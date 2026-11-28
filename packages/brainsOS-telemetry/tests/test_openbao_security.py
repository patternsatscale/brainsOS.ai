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

    import socket as _socket

    monkeypatch.delenv("TOOL_EGRESS_REQUIRE_PROXY_AUTH", raising=False)
    monkeypatch.delenv("TOOL_EGRESS_PROXY_SECRET", raising=False)
    monkeypatch.delenv("TOOL_EGRESS_PROXY_TOKENS", raising=False)

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        if host in ("api.firecrawl.dev", "api.tavily.com", "api.github.com", "github.com"):
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        raise _socket.gaierror(f"offline test DNS blocked for {host}")

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_getaddrinfo)

    # SSRF checks
    assert mod.is_blocked_destination("169.254.169.254") is not None
    assert mod.is_blocked_destination("fd00:ec2::254") is not None
    assert mod.is_blocked_destination("127.0.0.1") is not None
    assert mod.is_blocked_destination("10.0.0.5") is not None
    assert mod.is_blocked_destination("172.18.0.4") is not None
    assert mod.is_blocked_destination("localhost") is not None
    assert mod.is_blocked_destination("1.1.1.1") is None
    # DNS OSError fails closed (#406 INFO-2)
    assert mod.is_blocked_destination("nxdomain.invalid.local") is not None

    addon = mod.OpenBaoEgressAddon()
    addon._secrets_cache = {"FIRECRAWL_API_KEY": "fc-vault-secret"}
    addon._secrets_expires_at = 9999999999.0
    addon._allowed_ips = {"172.22.0.10"}
    addon._last_dns_check = 9999999999.0

    def make_flow(
        host: str,
        *,
        pretty_host: str | None = None,
        scheme: str = "https",
        sni: str | None = None,
        client_ip: str = "172.22.0.10",
        peername: tuple[str, int] | None = ("1.1.1.1", 443),
        content: bytes = b"",
    ):
        eff_pretty = pretty_host if pretty_host is not None else host
        req = SimpleNamespace(
            host=host,
            pretty_host=eff_pretty,
            scheme=scheme,
            url=f"{scheme}://{eff_pretty}/v1/scrape",
            headers={},
            content=content,
        )
        req.set_text = lambda text: setattr(req, "content", text.encode("utf-8"))
        return SimpleNamespace(
            request=req,
            client_conn=SimpleNamespace(peername=(client_ip, 50000)),
            server_conn=SimpleNamespace(sni=host if sni is None else sni, peername=peername),
            response=None,
        )

    # Mismatched SNI denied
    bad_sni = make_flow("api.firecrawl.dev", sni="evil.example.com")
    addon.request(bad_sni)
    assert bad_sni.response.status_code == 403

    # Empty SNI denied
    empty_sni = make_flow("api.firecrawl.dev", sni="")
    addon.request(empty_sni)
    assert empty_sni.response.status_code == 403

    # host vs pretty_host mismatch denied
    mismatch_host = make_flow("api.firecrawl.dev", pretty_host="evil.example.com")
    addon.request(mismatch_host)
    assert mismatch_host.response.status_code == 403

    # HTTP downgrade denied
    http_flow = make_flow("api.firecrawl.dev", scheme="http", sni="")
    addon.request(http_flow)
    assert http_flow.response.status_code == 403

    # http_connect, server_connect, server_connected, and post-connect peername SSRF blocks
    assert mod.is_blocked_destination("100.64.0.1") is not None
    assert mod.is_blocked_destination("::ffff:169.254.169.254") is not None
    assert mod.is_blocked_destination("fd12::1") is not None
    assert mod.is_blocked_destination("172.17.0.1") is not None

    connect_ssrf = make_flow("169.254.169.254")
    addon.http_connect(connect_ssrf)
    assert connect_ssrf.response.status_code == 403

    killed = []
    srv_obj = SimpleNamespace(peername=("172.17.0.1", 443), address=("172.17.0.1", 443), sni="api.firecrawl.dev", error=None)
    hook_data = SimpleNamespace(server=srv_obj, kill=lambda: killed.append(True))
    addon.server_connect(hook_data)
    assert srv_obj.error is not None and killed == [True]

    killed_post = []
    srv_post = SimpleNamespace(peername=("169.254.170.2", 443), address=("api.firecrawl.dev", 443), sni="api.firecrawl.dev", error=None)
    addon.server_connected(SimpleNamespace(server=srv_post, kill=lambda: killed_post.append(True)))
    assert srv_post.error is not None and killed_post == [True]

    peer_ssrf = make_flow("api.firecrawl.dev", peername=("127.0.0.1", 443))
    addon.request(peer_ssrf)
    assert peer_ssrf.response.status_code == 403

    # Valid caller + TLS + SNI -> injected in transit and redacted on response
    ok_flow = make_flow("api.firecrawl.dev")
    addon.request(ok_flow)
    assert ok_flow.response is None
    assert ok_flow.request.headers["Authorization"] == "Bearer fc-vault-secret"
    addon.response(ok_flow)
    assert ok_flow.request.headers["Authorization"] == mod.REDACTED_MARKER

    # Tavily uses Authorization: Bearer and scrubs api_key from JSON body
    addon._secrets_cache["TAVILY_API_KEY"] = "tvly-vault-secret"
    tavily_flow = make_flow(
        "api.tavily.com",
        content=json.dumps({"query": "test", "api_key": mod.DUMMY_PLACEHOLDER}).encode("utf-8"),
    )
    addon.request(tavily_flow)
    assert tavily_flow.response is None
    assert tavily_flow.request.headers["Authorization"] == "Bearer tvly-vault-secret"
    assert "api_key" not in json.loads(tavily_flow.request.content.decode("utf-8"))
    addon.response(tavily_flow)
    assert tavily_flow.request.headers["Authorization"] == mod.REDACTED_MARKER
    assert "tvly-vault-secret" not in tavily_flow.request.content.decode("utf-8")


