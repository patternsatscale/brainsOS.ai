"""Opaque-box E2E Tests for v0.5.3 RC3 Pre-AMI Security Hardening (#397: #405-#408).

Covers Features F1-F14 across Tiers 1-4, plus local Docker runtime verification
and the LOW-3 deferral guard (ViewportFrame.tsx untouched).
Zero reliance on live AWS or external SaaS tooling.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from .conftest import (
    REPO_ROOT,
    extract_caddy_block,
    load_yaml,
    read_repo_text,
)

pytestmark = [pytest.mark.e2e]


# ------------------------------------------------------------------------------
# Local Opaque-Box Helpers
# ------------------------------------------------------------------------------


def _docker_daemon_ready() -> bool:
    if not shutil.which("docker"):
        return False
    res = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5, check=False)
    return res.returncode == 0


def _pick_python_docker_image() -> str | None:
    for candidate in ("python:3.12-slim-bookworm", "brainsos-runner-base:latest"):
        res = subprocess.run(["docker", "image", "inspect", candidate], capture_output=True, check=False)
        if res.returncode == 0:
            return candidate
    return None


def _parse_set_cookies(res) -> list[str]:
    if hasattr(res.headers, "get_list"):
        return [c for c in res.headers.get_list("set-cookie") if c]
    raw = res.headers.get("set-cookie", "")
    return [raw] if raw else []


def _parse_env_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _isolated_script_env(repo_root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAINSOS_")}
    env["BRAINSOS_REPO_ROOT"] = str(repo_root)
    env["BRAINSOS_ENV_FILE"] = str(repo_root / ".env")
    if extra:
        env.update(extra)
    return env


def _prepare_firstboot_tree(tmp_path: Path, name: str = "brainsos") -> Path:
    root = tmp_path / name
    (root / "scripts" / "control").mkdir(parents=True, exist_ok=True)
    (root / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True, exist_ok=True)
    for rel in (
        "scripts/control/generate-env.sh",
        "scripts/control/env-upsert.sh",
        "packages/brainsOS-appliance/scripts/firstboot.sh",
        ".env.example",
    ):
        shutil.copy2(REPO_ROOT / rel, root / rel)
        if rel.endswith(".sh"):
            (root / rel).chmod(0o755)
    subprocess.run(
        ["git", "-c", "user.email=test@brainsos.ai", "-c", "user.name=test", "init", "--quiet"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


def _build_env_for_compose(tmp_path: Path) -> Path:
    """Create a deterministic temporary .env from .env.example for compose config checks."""
    env_out = tmp_path / "compose.env"
    lines = read_repo_text(".env.example").splitlines()
    rendered: list[str] = []
    for raw in lines:
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not v:
                v = f"ci-dummy-{k.lower()}-0123456789abcdef"
            rendered.append(f"{k}={v}")
        else:
            rendered.append(raw)
    env_out.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    os.chmod(env_out, 0o600)
    return env_out


def _caddy_handler_requires_admin_auth(caddy_text: str, handler_block: str) -> bool:
    """Return True if handler_block enforces authentik_admin_forward_auth directly or via imported snippet."""
    if not handler_block:
        return False
    if "authentik_admin_forward_auth" in handler_block:
        return True
    for snippet_name in re.findall(r"import\s+([A-Za-z0-9_]+)", handler_block):
        snippet_blk = extract_caddy_block(caddy_text, f"({snippet_name})")
        if "authentik_admin_forward_auth" in snippet_blk:
            return True
    return False


# ==============================================================================
# TIER 1: Feature Coverage (F1-F14 + LOW-3 Guard)
# ==============================================================================


@pytest.mark.tier1
class TestTier1RC3Features:
    # --- F1: Pre-wizard /identity & /status redaction (#405 HIGH-1) ---
    def test_f1_prewizard_unauth_identity_and_status_are_redacted(self, isolated_repo, system_api_client_factory):
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=test\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=false\n"
                "BRAINSOS_UNIT_NAME=Unit-RC3\n"
                "BRAINSOS_URL=https://unit.brainsos.ai\n"
                "BRAINSOS_TLS_MODE=internal\n"
                "BRAINSOS_ADMIN_EMAIL=secret-admin@brainsos.ai\n"
                "BRAINSOS_USER_SUB=secret-sub-uuid\n"
                "BRAINSOS_INSTANCE_ID=i-0123456789abcdef0\n"
            ),
            wizard_completed=False,
        )
        allowed_keys = {"firstboot_wizard_completed", "unit_name", "url", "tls_mode"}
        forbidden_keys = {
            "admin_email",
            "user_sub",
            "instance_id",
            "local_ipv4",
            "public_ipv4",
            "repo_root",
            "data_dir",
            "console_user",
            "suggested_local_domain",
            "os",
            "disk",
            "runners",
            "services",
            "git",
            "packages",
        }
        for path in ("/api/v1/system/identity", "/api/v1/system/status"):
            res = bundle["client"].get(path, headers=bundle["internal_headers"])
            assert res.status_code == 200, f"{path} returned {res.status_code}: {res.text}"
            data = res.json()
            assert data.get("firstboot_wizard_completed") is False
            assert set(data.keys()) <= allowed_keys, f"{path} leaked unexpected keys: {set(data.keys()) - allowed_keys}"
            assert not (set(data.keys()) & forbidden_keys)
            assert "secret-admin@brainsos.ai" not in res.text
            assert "secret-sub-uuid" not in res.text

        for caddy_rel in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
            caddy_txt = read_repo_text(caddy_rel)
            public_block = extract_caddy_block(caddy_txt, "@system_public_status")
            assert public_block, f"Missing @system_public_status matcher block in {caddy_rel}"
            public_tokens = public_block.split()
            assert "/api/v1/system/status" not in public_tokens, (
                f"{caddy_rel} must not bypass system_api_auth for /api/v1/system/status"
            )
            assert not any(
                tok.startswith("/api/v1/system/jobs") and tok != "/api/v1/system/jobs-active"
                for tok in public_tokens
            ), f"{caddy_rel} must not bypass system_api_auth for /api/v1/system/jobs/*"
            sys_block = extract_caddy_block(caddy_txt, "handle /api/v1/system/*")
            assert "import system_api_auth_{$BRAINSOS_WIZARD_COMPLETED:true}" in sys_block

    # --- F2: Bootstrap brute-force lockout & random fallback (#405 HIGH-1) ---
    def test_f2_bootstrap_token_lockout_returns_429_and_firstboot_random_fallback(
        self, isolated_repo, system_api_client_factory, monkeypatch
    ):
        monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0validtoken1234567")
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=test\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=false\n"
                "BRAINSOS_INSTANCE_ID=i-0validtoken1234567\n"
            ),
            wizard_completed=False,
        )
        # Use a dedicated isolated client IP so lockout state cannot bleed into other tests.
        isolated_client = TestClient(
            bundle["client"].app,
            cookies=bundle["client"].cookies,
            client=("203.0.113.202", 50000),
        )
        lockout_headers = {
            **bundle["internal_headers"],
            "X-CSRF-Token": bundle["csrf"],
            "Origin": "http://localhost",
            "X-Real-IP": "203.0.113.202",
            "X-Forwarded-For": "203.0.113.202",
        }
        statuses = []
        for idx in range(6):
            r = isolated_client.post(
                "/api/v1/system/setup",
                json={"bootstrap_token": f"wrong-guess-{idx}", "dry_run": True},
                headers=lockout_headers,
            )
            statuses.append(r.status_code)
        assert 429 in statuses, f"Expected 429 brute-force lockout within 6 failed attempts, got {statuses}"
        assert statuses[0] == 403, f"First failed attempt should return 403, got {statuses}"

        locked_valid = isolated_client.post(
            "/api/v1/system/setup",
            json={"bootstrap_token": "i-0validtoken1234567", "dry_run": True},
            headers=lockout_headers,
        )
        assert locked_valid.status_code == 429, "Valid bootstrap_token must stay blocked while IP is locked out"

        fb_txt = read_repo_text("packages/brainsOS-appliance/scripts/firstboot.sh")
        assert "i-appliance-${HOST_HASH" not in fb_txt

    # --- F3: Wizard session cookie & pre-SSO polling (#405 HIGH-1) ---
    def test_f3_wizard_session_cookie_attributes_and_pre_sso_polling(
        self, isolated_repo, system_api_client_factory, monkeypatch
    ):
        monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0wizardcookie12345")
        sd = isolated_repo / "scripts" / "control" / "set-domain.sh"
        sd.write_text("#!/usr/bin/env bash\necho dry-run-ok\n", encoding="utf-8")
        sd.chmod(0o755)
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=test\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=false\n"
                "BRAINSOS_INSTANCE_ID=i-0wizardcookie12345\n"
            ),
            wizard_completed=False,
        )
        https_client = TestClient(
            bundle["client"].app,
            base_url="https://testserver",
            cookies=bundle["client"].cookies,
        )
        unauth_headers = {**bundle["internal_headers"], "X-CSRF-Token": bundle["csrf"], "Origin": "http://localhost"}
        assert (
            https_client.post("/api/v1/system/dns-check", json={"domain": "example.com"}, headers=unauth_headers)
            .status_code
            in (401, 403)
        )
        assert (
            https_client.get("/api/v1/system/jobs/job-1111-2222", headers=bundle["internal_headers"]).status_code
            in (401, 403)
        )
        assert (
            https_client.get("/api/v1/system/jobs/job-1111-2222/stream", headers=bundle["internal_headers"])
            .status_code
            in (401, 403)
        )

        setup_res = https_client.post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": "i-0wizardcookie12345",
                "url": "unit.brainsos.ai",
                "tls_mode": "internal",
                "dry_run": True,
            },
            headers=unauth_headers,
        )
        assert setup_res.status_code == 200, setup_res.text
        wizard_cookies = [c for c in _parse_set_cookies(setup_res) if "brainsos_wizard_session=" in c]
        assert wizard_cookies, f"Missing brainsos_wizard_session Set-Cookie: {_parse_set_cookies(setup_res)}"
        cookie_hdr = wizard_cookies[0].lower()
        assert "httponly" in cookie_hdr and "secure" in cookie_hdr and "samesite=strict" in cookie_hdr

        dns_res = https_client.post("/api/v1/system/dns-check", json={"domain": "example.com"}, headers=unauth_headers)
        assert dns_res.status_code == 200
        status_res = https_client.get("/api/v1/system/status", headers=bundle["internal_headers"])
        assert status_res.status_code == 200 and "disk" in status_res.json()
        job_id = setup_res.headers.get("X-Job-ID", "job-nonexistent-0001")
        job_res = https_client.get(f"/api/v1/system/jobs/{job_id}", headers=bundle["internal_headers"])
        assert job_res.status_code in (200, 404)

        sys_mgr = read_repo_text("packages/brainsOS-portal/src/components/SystemManager.tsx")
        assert "credentials: 'include'" in sys_mgr or 'credentials: "include"' in sys_mgr

    # --- F4: Post-wizard System API RBAC & fail-closed groups (#405 HIGH-1) ---
    def test_f4_postwizard_viewer_shell_compatible_admin_endpoints_locked(
        self, isolated_repo, system_api_client_factory, monkeypatch
    ):
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=production\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=true\n"
                "BRAINSOS_UNIT_NAME=ProdUnit\n"
            ),
            wizard_completed=True,
        )
        monkeypatch.setenv("BRAINSOS_STAGE", "production")

        me = bundle["client"].get("/api/v1/system/me", headers=bundle["viewer_headers"])
        assert me.status_code == 200 and me.json()["is_superuser"] is False
        ident = bundle["client"].get("/api/v1/system/identity", headers=bundle["viewer_headers"])
        assert ident.status_code == 200 and "instance_id" not in ident.json()

        for method, path in (
            ("GET", "/api/v1/system/status"),
            ("GET", "/api/v1/system/runners"),
            ("GET", "/api/v1/system/jobs/job-uuid-9999"),
            ("GET", "/api/v1/system/jobs/job-uuid-9999/stream"),
            ("POST", "/api/v1/system/dns-check"),
        ):
            if method == "GET":
                r = bundle["client"].get(path, headers=bundle["viewer_headers"])
            else:
                r = bundle["client"].post(path, json={"domain": "example.com"}, headers=bundle["viewer_headers"])
            assert r.status_code == 403, f"Expected 403 for viewer on {method} {path}, got {r.status_code}"

        no_group_headers = {
            **bundle["internal_headers"],
            "X-Authentik-Username": "admin",
            "X-CSRF-Token": bundle["csrf"],
            "Origin": "http://localhost",
        }
        assert bundle["client"].get("/api/v1/system/status", headers=no_group_headers).status_code == 403
        assert bundle["client"].get("/api/v1/system/runners", headers=no_group_headers).status_code == 403
        assert bundle["client"].get("/api/v1/system/jobs/job-uuid-9999", headers=no_group_headers).status_code == 403
        assert bundle["client"].get("/api/v1/system/me", headers=no_group_headers).json()["is_superuser"] is False

    # --- F5: One-time INSTANCE_ID & locked OS admin password (#405 HIGH-3) ---
    def test_f5_os_admin_locked_independent_authentik_pw_and_postwizard_instance_id_disabled(
        self, isolated_repo, system_api_client_factory, tmp_path, monkeypatch
    ):
        root = _prepare_firstboot_tree(tmp_path, "fb_f5")
        env = _isolated_script_env(
            root,
            {
                "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
                "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
                "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
            },
        )
        proc = subprocess.run(
            ["bash", str(root / "packages/brainsOS-appliance/scripts/firstboot.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        vals = _parse_env_lines((root / ".env").read_text(encoding="utf-8"))
        assert vals.get("AUTHENTIK_BOOTSTRAP_PASSWORD")
        assert vals["AUTHENTIK_BOOTSTRAP_PASSWORD"] != vals.get("BRAINSOS_INSTANCE_ID", "")
        assert vals["AUTHENTIK_BOOTSTRAP_PASSWORD"] != vals.get("BRAINSOS_ADMIN_PASSWORD", "")

        for sh_rel in (
            "packages/brainsOS-appliance/scripts/firstboot.sh",
            "scripts/control/reload-env.sh",
            "scripts/control/set-domain.sh",
        ):
            txt = read_repo_text(sh_rel)
            assert "passwd -l admin" in txt, f"{sh_rel} must lock OS admin password via 'passwd -l admin'"
            assert "admin:${" not in txt or "chpasswd" not in txt, f"{sh_rel} must not set OS admin password via chpasswd"

        monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0onetimeonly123456")
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=test\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=true\n"
                "BRAINSOS_INSTANCE_ID=i-0onetimeonly123456\n"
            ),
            wizard_completed=True,
        )
        res = bundle["client"].post(
            "/api/v1/system/setup",
            json={"bootstrap_token": "i-0onetimeonly123456", "dry_run": True},
            headers={**bundle["internal_headers"], "X-CSRF-Token": bundle["csrf"], "Origin": "http://localhost"},
        )
        assert res.status_code == 403

    # --- F6: Default egress proxy auth & TOOL_EGRESS_PROXY_SECRET (#406 HIGH-2) ---
    def test_f6_egress_proxy_secret_generated_and_v2_token_minted_by_default(
        self, isolated_repo, tmp_path, monkeypatch
    ):
        assert "TOOL_EGRESS_PROXY_SECRET" in read_repo_text(".env.example")
        gen = isolated_repo / "scripts" / "control" / "generate-env.sh"
        gen.write_text(read_repo_text("scripts/control/generate-env.sh"), encoding="utf-8")
        gen.chmod(0o755)
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").write_text(
            read_repo_text("scripts/control/env-upsert.sh"), encoding="utf-8"
        )
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").chmod(0o755)
        (isolated_repo / ".env.example").write_text(read_repo_text(".env.example"), encoding="utf-8")
        (isolated_repo / ".env").unlink()

        r = subprocess.run(
            ["bash", str(gen), "--non-interactive", "--no-rebuild"],
            cwd=isolated_repo,
            env=_isolated_script_env(isolated_repo),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert r.returncode == 0, r.stderr
        env_vals = _parse_env_lines((isolated_repo / ".env").read_text(encoding="utf-8"))
        secret = env_vals.get("TOOL_EGRESS_PROXY_SECRET", "")
        assert len(secret) >= 32, "TOOL_EGRESS_PROXY_SECRET must be >= 32 chars"

        agents = load_yaml("docker/compose/compose.agents.yml")
        proxy_env = "\n".join(str(x) for x in agents["services"]["tool-egress-proxy"]["environment"])
        assert "TOOL_EGRESS_REQUIRE_PROXY_AUTH=" in proxy_env and "true" in proxy_env.lower()

        from brainsos_runner.clients.docker import EphemeralDockerRunnerClient
        from brainsos_runner.models import AgentTurnRequest, ChatMessage

        ws = tmp_path / "agents" / "alice" / "workspace"
        (tmp_path / "agents" / "alice" / "memories").mkdir(parents=True)
        ws.mkdir(parents=True)
        monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(tmp_path / "agents"))
        monkeypatch.setenv("TOOL_EGRESS_PROXY_SECRET", secret)

        captured: dict[str, list[str]] = {}

        async def _fake_exec(*cmd, **kwargs):
            captured["cmd"] = list(cmd)
            proc = MagicMock()
            proc.returncode = 0

            async def _comm(input=None):
                return json.dumps({"run_id": "r-f6", "status": "completed", "output_text": "ok"}).encode(), b""

            proc.communicate = _comm
            return proc

        dc = EphemeralDockerRunnerClient(image="brainsos-runner-hermes:latest")
        req = AgentTurnRequest(
            run_id="r-f6",
            agent_id="alice",
            model="gpt-4o",
            system_prompt="s",
            conversation=[ChatMessage(role="user", content="hi")],
            workspace_dir=str(ws),
        )
        with patch("brainsos_runner.clients.docker.asyncio.create_subprocess_exec", side_effect=_fake_exec):
            res = asyncio.run(dc.execute_turn(req))
        assert res.status == "completed"
        joined = " ".join(captured["cmd"])
        assert "v2." in joined
        assert secret not in joined

    # --- F7: Fail-closed GitHub repos, DNS OSError & server_connected (#406 HIGH-2, INFO-2) ---
    def test_f7_egress_addon_fail_closed_repos_dns_and_server_connected(self, egress_addon_factory, monkeypatch):
        _, create_addon, make_flow = egress_addon_factory
        monkeypatch.delenv("GITHUB_ALLOWED_REPOS", raising=False)
        monkeypatch.delenv("TOOL_EGRESS_PROXY_TOKENS", raising=False)

        addon = create_addon()
        flow_unset = make_flow("api.github.com", sni="api.github.com", path="/repos/org/repo/issues")
        addon.request(flow_unset)
        assert flow_unset.response is not None and flow_unset.response.status_code == 403

        with patch("socket.getaddrinfo", side_effect=OSError("DNS failure")):
            flow_dns = make_flow("api.tavily.com", sni="api.tavily.com")
            addon.request(flow_dns)
            assert flow_dns.response is not None and flow_dns.response.status_code == 403

        assert hasattr(addon, "server_connected"), "OpenBaoEgressAddon must implement server_connected"
        killed = []
        data = SimpleNamespace(
            server=SimpleNamespace(
                peername=("169.254.169.254", 443),
                address=("api.tavily.com", 443),
                sni="api.tavily.com",
                error=None,
            ),
            kill=lambda: killed.append(True),
        )
        addon.server_connected(data)
        assert data.server.error or killed

    # --- F8: brainsos-sandbox-net, litellm detachment & sandbox-gateway (#406 HIGH-4) ---
    def test_f8_sandbox_net_litellm_detachment_and_gateway_topology(self):
        base = load_yaml("docker-compose.yml")
        sbox_net = base["networks"].get("brainsos-sandbox-net")
        assert sbox_net and sbox_net.get("internal") is True

        ctrl = load_yaml("docker/compose/compose.control.yml")
        litellm_nets = set((ctrl["services"]["litellm"].get("networks") or {}).keys())
        assert litellm_nets == {"brainsos-control-net", "brainsos-ingress-net"}
        assert "brainsos-internal-net" not in litellm_nets and "brainsos-sandbox-net" not in litellm_nets

        merged_services: dict = {}
        for yml in (
            "docker/compose/compose.control.yml",
            "docker/compose/compose.agents.yml",
            "docker/compose/compose.telemetry.yml",
            "docker/compose/compose.ingress.yml",
        ):
            merged_services.update(load_yaml(yml).get("services", {}))
        gw = merged_services.get("sandbox-gateway")
        assert gw is not None, "Missing sandbox-gateway service"
        gw_nets = gw.get("networks") or {}
        assert "brainsos-sandbox-net" in gw_nets
        assert "brainsos-ingress-net" in gw_nets
        assert "brainsos-control-net" not in gw_nets and "brainsos-secrets-net" not in gw_nets
        sbox_cfg = gw_nets["brainsos-sandbox-net"] or {}
        aliases = set(sbox_cfg.get("aliases") or [])
        assert {"litellm", "lens"} <= aliases, f"sandbox-gateway must expose litellm & lens aliases, got {aliases}"

        assert gw.get("read_only") is True
        assert "ALL" in (gw.get("cap_drop") or [])
        assert "no-new-privileges:true" in (gw.get("security_opt") or [])
        gw_env_str = "\n".join(str(x) for x in (gw.get("environment") or []))
        for secret_key in (
            "LITELLM_MASTER_KEY",
            "DATABASE_URL",
            "LANGFUSE_SECRET_KEY",
            "TOOL_EGRESS_PROXY_SECRET",
            "OPENBAO_",
        ):
            assert secret_key not in gw_env_str, f"sandbox-gateway must be zero-secret; found {secret_key}"

        gw_dir = REPO_ROOT / "config" / "sandbox-gateway"
        assert gw_dir.is_dir(), "Missing config/sandbox-gateway configuration directory"
        gw_cfg_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(gw_dir.rglob("*")) if p.is_file())
        for required_path in (
            "/v1/chat/completions",
            "/v1/completions",
            "/v1/responses",
            "/v1/embeddings",
            "/v1/models",
            "/v1/traces",
            "/v1/logs",
        ):
            assert required_path in gw_cfg_text, f"Missing allowlisted path {required_path} in config/sandbox-gateway"
        assert "403" in gw_cfg_text

        from brainsos_runner.clients.docker import EphemeralDockerRunnerClient

        assert EphemeralDockerRunnerClient(image="img").network == "brainsos-sandbox-net"

    # --- F9: mitmweb isolation, CSS 0644, ALB CIDRs & IMDS guard (#406 HIGH-4, INFO-1) ---
    def test_f9_mitmweb_isolation_css_mode_alb_cidrs_and_imds_guard(self, fake_bin_dir, tmp_path):
        agents = load_yaml("docker/compose/compose.agents.yml")
        proxy_svc = agents["services"]["tool-egress-proxy"]
        cmd_str = str(proxy_svc.get("command", ""))
        assert "web_password=" not in cmd_str
        proxy_nets = set((proxy_svc.get("networks") or {}).keys())
        assert "brainsos-sandbox-net" in proxy_nets
        web_host_m = re.search(r"--web-host\s+(\S+)", cmd_str)
        assert web_host_m is not None
        assert "0.0.0.0" not in web_host_m.group(1) and "172.28.8." not in web_host_m.group(1)
        base_compose = load_yaml("docker-compose.yml")
        root_proxy_nets = (base_compose.get("services") or {}).get("tool-egress-proxy", {}).get("networks") or {}
        assert "brainsos-ingress-net" in root_proxy_nets
        assert "0o666" not in read_repo_text("docker/egress/Dockerfile")

        ing = load_yaml("docker/compose/compose.ingress.yml")
        env_line = next(
            x for x in ing["services"]["caddy"]["environment"] if str(x).startswith("AUTH_ALB_TRUSTED_CIDRS=")
        )
        default_cidrs = env_line.split(":-", 1)[1].rstrip("}")
        nets = [ipaddress.ip_network(c) for c in default_cidrs.split()]
        assert not any(ipaddress.ip_address("172.28.0.10") in n for n in nets)
        assert not any(ipaddress.ip_address("172.28.8.10") in n for n in nets)
        assert any(ipaddress.ip_address("172.31.10.5") in n for n in nets)

        for tool, body in {
            "uname": "#!/usr/bin/env bash\necho Linux\n",
            "iptables": "#!/usr/bin/env bash\nexit 1\n",
            "ip6tables": "#!/usr/bin/env bash\nexit 1\n",
            "docker": (
                "#!/usr/bin/env bash\n"
                'if [ "$1" = "network" ] && [ "$2" = "ls" ]; then '
                "printf 'brainsos-internal-net\\nbrainsos-sandbox-net\\n'; exit 0; fi\n"
                'if [ "$1" = "network" ] && [ "$2" = "inspect" ]; then echo "br-${!#}"; exit 0; fi\n'
                "exit 1\n"
            ),
        }.items():
            p = fake_bin_dir / tool
            p.write_text(body, encoding="utf-8")
            p.chmod(0o755)
        env_file = tmp_path / "imds.env"
        env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")
        out = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts/setup/imds-guard.sh"), "--dry-run", "--force"],
            cwd=REPO_ROOT,
            env={**os.environ, "PATH": f"{fake_bin_dir}:{os.environ['PATH']}", "BRAINSOS_ENV_FILE": str(env_file)},
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert out.returncode == 0
        assert "169.254.0.0/16" in out.stdout
        assert "brainsos-sandbox-net" in out.stdout or "br-brainsos-sandbox-net" in out.stdout

    # --- F10: Langfuse, @litellm_ui_referer & @sogo_static edge hardening (#407 HIGH-5, MEDIUM-5) ---
    @pytest.mark.parametrize("caddy_rel", ["config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"])
    def test_f10_caddy_gates_langfuse_litellm_referer_and_drops_sogo_static_token(self, caddy_rel):
        txt = read_repo_text(caddy_rel)
        litellm_ref_blk = extract_caddy_block(txt, "handle @litellm_ui_referer")
        assert _caddy_handler_requires_admin_auth(txt, litellm_ref_blk), (
            f"handle @litellm_ui_referer must enforce authentik_admin_forward_auth in {caddy_rel}"
        )

        for lf_handler in (
            "handle @langfuse_host",
            "handle /project/brainsos*",
            "handle /trace/*",
            "handle /organization/brainsos*",
            "handle /api/trpc/*",
            "handle /api/public/*",
            "handle /api/project/*",
            "handle /api/traces/*",
            "handle /api/dashboard/*",
            "handle /api/chatCompletion*",
            "handle /api/admin/*",
            "handle /api/internal/*",
            "handle /account/settings*",
        ):
            blk = extract_caddy_block(txt, lf_handler)
            assert _caddy_handler_requires_admin_auth(txt, blk), (
                f"{lf_handler} must enforce authentik_admin_forward_auth in {caddy_rel}"
            )

        for blocked in ("/auth/sign-up*", "/auth/reset-password*"):
            blk = extract_caddy_block(txt, f"handle {blocked}")
            assert "403" in blk, f"{blocked} must respond 403 in {caddy_rel}"

        for sogo_blk in ("handle @mail_static", "handle @sogo_static"):
            blk = extract_caddy_block(txt, sogo_blk)
            assert "X-Caddy-Ingress-Token" not in blk, f"{sogo_blk} must not inject X-Caddy-Ingress-Token"

        nginx_conf = read_repo_text("docker/sogo/nginx.conf")
        assert "WebServerResources" in nginx_conf

    # --- F11: Drop ~/.aws mount, remove static fallbacks & generate secrets (#407 MEDIUM-1/2, INFO-3) ---
    def test_f11_no_aws_mount_no_static_secret_fallbacks_and_clickhouse_mail_secrets(self, isolated_repo):
        ing = load_yaml("docker/compose/compose.ingress.yml")
        vols = "\n".join(str(v) for v in ing["services"]["caddy"]["volumes"])
        assert ".aws" not in vols

        forbidden_literals = (
            "brainsos_tool_egress_secret",
            "brainsos_operator_secret",
            "sk-brainsos-master-key",
            "brainsos_litellm_secret_change_me",
            "brainsos_langfuse_secret_change_me",
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "myredissecret",
            "miniosecret",
            "sogo_secret_pass",
            "authentik_db_secret",
            "authentik_redis_secret_change_me",
            "brainsos_authentik_secret_change_me",
            "sk-brainsos-operator-virtual-key",
        )
        for rel in (
            "config/caddy/Caddyfile",
            "config/caddy/Caddyfile.appliance",
            "docker/compose/compose.ingress.yml",
            "docker/compose/compose.control.yml",
            "docker/compose/compose.telemetry.yml",
            "docker/compose/compose.apps.yml",
            "docker/langfuse/docker-compose.yml",
            "docker/editor/entrypoint.sh",
        ):
            content = read_repo_text(rel)
            for lit in forbidden_literals:
                assert lit not in content, f"Static secret fallback '{lit}' found in {rel}"

        gen = isolated_repo / "scripts" / "control" / "generate-env.sh"
        gen.write_text(read_repo_text("scripts/control/generate-env.sh"), encoding="utf-8")
        gen.chmod(0o755)
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").write_text(
            read_repo_text("scripts/control/env-upsert.sh"), encoding="utf-8"
        )
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").chmod(0o755)
        (isolated_repo / ".env.example").write_text(read_repo_text(".env.example"), encoding="utf-8")
        (isolated_repo / ".env").unlink()

        r = subprocess.run(
            ["bash", str(gen), "--non-interactive", "--no-rebuild"],
            cwd=isolated_repo,
            env=_isolated_script_env(isolated_repo),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert r.returncode == 0, r.stderr
        vals = _parse_env_lines((isolated_repo / ".env").read_text(encoding="utf-8"))
        assert vals.get("CLICKHOUSE_PASSWORD")
        mail_pws = [
            vals.get(k)
            for k in (
                "TERRASTELLA_MAIL_PASSWORD",
                "BAWTFORD_MAIL_PASSWORD",
                "MARVIN_MAIL_PASSWORD",
                "PING_MAIL_PASSWORD",
                "CLAUDE_MAIL_PASSWORD",
                "GPT_MAIL_PASSWORD",
            )
        ]
        assert all(mail_pws) and len(set(mail_pws)) == len(mail_pws)
        assert vals.get("BRAINSOS_ADMIN_PASSWORD") not in mail_pws

    # --- F12: Parameterized provisioning & Editor strict SSL (#407 MEDIUM-6) ---
    def test_f12_parameterized_provisioning_and_editor_strict_ssl(self):
        sogo_ep = read_repo_text("docker/sogo/entrypoint.sh")
        assert "-v " in sogo_ep
        assert "sogo_secret_pass|" not in sogo_ep

        sso_sh = read_repo_text("scripts/setup/setup-litellm-sso.sh")
        assert "json.dumps" in sso_sh

        git_sh = read_repo_text("scripts/setup/setup-git.sh")
        assert "0600" in git_sh or "600" in git_sh

        settings = json.loads(read_repo_text("config/editor/settings.json"))
        assert settings.get("http.proxyStrictSSL") is True
        assert '"http.proxyStrictSSL"] = False' not in read_repo_text("docker/editor/entrypoint.sh")

    # --- F13: Fleet EBS encryption & SST IAM/S3 hardening (#408 MEDIUM-3/4) ---
    def test_f13_launch_fleet_default_ebs_encryption_and_sst_hardening(self, fake_bin_dir, tmp_path):
        calls_log = tmp_path / "aws_calls.log"
        mock_aws = fake_bin_dir / "aws"
        mock_aws.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{calls_log}"\n'
            'if [[ "$*" == *"configure get region"* ]]; then echo "us-east-1"; exit 0; fi\n'
            'if [[ "$*" == *"sts get-caller-identity"* ]]; then '
            'echo \'{"Account":"123456789012","Arn":"arn:aws:iam::123456789012:user/test"}\'; exit 0; fi\n'
            'if [[ "$*" == *"describe-images"* ]]; then echo "ami-0123456789abcdef0"; exit 0; fi\n'
            'if [[ "$*" == *"get-instance-profile"* ]]; then echo "instanceRoleBedrock"; exit 0; fi\n'
            'if [[ "$*" == *"describe-vpcs"* ]]; then echo "vpc-01234567"; exit 0; fi\n'
            'if [[ "$*" == *"describe-security-groups"* ]]; then echo "sg-01234567"; exit 0; fi\n'
            'if [[ "$*" == *"list-hosted-zones-by-name"* ]]; then echo "/hostedzone/Z123456"; exit 0; fi\n'
            'if [[ "$*" == *"run-instances"* ]]; then echo "i-0000000000000001"; exit 0; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        mock_aws.chmod(0o755)
        res = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts/control/launch-fleet.sh"),
                "--ami",
                "ami-0123456789abcdef0",
                "--participants",
                "alice",
                "--base-domain",
                "demo.brainsos.ai",
                "--zone-id",
                "Z123456",
                "--no-ensure-iam-ddns",
                "--roster-out",
                str(tmp_path / "roster"),
                "--apply",
            ],
            cwd=tmp_path,
            env={**os.environ, "PATH": f"{fake_bin_dir}:{os.environ['PATH']}"},
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, res.stderr + res.stdout
        assert "Encrypted=true" in calls_log.read_text(encoding="utf-8")

        iam_ts = read_repo_text("infra/src/components/iam.ts")
        assert "$util.secret(" in iam_ts
        s3_ts = read_repo_text("infra/src/components/s3.ts")
        assert "BucketPublicAccessBlock" in s3_ts and s3_ts.count("blockPublicAcls: true") >= 2

    # --- F14: Supply-chain pinning, AMI SSH scrub, safe.directory & Dovecot (#408 LOW-1/2/4/5) ---
    def test_f14_supply_chain_pinning_ami_ssh_scrub_safe_directory_and_dovecot(self):
        caddy_df = read_repo_text("docker/caddy/Dockerfile")
        assert re.search(r"github\.com/caddy-dns/route53@v[0-9]+\.[0-9]+\.[0-9]+", caddy_df)
        from_lines = [ln.strip() for ln in caddy_df.splitlines() if ln.strip().upper().startswith("FROM ")]
        assert len(from_lines) >= 2
        for fl in from_lines:
            assert re.search(r"@sha256:[0-9a-f]{64}", fl), f"Caddy FROM must be @sha256:-pinned: {fl}"
            if "caddy:" in fl:
                assert re.search(r"caddy:(?:2\.11\.4|2\.11\.9)\b", fl), (
                    f"Caddy FROM version tag must be pinned to 2.11.4 or 2.11.9: {fl}"
                )

        for df in ("docker/hermes/Dockerfile", "docker/runners/base/Dockerfile"):
            txt = read_repo_text(df)
            assert "safe.directory '*'" not in txt and 'safe.directory "*"' not in txt
            assert "/workspace" in txt and "/data" in txt and "/opt/data" in txt
            assert ">=" not in txt, f"{df} must not contain unpinned >= constraints"
            for fl in [ln.strip() for ln in txt.splitlines() if ln.strip().upper().startswith("FROM ")]:
                assert re.search(r"@sha256:[0-9a-f]{64}", fl), f"{df} FROM must be @sha256:-pinned: {fl}"

        assert re.search(r'"?langfuse==[0-9]+\.[0-9]+\.[0-9]+"?', read_repo_text("docker/hermes/Dockerfile"))
        assert re.search(r'"?uvicorn==[0-9]+\.[0-9]+\.[0-9]+"?', read_repo_text("docker/runners/base/Dockerfile"))

        child_runner_pins = {
            "docker/runners/claude-sdk/Dockerfile": ("anthropic==", "boto3==", "mcp==", "httpx=="),
            "docker/runners/openai-sdk/Dockerfile": ("openai==", "mcp==", "httpx=="),
            "docker/runners/hermes/Dockerfile": ("openai==", "httpx==", "pyyaml=="),
        }
        for df, expected_pins in child_runner_pins.items():
            txt = read_repo_text(df)
            assert "safe.directory '*'" not in txt and 'safe.directory "*"' not in txt
            from_lines = [ln.strip() for ln in txt.splitlines() if ln.strip().upper().startswith("FROM ")]
            assert from_lines == ["FROM brainsos-runner-base:latest"], (
                f"{df} must inherit brainsos-runner-base:latest: {from_lines}"
            )
            assert ">=" not in txt, f"{df} must not contain unpinned >= constraints"
            for pin in expected_pins:
                assert re.search(rf"{re.escape(pin)}[0-9]+\.[0-9]+\.[0-9]+", txt), f"{df} missing exact pin {pin}"

        for df in [
            *sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "docker" / "mail").glob("Dockerfile*")),
            "docker/sogo/Dockerfile",
        ]:
            txt = read_repo_text(df)
            for fl in [ln.strip() for ln in txt.splitlines() if ln.strip().upper().startswith("FROM ")]:
                assert re.search(r"@sha256:[0-9a-f]{64}", fl), f"{df} FROM must be @sha256:-pinned: {fl}"

        prov = read_repo_text("packages/brainsOS-appliance/packer/provision.sh")
        assert "/home/admin/.ssh/authorized_keys" in prov and "authorized_keys2" in prov

        dovecot = read_repo_text("docker/mail/dovecot/dovecot.conf")
        dovecot_active = "\n".join(
            ln for ln in dovecot.splitlines() if ln.strip() and not ln.strip().startswith("#")
        )
        assert re.search(r"^\s*mail_debug\s*=\s*no\b", dovecot_active, re.MULTILINE)
        assert re.search(r"^\s*disable_plaintext_auth\s*=\s*yes\b", dovecot_active, re.MULTILINE)
        assert "172.16.0.0/12" not in dovecot_active and "0.0.0.0/0" not in dovecot_active

    # --- LOW-3 Deferral Guard (#403) ---
    def test_low3_viewport_frame_remains_deferred_and_untouched(self):
        vf = read_repo_text("packages/brainsOS-portal/src/components/ViewportFrame.tsx")
        assert 'sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"' in vf


# ==============================================================================
# TIER 2: Boundary & Corner Cases
# ==============================================================================


@pytest.mark.tier2
class TestTier2RC3Boundaries:
    def test_t2_01_firstboot_non_ec2_fallback_entropy_and_uniqueness(self, tmp_path):
        tokens: list[str] = []
        for idx in range(2):
            root = _prepare_firstboot_tree(tmp_path, f"fb_rand_{idx}")
            env = _isolated_script_env(
                root,
                {
                    "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
                    "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
                    "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
                },
            )
            proc = subprocess.run(
                ["bash", str(root / "packages/brainsOS-appliance/scripts/firstboot.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
            vals = _parse_env_lines((root / ".env").read_text(encoding="utf-8"))
            iid = vals.get("BRAINSOS_INSTANCE_ID", "")
            assert iid and not iid.startswith("i-appliance-")
            assert len(iid) >= 24, f"Fallback instance token too short for >=128-bit entropy: {iid!r}"
            assert stat.S_IMODE((root / ".env").stat().st_mode) == 0o600
            tokens.append(iid)
        assert tokens[0] != tokens[1], "Non-EC2 fallback token must be unique per appliance"

    def test_t2_02_dismiss_only_permanently_disables_instance_id_bootstrap(
        self, isolated_repo, system_api_client_factory, monkeypatch
    ):
        monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0dismissonce123456")
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=test\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=false\n"
                "BRAINSOS_INSTANCE_ID=i-0dismissonce123456\n"
            ),
            wizard_completed=False,
        )
        hdrs = {**bundle["internal_headers"], "X-CSRF-Token": bundle["csrf"], "Origin": "http://localhost"}
        dis = bundle["client"].post(
            "/api/v1/system/setup",
            json={"bootstrap_token": "i-0dismissonce123456", "dismiss_only": True},
            headers=hdrs,
        )
        assert dis.status_code == 200 and dis.json()["firstboot_wizard_completed"] is True
        retry = bundle["client"].post(
            "/api/v1/system/setup",
            json={"bootstrap_token": "i-0dismissonce123456", "dry_run": True},
            headers=hdrs,
        )
        assert retry.status_code == 403

    def test_t2_03_egress_github_wildcard_vs_empty_and_peername_matrix(self, egress_addon_factory, monkeypatch):
        _, create_addon, make_flow = egress_addon_factory
        addon = create_addon()
        monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "")
        f_empty = make_flow("api.github.com", sni="api.github.com", path="/repos/org/any/issues")
        addon.request(f_empty)
        assert f_empty.response.status_code == 403

        monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "*")
        f_wild = make_flow("api.github.com", sni="api.github.com", path="/repos/org/any/issues")
        addon.request(f_wild)
        assert f_wild.response is None and "Bearer " in f_wild.request.headers.get("Authorization", "")

        f_trav = make_flow("api.github.com", sni="api.github.com", path="/repos/org/ok/../../org/evil")
        monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "org/ok")
        addon.request(f_trav)
        assert f_trav.response is not None and f_trav.response.status_code == 403

        for bad_ip in ("127.0.0.1", "169.254.169.254", "169.254.170.2", "10.0.0.1", "172.28.0.10", "fd00:ec2::254"):
            killed = []
            d = SimpleNamespace(
                server=SimpleNamespace(
                    peername=(bad_ip, 443),
                    address=("api.github.com", 443),
                    sni="api.github.com",
                    error=None,
                ),
                kill=lambda: killed.append(bad_ip),
            )
            addon.server_connected(d)
            assert d.server.error or killed, f"Failed to block post-connect peer IP {bad_ip}"

        ok_killed = []
        d_ok = SimpleNamespace(
            server=SimpleNamespace(
                peername=("93.184.216.34", 443),
                address=("api.tavily.com", 443),
                sni="api.tavily.com",
                error=None,
            ),
            kill=lambda: ok_killed.append(True),
        )
        addon.server_connected(d_ok)
        assert not d_ok.server.error and not ok_killed

    def test_t2_04_launch_fleet_no_encrypt_vs_hibernation_capable(self, fake_bin_dir, tmp_path):
        calls_log = tmp_path / "aws_calls_t2.log"
        mock_aws = fake_bin_dir / "aws"
        mock_aws.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{calls_log}"\n'
            'if [[ "$*" == *"configure get region"* ]]; then echo "us-east-1"; exit 0; fi\n'
            'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo \'{"Account":"123456789012"}\'; exit 0; fi\n'
            'if [[ "$*" == *"describe-images"* ]]; then echo "ami-0123456789abcdef0"; exit 0; fi\n'
            'if [[ "$*" == *"get-instance-profile"* ]]; then echo "instanceRoleBedrock"; exit 0; fi\n'
            'if [[ "$*" == *"describe-vpcs"* ]]; then echo "vpc-01"; exit 0; fi\n'
            'if [[ "$*" == *"describe-security-groups"* ]]; then echo "sg-01"; exit 0; fi\n'
            'if [[ "$*" == *"run-instances"* ]]; then echo "i-0001"; exit 0; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        mock_aws.chmod(0o755)
        base_args = [
            "bash",
            str(REPO_ROOT / "scripts/control/launch-fleet.sh"),
            "--ami",
            "ami-0123456789abcdef0",
            "--participants",
            "bob",
            "--base-domain",
            "demo.brainsos.ai",
            "--zone-id",
            "Z123",
            "--no-ensure-iam-ddns",
            "--roster-out",
            str(tmp_path / "roster"),
            "--apply",
        ]
        env = {**os.environ, "PATH": f"{fake_bin_dir}:{os.environ['PATH']}"}
        r_noenc = subprocess.run([*base_args, "--no-encrypt"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
        assert r_noenc.returncode == 0, r_noenc.stderr + r_noenc.stdout
        assert "Encrypted=false" in calls_log.read_text(encoding="utf-8")

        calls_log.write_text("", encoding="utf-8")
        r_hib = subprocess.run(
            [*base_args, "--hibernation-capable", "--no-encrypt"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert r_hib.returncode == 0, r_hib.stderr + r_hib.stdout
        assert "Encrypted=true" in calls_log.read_text(encoding="utf-8")

    def test_t2_05_provision_scan_only_rejects_admin_authorized_keys2(self, tmp_path):
        prov_txt = read_repo_text("packages/brainsOS-appliance/packer/provision.sh")
        assert "/home/admin/.ssh/authorized_keys" in prov_txt
        assert "authorized_keys2" in prov_txt

        app_dir = tmp_path / "app"
        (app_dir / "data" / "settings").mkdir(parents=True)
        (app_dir / ".env.example").write_text("FOO=\n", encoding="utf-8")
        fake_home_root = tmp_path / "home_root"
        (fake_home_root / "root").mkdir(parents=True)
        (fake_home_root / "home" / "admin" / ".ssh").mkdir(parents=True)
        (fake_home_root / "home" / "admin" / ".ssh" / "authorized_keys2").write_text(
            "ssh-ed25519 AAAA test\n", encoding="utf-8"
        )
        assert "BRAINSOS_SCAN_HOME_ROOT" in prov_txt
        proc = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "packages/brainsOS-appliance/packer/provision.sh"),
                "--scan-only",
                "--app-dir",
                str(app_dir),
            ],
            env={**os.environ, "BRAINSOS_SCAN_HOME_ROOT": str(fake_home_root)},
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode != 0
        assert "authorized_keys2" in proc.stdout + proc.stderr

    def test_t2_06_sogo_entrypoint_avoids_sed_delimiter_corruption(self, tmp_path):
        sogo_ep = read_repo_text("docker/sogo/entrypoint.sh")
        sed_invocations = [
            m.group(0) for m in re.finditer(r"(?m)^[^#\n]*\bsed\b[^\n]*(?:\\\n[^\n]*)*", sogo_ep)
        ]
        assert sed_invocations, "Expected benign JS sed patches in docker/sogo/entrypoint.sh"
        for inv in sed_invocations:
            assert not any(
                tok in inv for tok in ("sogo_secret_pass", "DB_PASS", "MAIL_DOMAIN", "sogo.conf", " -e ")
            ), f"Active sed substitution in docker/sogo/entrypoint.sh: {inv}"
        assert "python3" in sogo_ep and "-v " in sogo_ep

        py_match = re.search(r"python3\s+-\s+<<\s*'PYEOF'\n(.*?)\nPYEOF", sogo_ep, re.DOTALL)
        assert py_match, "Expected Python sogo.conf renderer block in docker/sogo/entrypoint.sh"
        out_conf = tmp_path / "sogo.conf"
        special_pass = "p|a/s&s'w\\o%rd"
        proc = subprocess.run(
            [sys.executable, "-c", py_match.group(1)],
            env={
                **os.environ,
                "SOGO_CONF_TEMPLATE": str(REPO_ROOT / "docker/sogo/sogo.conf"),
                "SOGO_CONF_OUT": str(out_conf),
                "SOGO_RENDER_HOST": "sogo-db",
                "SOGO_RENDER_PORT": "5432",
                "SOGO_RENDER_USER": "sogo&user",
                "SOGO_RENDER_PASS": special_pass,
                "SOGO_RENDER_NAME": "sogo/db",
                "SOGO_RENDER_DOMAIN": "mail.example.test",
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        rendered = out_conf.read_text(encoding="utf-8")
        assert "__SOGO_" not in rendered
        assert f"postgresql://sogo%26user:{urllib.parse.quote(special_pass, safe='')}@sogo-db:5432/sogo%2Fdb/" in rendered
        assert 'SOGoMailDomain = "mail.example.test";' in rendered


# ==============================================================================
# TIER 3: Cross-Feature Combinatorial Interactions
# ==============================================================================


@pytest.mark.tier3
class TestTier3RC3Interactions:
    def test_t3_01_ephemeral_runner_v2_token_integrates_with_egress_addon_and_sandbox_net(
        self, tmp_path, egress_addon_factory, monkeypatch
    ):
        from brainsos_runner.clients.docker import EphemeralDockerRunnerClient
        from brainsos_runner.models import AgentTurnRequest, ChatMessage

        ws = tmp_path / "agents" / "alice" / "workspace"
        (tmp_path / "agents" / "alice" / "memories").mkdir(parents=True)
        ws.mkdir(parents=True)
        secret = "a" * 64
        monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(tmp_path / "agents"))
        monkeypatch.setenv("TOOL_EGRESS_PROXY_SECRET", secret)

        captured: dict[str, list[str]] = {}

        async def _fake_exec(*cmd, **kwargs):
            captured["cmd"] = list(cmd)
            proc = MagicMock()
            proc.returncode = 0

            async def _comm(input=None):
                return json.dumps({"run_id": "r-t3", "status": "completed", "output_text": "ok"}).encode(), b""

            proc.communicate = _comm
            return proc

        dc = EphemeralDockerRunnerClient(image="img")
        req = AgentTurnRequest(
            run_id="r-t3",
            agent_id="alice",
            model="gpt-4o",
            system_prompt="s",
            conversation=[ChatMessage(role="user", content="hi")],
            workspace_dir=str(ws),
        )
        with patch("brainsos_runner.clients.docker.asyncio.create_subprocess_exec", side_effect=_fake_exec):
            res = asyncio.run(dc.execute_turn(req))
        assert res.status == "completed"
        assert "--network" in captured["cmd"] and "brainsos-sandbox-net" in captured["cmd"]

        m = re.search(r"(v2\.[A-Za-z0-9_-]+\.[0-9a-f]{64})", " ".join(captured["cmd"]))
        assert m, "Expected v2. HMAC token in ephemeral runner command"
        _, create_addon, make_flow = egress_addon_factory
        addon = create_addon()
        flow_ok = make_flow(
            "api.tavily.com",
            sni="api.tavily.com",
            headers={"Proxy-Authorization": f"Bearer {m.group(1)}"},
        )
        addon.request(flow_ok)
        assert flow_ok.response is None

    def test_t3_02_generate_env_satisfies_compose_appliance_without_static_fallbacks(self, isolated_repo):
        gen = isolated_repo / "scripts" / "control" / "generate-env.sh"
        gen.write_text(read_repo_text("scripts/control/generate-env.sh"), encoding="utf-8")
        gen.chmod(0o755)
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").write_text(
            read_repo_text("scripts/control/env-upsert.sh"), encoding="utf-8"
        )
        (isolated_repo / "scripts" / "control" / "env-upsert.sh").chmod(0o755)
        (isolated_repo / ".env.example").write_text(read_repo_text(".env.example"), encoding="utf-8")
        (isolated_repo / ".env").unlink()
        gen_res = subprocess.run(
            ["bash", str(gen), "--non-interactive", "--no-rebuild"],
            cwd=isolated_repo,
            env=_isolated_script_env(isolated_repo),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert gen_res.returncode == 0, gen_res.stderr
        if shutil.which("docker"):
            cfg = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(isolated_repo / ".env"),
                    "-f",
                    str(REPO_ROOT / "docker-compose.yml"),
                    "-f",
                    str(REPO_ROOT / "docker/compose/compose.appliance.yml"),
                    "config",
                    "-q",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert cfg.returncode == 0, cfg.stderr


# ==============================================================================
# TIER 4: End-to-End Scenarios & Local Docker Runtime Verification
# ==============================================================================


@pytest.mark.tier4
class TestTier4RC3Scenarios:
    def test_t4_s01_zero_ssh_onboarding_cookie_wizard_completion_and_postwizard_rbac(
        self, isolated_repo, system_api_client_factory, tmp_path, monkeypatch
    ):
        fb_root = _prepare_firstboot_tree(tmp_path, "fb_s01")
        env = _isolated_script_env(
            fb_root,
            {
                "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
                "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
                "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
            },
        )
        fb_proc = subprocess.run(
            ["bash", str(fb_root / "packages/brainsOS-appliance/scripts/firstboot.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert fb_proc.returncode == 0, fb_proc.stdout + fb_proc.stderr
        fb_vals = _parse_env_lines((fb_root / ".env").read_text(encoding="utf-8"))
        assert fb_vals["AUTHENTIK_BOOTSTRAP_PASSWORD"] != fb_vals.get("BRAINSOS_INSTANCE_ID", "")

        monkeypatch.setenv("BRAINSOS_TEST_INSTANCE_ID", "i-0scenario01rc30001")
        sd = isolated_repo / "scripts" / "control" / "set-domain.sh"
        sd.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
        sd.chmod(0o755)
        bundle = system_api_client_factory(
            isolated_repo,
            env_text=(
                "BRAINSOS_STAGE=production\n"
                "SYSTEM_API_TOKEN=e2e-internal-token-12345\n"
                "BRAINSOS_WIZARD_COMPLETED=false\n"
                "BRAINSOS_INSTANCE_ID=i-0scenario01rc30001\n"
            ),
            wizard_completed=False,
        )
        monkeypatch.setenv("BRAINSOS_STAGE", "production")
        ident_pre = bundle["client"].get("/api/v1/system/identity", headers=bundle["internal_headers"]).json()
        assert set(ident_pre.keys()) <= {"firstboot_wizard_completed", "unit_name", "url", "tls_mode"}

        hdrs = {**bundle["internal_headers"], "X-CSRF-Token": bundle["csrf"], "Origin": "http://localhost"}
        setup = bundle["client"].post(
            "/api/v1/system/setup",
            json={
                "bootstrap_token": "i-0scenario01rc30001",
                "local_domain": "alice.brainsos.ai",
                "url": "alice.brainsos.ai",
                "superuser_username": "alice",
                "superuser_password": "StrongPassword!99",
                "tls_mode": "internal",
                "mark_wizard_completed": True,
            },
            headers=hdrs,
        )
        assert setup.status_code == 200, setup.text
        assert any("brainsos_wizard_session=" in c for c in _parse_set_cookies(setup))

        (isolated_repo / ".brainsos-wizard-completed").write_text("2026-11-27T00:00:00Z\n", encoding="utf-8")
        assert (
            bundle["client"]
            .post(
                "/api/v1/system/setup",
                json={"bootstrap_token": "i-0scenario01rc30001", "dry_run": True},
                headers=hdrs,
            )
            .status_code
            == 403
        )
        assert bundle["client"].get("/api/v1/system/me", headers=bundle["viewer_headers"]).status_code == 200
        assert bundle["client"].get("/api/v1/system/status", headers=bundle["viewer_headers"]).status_code == 403
        assert bundle["client"].get("/api/v1/system/jobs/job-post-1", headers=bundle["viewer_headers"]).status_code == 403


@pytest.mark.tier4
@pytest.mark.docker_runtime
class TestRC3DockerRuntime:
    """Local Docker runtime verification (zero AWS/SaaS; skips cleanly if Docker daemon unavailable)."""

    def test_docker_compose_config_and_litellm_network_detachment(self, tmp_path):
        if not _docker_daemon_ready():
            pytest.skip("Docker daemon not available")
        env_file = _build_env_for_compose(tmp_path)
        res = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(REPO_ROOT / "docker-compose.yml"),
                "-f",
                str(REPO_ROOT / "docker/compose/compose.appliance.yml"),
                "config",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert res.returncode == 0, res.stderr
        cfg = yaml.safe_load(res.stdout)
        assert cfg["networks"]["brainsos-sandbox-net"]["internal"] is True
        litellm_nets = set(cfg["services"]["litellm"]["networks"].keys())
        assert litellm_nets == {"brainsos-control-net", "brainsos-ingress-net"}
        assert "brainsos-sandbox-net" not in litellm_nets and "brainsos-internal-net" not in litellm_nets
        assert "sandbox-gateway" in cfg["services"]
        assert "brainsos-sandbox-net" in cfg["services"]["sandbox-gateway"]["networks"]

    def test_caddy_validate_in_local_docker(self, tmp_path):
        if not _docker_daemon_ready():
            pytest.skip("Docker daemon not available")
        caddy_img = "brainsos-caddy:latest"
        if subprocess.run(["docker", "image", "inspect", caddy_img], capture_output=True).returncode != 0:
            pytest.skip(f"Caddy image {caddy_img} not built locally")
        ca_crt = tmp_path / "openbao_ca.crt"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                "/dev/null",
                "-out",
                str(ca_crt),
                "-days",
                "1",
                "-subj",
                "/CN=brainsos-openbao-validate",
            ],
            check=True,
            capture_output=True,
        )
        for caddy_rel in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
            caddy_filename = Path(caddy_rel).name
            res = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{REPO_ROOT / 'config' / 'caddy'}:/etc/caddy:ro",
                    "-v",
                    f"{ca_crt}:/etc/ssl/openbao/ca.crt:ro",
                    "-e",
                    "BRAINSOS_DOMAIN=unit.brainsos.ai",
                    "-e",
                    "BRAINSOS_LOCAL_DOMAIN=unit.local.brainsos.ai",
                    "-e",
                    "BRAINSOS_PORTAL_STATIC_DIR=/srv/portal",
                    "-e",
                    "BRAINSOS_WIZARD_COMPLETED=true",
                    "-e",
                    "AUTH_ALB_TRUSTED_CIDRS=172.31.0.0/16",
                    "-e",
                    "CADDY_INGRESS_TOKEN=ci-token",
                    "-e",
                    "HERMES_DASHBOARD_PROXY_TOKEN=ci-hermes",
                    "-e",
                    "RUNNER_AUTH_TOKEN=ci-runner",
                    "-e",
                    "TOOL_EGRESS_WEB_PASSWORD=ci-egress",
                    "--entrypoint",
                    "caddy",
                    caddy_img,
                    "validate",
                    "--config",
                    f"/etc/caddy/{caddy_filename}",
                    "--adapter",
                    "caddyfile",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert res.returncode == 0, f"caddy validate failed on {caddy_rel}: {res.stderr}\n{res.stdout}"

    def test_sandbox_gateway_l7_allowlist_and_403_in_local_docker(self, tmp_path):
        if not _docker_daemon_ready():
            pytest.skip("Docker daemon not available")
        gw_dir = REPO_ROOT / "config" / "sandbox-gateway"
        if not gw_dir.is_dir():
            pytest.skip("config/sandbox-gateway directory not present")
        py_img = _pick_python_docker_image()
        if not py_img:
            pytest.skip("Neither python:3.12-slim-bookworm nor brainsos-runner-base:latest is present locally")

        env_file = _build_env_for_compose(tmp_path)
        cfg_res = subprocess.run(
            ["docker", "compose", "--env-file", str(env_file), "-f", str(REPO_ROOT / "docker-compose.yml"), "config"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert cfg_res.returncode == 0, cfg_res.stderr
        cfg = yaml.safe_load(cfg_res.stdout)
        gw_svc = cfg["services"]["sandbox-gateway"]
        gw_img = gw_svc["image"]
        if subprocess.run(["docker", "image", "inspect", gw_img], capture_output=True).returncode != 0:
            pytest.skip(f"Gateway image {gw_img} not built/pulled locally")

        net_name = f"rc3-gw-test-{os.getpid()}"
        up_name = f"rc3-up-{os.getpid()}"
        gw_name = f"rc3-gw-{os.getpid()}"
        try:
            subprocess.run(["docker", "network", "create", net_name], check=True, capture_output=True)
            up_script = (
                "import http.server, threading, time\n"
                "class H(http.server.BaseHTTPRequestHandler):\n"
                "  def _ok(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
                "  do_GET=_ok; do_POST=_ok\n"
                "  def log_message(self, *a): pass\n"
                "for p in (4000, 4318):\n"
                "  threading.Thread(target=http.server.HTTPServer(('0.0.0.0', p), H).serve_forever, daemon=True).start()\n"
                "time.sleep(60)\n"
            )
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    up_name,
                    "--network",
                    net_name,
                    "--network-alias",
                    "litellm",
                    "--network-alias",
                    "lens",
                    py_img,
                    "python3",
                    "-c",
                    up_script,
                ],
                check=True,
                capture_output=True,
            )

            gw_args: list[str] = ["docker", "run", "-d", "--rm", "--name", gw_name, "--network", net_name]
            for vol in gw_svc.get("volumes") or []:
                if isinstance(vol, dict):
                    gw_args.extend(["-v", f"{vol['source']}:{vol['target']}:ro"])
                elif isinstance(vol, str):
                    gw_args.extend(["-v", vol])
            gw_env = gw_svc.get("environment") or {}
            if isinstance(gw_env, dict):
                for k, v in gw_env.items():
                    if v is not None:
                        gw_args.extend(["-e", f"{k}={v}"])
            elif isinstance(gw_env, list):
                for item in gw_env:
                    gw_args.extend(["-e", str(item)])
            ep = gw_svc.get("entrypoint")
            if isinstance(ep, list) and ep:
                gw_args.extend(["--entrypoint", str(ep[0])])
            elif isinstance(ep, str) and ep:
                gw_args.extend(["--entrypoint", ep])
            gw_args.append(gw_img)
            cmd = gw_svc.get("command")
            if isinstance(cmd, list):
                gw_args.extend(str(c) for c in cmd)
            elif isinstance(cmd, str) and cmd:
                gw_args.extend(cmd.split())

            subprocess.run(gw_args, check=True, capture_output=True)
            time.sleep(1.5)

            probe_py = (
                "import urllib.request, urllib.error, json\n"
                "def call(host, port, method, path):\n"
                "  req = urllib.request.Request(f'http://{host}:{port}{path}', method=method, data=(b'{}' if method=='POST' else None))\n"
                "  try:\n"
                "    with urllib.request.urlopen(req, timeout=3) as r: return r.status\n"
                "  except urllib.error.HTTPError as e: return e.code\n"
                "out = {\n"
                "  'models': call(GW, 4000, 'GET', '/v1/models'),\n"
                "  'chat': call(GW, 4000, 'POST', '/v1/chat/completions'),\n"
                "  'completions': call(GW, 4000, 'POST', '/v1/completions'),\n"
                "  'responses': call(GW, 4000, 'POST', '/v1/responses'),\n"
                "  'embeddings': call(GW, 4000, 'POST', '/v1/embeddings'),\n"
                "  'key_gen': call(GW, 4000, 'POST', '/key/generate'),\n"
                "  'ui': call(GW, 4000, 'GET', '/ui'),\n"
                "  'user_info': call(GW, 4000, 'GET', '/user/info'),\n"
                "  'model_new': call(GW, 4000, 'POST', '/model/new'),\n"
                "  'config': call(GW, 4000, 'GET', '/config'),\n"
                "  'sso': call(GW, 4000, 'GET', '/sso'),\n"
                "  'traces_post': call(GW, 4318, 'POST', '/v1/traces'),\n"
                "  'logs_post': call(GW, 4318, 'POST', '/v1/logs'),\n"
                "  'traces_get': call(GW, 4318, 'GET', '/api/traces'),\n"
                "}\n"
                "print(json.dumps(out))\n"
            ).replace("GW", repr(gw_name))
            probe = subprocess.run(
                ["docker", "run", "--rm", "--network", net_name, py_img, "python3", "-c", probe_py],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            results = json.loads(probe.stdout.strip().splitlines()[-1])
            for ok_key in ("models", "chat", "completions", "responses", "embeddings", "traces_post", "logs_post"):
                assert results[ok_key] == 200, f"Expected 200 for {ok_key}, got {results}"
            for deny_key in ("key_gen", "ui", "user_info", "model_new", "config", "sso", "traces_get"):
                assert results[deny_key] == 403, f"Expected 403 for {deny_key}, got {results}"
        finally:
            for c in (gw_name, up_name):
                subprocess.run(["docker", "rm", "-f", c], capture_output=True, check=False)
            subprocess.run(["docker", "network", "rm", net_name], capture_output=True, check=False)

    def test_running_litellm_container_network_membership_if_active(self):
        if not _docker_daemon_ready():
            pytest.skip("Docker daemon not available")
        insp = subprocess.run(
            ["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", "brainsos-control-litellm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if insp.returncode != 0:
            pytest.skip("brainsos-control-litellm container is not currently running")
        nets = set(json.loads(insp.stdout.strip()).keys())
        assert nets == {"brainsos-control-net", "brainsos-ingress-net"}
        assert "brainsos-sandbox-net" not in nets and "brainsos-internal-net" not in nets
