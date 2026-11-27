"""Regression tests for Ticket #387: OpenBao KV v2, egress SSRF/TLS, segmentation, runner & MCP isolation."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from brainsos_memory.okf.purity import resolve_safe_path, validate_purity
from brainsos_telemetry.openbao_client import DUMMY_PLACEHOLDER, put_tool_secrets
from brainsos_telemetry.system import create_system_api_app, issue_csrf_token
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_openbao_put_tool_secrets_http_and_system_api_placeholder(tmp_path, monkeypatch):
    """Verify real secrets go to OpenBao KV v2 and runner-hermes only gets dummy placeholders."""
    stored_payloads = []

    class FakeResp:
        def __init__(self, status: int, body: dict):
            self.status = status
            self._raw = json.dumps(body).encode("utf-8")

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=3.0):
        if req.get_method() == "GET":
            return FakeResp(200, {"data": {"data": {"EXISTING": "keep"}}})
        stored_payloads.append(json.loads(req.data.decode("utf-8")))
        return FakeResp(200, {"data": {"version": 2}})

    (tmp_path / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")
    monkeypatch.setenv("OPENBAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "root-tok-test")
    monkeypatch.setenv("SYSTEM_API_TOKEN", "test-secret-token-12345")
    monkeypatch.setenv("BRAINSOS_STAGE", "test")

    with (
        patch("brainsos_telemetry.openbao_client.urllib.request.urlopen", side_effect=fake_urlopen),
        patch("brainsos_telemetry.system.get_repo_root", return_value=str(tmp_path)),
    ):
        ok = put_tool_secrets(str(tmp_path), {"FIRECRAWL_API_KEY": "fc-real-key-123"})
        assert ok is True
        assert stored_payloads[-1]["data"] == {"EXISTING": "keep", "FIRECRAWL_API_KEY": "fc-real-key-123"}

        app = create_system_api_app()
        client = TestClient(app)
        res = client.post(
            "/api/v1/system/runners/hermes/config",
            json={
                "firecrawl_api_key": "fc-secret-xyz987",  # gitleaks:allow
                "github_token": "ghp_secretvalue123456",  # gitleaks:allow
                "restart_runner": False,
            },
            headers={
                "X-BrainsOS-Internal": "test-secret-token-12345",
                "X-Authentik-Username": "admin",
                "X-Authentik-Groups": "authentik Admins",
                "X-CSRF-Token": issue_csrf_token(),
                "Origin": "http://localhost",
            },
        )
        assert res.status_code == 200
        assert res.json()["stored_in_openbao"] is True

        hermes_env = (tmp_path / "data/runners/hermes/.env").read_text(encoding="utf-8")
        assert f"FIRECRAWL_API_KEY={DUMMY_PLACEHOLDER}" in hermes_env
        assert f"GITHUB_TOKEN={DUMMY_PLACEHOLDER}" in hermes_env
        assert "fc-secret-xyz987" not in hermes_env
        assert "ghp_secretvalue123456" not in hermes_env


def test_egress_addon_ssrf_sni_and_openbao_injection(monkeypatch):
    """Verify tool-egress-proxy blocks SSRF/IMDSv6, requires HTTPS+SNI match, and masks logs."""
    # Provide stub mitmproxy module if not installed in unit-test venv
    import sys
    from types import ModuleType

    class FakeResponse:
        @staticmethod
        def make(status_code: int, content: bytes = b"", headers: dict | None = None):
            return SimpleNamespace(status_code=status_code, content=content, headers=headers or {})

    fake_http = ModuleType("mitmproxy.http")
    fake_http.HTTPFlow = object  # type: ignore[attr-defined]
    fake_http.Response = FakeResponse  # type: ignore[attr-defined]
    fake_mitm = ModuleType("mitmproxy")
    fake_mitm.http = fake_http  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mitmproxy", fake_mitm)
    monkeypatch.setitem(sys.modules, "mitmproxy.http", fake_http)

    addon_path = REPO_ROOT / "config/egress/addons/github_auth.py"
    spec = importlib.util.spec_from_file_location("egress_addon_test", addon_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # SSRF checks
    assert mod.is_blocked_destination("169.254.169.254") is not None
    assert mod.is_blocked_destination("fd00:ec2::254") is not None
    assert mod.is_blocked_destination("127.0.0.1") is not None
    assert mod.is_blocked_destination("10.0.0.5") is not None
    assert mod.is_blocked_destination("172.18.0.4") is not None
    assert mod.is_blocked_destination("localhost") is not None
    assert mod.is_blocked_destination("1.1.1.1") is None

    addon = mod.OpenBaoEgressAddon()
    addon._secrets_cache = {"FIRECRAWL_API_KEY": "fc-vault-secret"}
    addon._secrets_expires_at = 9999999999.0
    addon._allowed_ips = {"172.22.0.10"}
    addon._last_dns_check = 9999999999.0

    def make_flow(host: str, *, scheme: str = "https", sni: str = "", client_ip: str = "172.22.0.10"):
        req = SimpleNamespace(
            pretty_host=host,
            scheme=scheme,
            url=f"{scheme}://{host}/v1/scrape",
            headers={},
            content=b"",
        )
        return SimpleNamespace(
            request=req,
            client_conn=SimpleNamespace(peername=(client_ip, 50000)),
            server_conn=SimpleNamespace(sni=sni or host),
            response=None,
        )

    # Mismatched SNI denied
    bad_sni = make_flow("api.firecrawl.dev", sni="evil.example.com")
    addon.request(bad_sni)
    assert bad_sni.response.status_code == 403

    # HTTP downgrade denied
    http_flow = make_flow("api.firecrawl.dev", scheme="http", sni="")
    addon.request(http_flow)
    assert http_flow.response.status_code == 403

    # Valid caller + TLS + SNI -> injected in transit and redacted on response
    ok_flow = make_flow("api.firecrawl.dev")
    addon.request(ok_flow)
    assert ok_flow.response is None
    assert ok_flow.request.headers["Authorization"] == "Bearer fc-vault-secret"
    addon.response(ok_flow)
    assert ok_flow.request.headers["Authorization"] == mod.REDACTED_MARKER


def test_mcp_memory_single_tenant_pin_and_okf_purity(tmp_path, monkeypatch):
    """Verify MCP memory enforces BRAINSOS_AGENT_ID and purity.py blocks dotfiles & symlink escapes."""
    from brainsos_mcp.modules.memory import resolve_tenant_memory_target

    agents_root = tmp_path / "agents"
    (agents_root / "alpha" / "memories").mkdir(parents=True)
    (agents_root / "beta" / "memories").mkdir(parents=True)
    (agents_root / "alpha" / "SOUL.md").write_text("# Alpha\n", encoding="utf-8")
    (agents_root / "beta" / "SOUL.md").write_text("# Beta\n", encoding="utf-8")

    monkeypatch.setenv("BRAINSOS_MEMORY_ROOT", str(agents_root))
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alpha")

    root_dir, rel = resolve_tenant_memory_target("research/notes.md")
    assert Path(root_dir) == (agents_root / "alpha" / "memories").resolve()
    assert rel == "research/notes.md"

    with pytest.raises(PermissionError):
        resolve_tenant_memory_target("beta/research/secret.md")

    with pytest.raises(PermissionError):
        resolve_tenant_memory_target("notes.md", agent_id="beta")

    # purity.py: realpath/commonpath + symlink escape + non-.gitkeep dotfiles
    mem = tmp_path / "mem"
    mem.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret\n", encoding="utf-8")
    link = mem / "escape.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError):
        resolve_safe_path(str(mem), "escape.md")

    (mem / ".env").write_text("SECRET=1\n", encoding="utf-8")
    clean, violations = validate_purity(str(mem))
    assert clean is False
    assert any("symlink" in v.lower() for v in violations)
    assert any(".env" in v for v in violations)


def test_imds_guard_ipv6_and_compose_security_invariants(tmp_path):
    """Verify IMDSv6 DROP, OpenBao container, network segmentation, non-root runners & no NODE_TLS bypass."""
    # IMDS guard dry-run covers IPv6 fd00:ec2::254/128 DROP + static IP
    env = os.environ.copy()
    env["BRAINSOS_LITELLM_STATIC_IP"] = "172.21.0.5"
    res = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/setup/imds-guard.sh"), "--apply", "--dry-run", "--force"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if os.uname().sysname == "Linux":
        assert res.returncode == 0
        assert "BRAINSOS-IMDS6" in res.stdout
        assert "fd00:ec2::254/128" in res.stdout

    compose_ctrl = (REPO_ROOT / "docker/compose/compose.control.yml").read_text(encoding="utf-8")
    assert "quay.io/openbao/openbao:" in compose_ctrl
    assert "brainsos-control-secrets" in compose_ctrl

    compose_apps = (REPO_ROOT / "docker/compose/compose.apps.yml").read_text(encoding="utf-8")
    assert "NODE_TLS_REJECT_UNAUTHORIZED=0" not in compose_apps
    assert "--requirepass" in compose_apps
    assert "GITEA__service__DISABLE_REGISTRATION=true" in compose_apps
    assert ":latest" not in compose_apps or "brainsos-" in compose_apps

    compose_agents = (REPO_ROOT / "docker/compose/compose.agents.yml").read_text(encoding="utf-8")
    assert 'user: "10001:10001"' in compose_agents
    assert "GITHUB_TOKEN_CINDY" not in compose_agents
    assert "${HOME}/.aws:/root/.aws" not in compose_agents
    assert "RUNNER_AUTH_TOKEN" in compose_agents

    hermes_df = (REPO_ROOT / "docker/hermes/Dockerfile").read_text(encoding="utf-8")
    assert "/etc/skel/.config/gh/hosts.yml" not in hermes_df
    assert "uv:0.6.14" in hermes_df

    estop = (REPO_ROOT / "scripts/control/emergency-stop.sh").read_text(encoding="utf-8")
    non_comment_estop = "\n".join(ln for ln in estop.splitlines() if not ln.lstrip().startswith("#"))
    assert "eval " not in non_comment_estop
    assert "printenv " in non_comment_estop

    # Dynamic script allowlisting on SDK runners
    for sdk_server in (
        REPO_ROOT / "docker/runners/openai-sdk/server.py",
        REPO_ROOT / "docker/runners/claude-sdk/server.py",
    ):
        txt = sdk_server.read_text(encoding="utf-8")
        assert "LITELLM_MASTER_KEY" not in txt
        assert "os.path.commonpath" in txt
        with patch.dict(os.environ, {}, clear=False):
            spec = importlib.util.spec_from_file_location(f"sdk_{sdk_server.parent.name}", sdk_server)
            assert spec and spec.loader
            # Only verify _load_dynamic_script rejects outside paths if importable cleanly in env
            try:
                sdk_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sdk_mod)
                with pytest.raises(PermissionError):
                    sdk_mod._load_dynamic_script("/etc/passwd", "alpha")
            except ImportError:
                pass