def test_openbao_client_rejects_data_dir_seal_and_uses_external_writer_token(tmp_path, monkeypatch):
    """Verify F10 openbao_client ignores .seal.json inside data_dir and reads externalized writer token."""
    data_dir = tmp_path / "data"
    bad_seal_dir = data_dir / "control_plane" / "openbao"
    bad_seal_dir.mkdir(parents=True)
    (bad_seal_dir / ".seal.json").write_text('{"root_token": "hvs.bad-data-dir-token"}', encoding="utf-8")

    monkeypatch.delenv("OPENBAO_TOKEN", raising=False)
    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAINSOS_OPENBAO_WRITER_TOKEN_FILE", str(bad_seal_dir / "token.txt"))
    monkeypatch.setenv("BRAINSOS_OPENBAO_SEAL_FILE", str(bad_seal_dir / ".seal.json"))
    monkeypatch.setenv("OPENBAO_ADDR", "https://openbao:8200")
    monkeypatch.setenv("BRAINSOS_STAGE", "test")

    assert put_tool_secrets(str(tmp_path), {"TAVILY_API_KEY": "tvly-test"}) is False

    ext_tok = tmp_path / "external_secrets" / "openbao-system-api.token"
    ext_tok.parent.mkdir(parents=True)
    ext_tok.write_text("hvs.writer-token-ok\n", encoding="utf-8")
    monkeypatch.setenv("BRAINSOS_OPENBAO_WRITER_TOKEN_FILE", str(ext_tok))

    seen_tokens = []

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

    def fake_open(req, timeout=3.0, **kwargs):
        seen_tokens.append(req.headers.get("X-vault-token"))
        if req.get_method() == "GET":
            return FakeResp(200, {"data": {"data": {}}})
        return FakeResp(200, {"data": {"version": 1}})

    with patch("brainsos_telemetry.openbao_client.urllib.request.urlopen", side_effect=fake_open):
        assert put_tool_secrets(str(tmp_path), {"TAVILY_API_KEY": "tvly-test"}) is True
    assert seen_tokens == ["hvs.writer-token-ok", "hvs.writer-token-ok"]


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


def test_openbao_web_ui_oidc_and_caddy_isolation() -> None:
    """Verify #393 OpenBao Web UI, Authentik OIDC wiring, Caddy routing & Portal subsystem icon."""
    hcl = (REPO_ROOT / "config/openbao/openbao.hcl").read_text(encoding="utf-8")
    assert "ui = true" in hcl

    compose_ctrl = (REPO_ROOT / "docker/compose/compose.control.yml").read_text(encoding="utf-8")
    openbao_section = compose_ctrl.split("openbao:", 1)[1]
    assert "brainsos-ingress-net:" in openbao_section
    assert "ports:" not in openbao_section
    assert "caddy_root.crt:/etc/ssl/caddy/root.crt:ro" in openbao_section

    blueprint = (REPO_ROOT / "config/authentik/blueprints/brainsos-portal.yaml").read_text(encoding="utf-8")
    assert 'client_id: "openbao-vault"' in blueprint
    assert "/ui/vault/auth/oidc/oidc/callback" in blueprint

    setup_secrets = (REPO_ROOT / "scripts/setup/setup-secrets.sh").read_text(encoding="utf-8")
    assert "--sync-oidc" in setup_secrets
    assert 'default_role="admin"' in setup_secrets
    assert "openbao-admin" in setup_secrets

    for caddy_name in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
        caddy_txt = (REPO_ROOT / caddy_name).read_text(encoding="utf-8")
        assert "handle @openbao_paths {" in caddy_txt
        assert caddy_txt.index("handle @openbao_paths {") < caddy_txt.index("handle @litellm_ui {")
        assert caddy_txt.index("handle @openbao_paths {") < caddy_txt.index("handle @litellm_api {")
        assert "/ui/vault/" in caddy_txt

    subsystems = (REPO_ROOT / "packages/brainsOS-portal/src/data/subsystems.ts").read_text(encoding="utf-8")
    assert 'id: "secrets"' in subsystems
    assert 'route: "/secrets/"' in subsystems


def _extract_caddy_brace_block(text: str, header_prefix: str) -> str:
    """Return the brace-balanced Caddy block starting at `header_prefix`."""
    idx = text.find(header_prefix)
    assert idx != -1, f"Missing block {header_prefix!r}"
    brace_start = text.find("{", idx)
    assert brace_start != -1, f"Missing opening brace for {header_prefix!r}"
    depth = 0
    for pos in range(brace_start, len(text)):
        ch = text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[idx : pos + 1]
    raise AssertionError(f"Unclosed brace block for {header_prefix!r}")


def _run_caddy_adapt(cfg_name: str, *, alb_oidc: str = "true", wizard_completed: str = "true") -> dict | None:
    """Run `caddy adapt` via local binary or `brainsos-caddy:latest` if available."""
    import shutil

    caddy_bin = shutil.which("caddy")
    if caddy_bin:
        env = os.environ.copy()
        env["AUTH_ALB_OIDC_ENABLED"] = alb_oidc
        env["BRAINSOS_WIZARD_COMPLETED"] = wizard_completed
        proc = subprocess.run(
            [caddy_bin, "adapt", "--config", str(REPO_ROOT / "config/caddy" / cfg_name), "--adapter", "caddyfile"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert proc.returncode == 0, f"caddy adapt failed for {cfg_name}: {proc.stderr}"
        return json.loads(proc.stdout)

    docker_bin = shutil.which("docker")
    if docker_bin:
        inspect = subprocess.run(
            [docker_bin, "image", "inspect", "brainsos-caddy:latest"],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect.returncode == 0:
            proc = subprocess.run(
                [
                    docker_bin,
                    "run",
                    "--rm",
                    "-e",
                    f"AUTH_ALB_OIDC_ENABLED={alb_oidc}",
                    "-e",
                    f"BRAINSOS_WIZARD_COMPLETED={wizard_completed}",
                    "-v",
                    f"{REPO_ROOT / 'config/caddy'}:/etc/caddy:ro",
                    "--entrypoint",
                    "caddy",
                    "brainsos-caddy:latest",
                    "adapt",
                    "--config",
                    f"/etc/caddy/{cfg_name}",
                    "--adapter",
                    "caddyfile",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"docker caddy adapt failed for {cfg_name}: {proc.stderr}"
            return json.loads(proc.stdout)

    return None


def test_caddy_openbao_v1_and_system_public_routes_not_shadowed() -> None:
    """Verify LiteLLM catch-alls exclude OpenBao /v1/* & /ui/* prefixes and @system_public_status precedes auth."""
    openbao_v1_prefixes = (
        "/v1/sys/*",
        "/v1/auth/*",
        "/v1/secret/*",
        "/v1/identity/*",
        "/v1/cubbyhole/*",
    )
    openbao_ui_prefixes = (
        "/ui/vault",
        "/ui/vault/*",
        "/ui/assets/*",
        "/ui/engines-dist/*",
        "/ui/sw*",
        "/ui/favicon.svg",
        "/ui/opensearch.xml",
    )

    for cfg_name in ("Caddyfile", "Caddyfile.appliance"):
        caddy_txt = (REPO_ROOT / "config/caddy" / cfg_name).read_text(encoding="utf-8")

        for matcher_name in ("@proxy_api_path {", "@litellm_api {", "@litellm_ui_referer {"):
            block = _extract_caddy_brace_block(caddy_txt, matcher_name)
            assert "not path" in block, f"{cfg_name} {matcher_name} missing `not path` exclusion"
            for prefix in openbao_v1_prefixes:
                assert prefix in block, f"{cfg_name} {matcher_name} missing OpenBao exclusion {prefix}"

        ui_block = _extract_caddy_brace_block(caddy_txt, "@litellm_ui {")
        assert "not path" in ui_block, f"{cfg_name} @litellm_ui missing `not path` exclusion"
        for prefix in openbao_ui_prefixes:
            assert prefix in ui_block, f"{cfg_name} @litellm_ui missing OpenBao exclusion {prefix}"

        sys_block = _extract_caddy_brace_block(caddy_txt, "handle /api/v1/system/* {")
        assert "@system_public_status {" in sys_block
        assert "handle @system_public_status {" in sys_block
        assert sys_block.index("handle @system_public_status {") < sys_block.index(
            "import system_api_auth_{$BRAINSOS_WIZARD_COMPLETED:true}"
        )

        adapted = _run_caddy_adapt(cfg_name, alb_oidc="true", wizard_completed="true")
        if adapted is None:
            continue

        servers = adapted.get("apps", {}).get("http", {}).get("servers", {})
        assert servers, f"No HTTP servers in adapted {cfg_name}"

        def _inspect_route_list(routes: list[dict], *, site_label: str) -> None:
            openbao_idx: int | None = None
            ui_idx: int | None = None
            ui_excluded_openbao = False
            for idx, r in enumerate(routes):
                matches = r.get("match", [])
                for m in matches:
                    paths = m.get("path", [])
                    if "/v1/*" in paths:
                        not_blocks = m.get("not", [])
                        excluded: set[str] = set()
                        for nb in not_blocks:
                            excluded.update(nb.get("path", []))
                        assert set(openbao_v1_prefixes).issubset(excluded), (
                            f"{cfg_name} {site_label} route[{idx}] matches /v1/* without excluding OpenBao prefixes: {m}"
                        )
                    if "/ui/vault/*" in paths:
                        openbao_idx = idx
                    if "/ui/*" in paths:
                        ui_idx = idx
                        not_blocks = m.get("not", [])
                        excluded_ui: set[str] = set()
                        for nb in not_blocks:
                            excluded_ui.update(nb.get("path", []))
                        ui_excluded_openbao = set(openbao_ui_prefixes).issubset(excluded_ui)
                        assert ui_excluded_openbao, (
                            f"{cfg_name} {site_label} route[{idx}] matches /ui/* without excluding OpenBao UI prefixes: {m}"
                        )
                    if paths == ["/api/v1/system/*"]:
                        handlers = r.get("handle", [])
                        subroutes = [h for h in handlers if h.get("handler") == "subroute"]
                        assert subroutes, f"{cfg_name} {site_label} /api/v1/system/* missing subroute"
                        nested = subroutes[0].get("routes", [])
                        assert len(nested) >= 2, f"{cfg_name} {site_label} /api/v1/system/* expected >=2 nested routes"
                        first_match = nested[0].get("match", [])
                        assert first_match, f"{cfg_name} {site_label} nested[0] must be @system_public_status"
                        assert first_match[0].get("method") == ["GET"]
                        assert "/api/v1/system/health" in first_match[0].get("path", [])
                        assert "match" not in nested[1], (
                            f"{cfg_name} {site_label} nested[1] must be default auth-gated fallback"
                        )

                for h in r.get("handle", []):
                    if h.get("handler") == "subroute" and isinstance(h.get("routes"), list):
                        # Do not conflate nested /api/v1/system/* subroutes with outer site routes
                        if not any(m.get("path") == ["/api/v1/system/*"] for m in matches):
                            _inspect_route_list(h["routes"], site_label=site_label)

            if openbao_idx is not None and ui_idx is not None and not ui_excluded_openbao:
                assert openbao_idx < ui_idx, (
                    f"{cfg_name} {site_label}: @openbao_paths ({openbao_idx}) must precede /ui/* ({ui_idx})"
                )

        for srv_name, srv in servers.items():
            for r_idx, top_route in enumerate(srv.get("routes", [])):
                for h in top_route.get("handle", []):
                    if h.get("handler") == "subroute":
                        _inspect_route_list(h.get("routes", []), site_label=f"{srv_name}.routes[{r_idx}]")


def test_egress_addon_v2_signed_token_repo_allowlist_and_explicit_empty_tenant_env(monkeypatch) -> None:
    """Verify signed v2 proxy token binds repos claim, blocks repos: [] fail-closed, and prevents empty tenant env fallback."""
    import base64
    import hashlib
    import hmac
    import sys
    import time
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
    spec = importlib.util.spec_from_file_location("egress_addon_v2_test", addon_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import socket as _socket

    def _fake_gh_dns(host, port, *args, **kwargs):
        if host in ("api.github.com", "github.com"):
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("140.82.113.4", 443))]
        raise _socket.gaierror(f"offline test DNS blocked for {host}")

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_gh_dns)

    secret = "egress-hmac-secret-test"
    monkeypatch.setenv("TOOL_EGRESS_PROXY_SECRET", secret)
    monkeypatch.delenv("TOOL_EGRESS_PROXY_TOKENS", raising=False)
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "org/bawtford-repo")

    def _mint_v2(tenant: str, repos: list[str] | None) -> str:
        payload: dict[str, object] = {"t": tenant, "exp": int(time.time()) + 300}
        if repos is not None:
            payload["repos"] = repos
        b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
        sig = hmac.new(secret.encode(), f"v2.{b64}".encode(), hashlib.sha256).hexdigest()
        return f"v2.{b64}.{sig}"

    def _make_gh_flow(host: str, path: str, auth_hdr: str | None = None, client_conn=None):
        hdrs = {}
        if auth_hdr is not None:
            hdrs["Proxy-Authorization"] = auth_hdr
        req = SimpleNamespace(
            host=host,
            pretty_host=host,
            scheme="https",
            path=path,
            url=f"https://{host}{path}",
            headers=hdrs,
            content=b"",
        )
        return SimpleNamespace(
            request=req,
            client_conn=client_conn or SimpleNamespace(peername=("172.28.1.50", 40000)),
            server_conn=SimpleNamespace(sni=host, peername=("140.82.113.4", 443)),
            response=None,
        )

    addon = mod.OpenBaoEgressAddon()
    addon._secrets_cache = {"GITHUB_TOKEN": "ghp_real_secret_token"}
    addon._secrets_expires_at = 9999999999.0

    # 1. marvin with signed repos=[] is denied 403 even though global GITHUB_ALLOWED_REPOS is set
    marvin_conn = SimpleNamespace(peername=("172.28.1.51", 40001))
    marvin_tok = _mint_v2("marvin", [])
    c_flow = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", f"Bearer {marvin_tok}", marvin_conn)
    addon.http_connect(c_flow)
    assert c_flow.response is None
    r_flow = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", None, marvin_conn)
    addon.request(r_flow)
    assert r_flow.response is not None and r_flow.response.status_code == 403

    # 2. bawtford with signed repos=["org/bawtford-repo"] allowed on that repo, denied on other repo
    bawt_conn = SimpleNamespace(peername=("172.28.1.52", 40002))
    bawt_tok = _mint_v2("bawtford", ["org/bawtford-repo"])
    addon.http_connect(_make_gh_flow("api.github.com", "/", f"Bearer {bawt_tok}", bawt_conn))
    ok_req = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", None, bawt_conn)
    addon.request(ok_req)
    assert ok_req.response is None
    assert ok_req.request.headers["Authorization"] == "Bearer ghp_real_secret_token"

    bad_req = _make_gh_flow("api.github.com", "/repos/org/other-repo/issues", None, bawt_conn)
    addon.request(bad_req)
    assert bad_req.response is not None and bad_req.response.status_code == 403

    # 3. Tampered v2 payload rejected with 407 on CONNECT
    tamper_payload = base64.urlsafe_b64encode(
        json.dumps({"t": "marvin", "exp": int(time.time()) + 300, "repos": ["org/bawtford-repo"]}).encode()
    ).decode().rstrip("=")
    tampered_tok = f"v2.{tamper_payload}.{marvin_tok.split('.')[2]}"
    tamper_flow = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", f"Bearer {tampered_tok}")
    addon.http_connect(tamper_flow)
    assert tamper_flow.response is not None and tamper_flow.response.status_code == 407

    # 4. Explicitly empty GITHUB_ALLOWED_REPOS_ALICE="" blocks alice without falling back to global GITHUB_ALLOWED_REPOS
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS_ALICE", "")
    alice_tok = _mint_v2("alice", ["org/bawtford-repo"])
    alice_conn = SimpleNamespace(peername=("172.28.1.53", 40003))
    addon.http_connect(_make_gh_flow("api.github.com", "/", f"Bearer {alice_tok}", alice_conn))
    alice_req = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", None, alice_conn)
    addon.request(alice_req)
    assert alice_req.response is not None and alice_req.response.status_code == 403

    # 5. Unset GITHUB_ALLOWED_REPOS with repos omitted fails closed (403) (#406 HIGH-2)
    monkeypatch.delenv("GITHUB_ALLOWED_REPOS", raising=False)
    dave_tok = _mint_v2("dave", None)
    dave_conn = SimpleNamespace(peername=("172.28.1.54", 40004))
    addon.http_connect(_make_gh_flow("api.github.com", "/", f"Bearer {dave_tok}", dave_conn))
    dave_req = _make_gh_flow("api.github.com", "/repos/org/bawtford-repo/issues", None, dave_conn)
    addon.request(dave_req)
    assert dave_req.response is not None and dave_req.response.status_code == 403

    # 6. Explicit "*" wildcard allows GitHub access while still blocking traversal
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "*")
    star_req = _make_gh_flow("api.github.com", "/repos/any/repo/issues", None, dave_conn)
    addon.request(star_req)
    assert star_req.response is None
    trav_req = _make_gh_flow("api.github.com", "/repos/any/../../evil", None, dave_conn)
    addon.request(trav_req)
    assert trav_req.response is not None and trav_req.response.status_code == 403


