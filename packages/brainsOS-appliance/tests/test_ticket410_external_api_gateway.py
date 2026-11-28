"""Tests for Ticket #410: External Virtual-Key AI Gateway (api.{host}) & LiteLLM Admin Route Gating."""

from __future__ import annotations

import http.client
import importlib.util
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from brainsos_terminal.urls import get_service_directory

REPO_ROOT = Path(__file__).resolve().parents[3]


def _extract_brace_block(text: str, header_prefix: str) -> str:
    idx = text.find(header_prefix)
    assert idx != -1, f"Missing block {header_prefix!r}"
    brace_start = text.find("{", idx)
    assert brace_start != -1, f"Missing '{{' for {header_prefix!r}"
    depth = 0
    for pos in range(brace_start, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[idx : pos + 1]
    raise AssertionError(f"Unclosed block {header_prefix!r}")


def _load_ddns_module():
    spec = importlib.util.spec_from_file_location(
        "sync_route53_ddns_t410", REPO_ROOT / "scripts" / "control" / "sync-route53-ddns.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_caddyfiles_define_api_subdomain_virtual_key_gateway_and_admin_gating() -> None:
    """Verify both Caddyfiles define (litellm_external_virtual_key_gateway), @api_host, and admin SSO on LiteLLM management routes."""
    app_caddy = (REPO_ROOT / "config/caddy/Caddyfile.appliance").read_text(encoding="utf-8")
    assert "api.{$BRAINSOS_DOMAIN:localhost}" in app_caddy

    for rel in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        gw = _extract_brace_block(txt, "(litellm_external_virtual_key_gateway)")
        assert "request_header -Cookie" in gw
        assert "max_size 10MB" in gw
        assert "/v1/chat/completions" in gw
        assert "/v1/messages" in gw
        assert "/v1/models" in gw
        assert "Master key prohibited on external API" in gw
        assert "Missing or invalid LiteLLM virtual key" in gw
        assert "Endpoint not exposed on external AI gateway" in gw

        assert "@api_host header_regexp Host (?i)^api\\." in txt
        api_blk = _extract_brace_block(txt, "handle @api_host {")
        assert "import litellm_external_virtual_key_gateway" in api_blk

        for admin_guarded in (
            "handle /proxy/ui/* {",
            "handle @litellm_ui {",
            "handle @litellm_api {",
            "handle @litellm_proxy_fallback {",
        ):
            blk = _extract_brace_block(txt, admin_guarded)
            assert "import authentik_admin_forward_auth" in blk, (
                f"{rel} {admin_guarded} must enforce authentik_admin_forward_auth"
            )


def test_generate_env_uses_sk_master_prefix_and_provision_scans_it(tmp_path: Path) -> None:
    """Verify newly generated LITELLM_MASTER_KEY uses sk-master-* and provision.sh scans both prefixes."""
    for sub in ("scripts/control", "config"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / ".env.example", tmp_path / ".env.example")
    gen = tmp_path / "scripts/control/generate-env.sh"
    shutil.copy2(REPO_ROOT / "scripts/control/generate-env.sh", gen)
    gen.chmod(0o755)
    (tmp_path / "config/agents.yaml").write_text("agents: []\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", str(gen), "--non-interactive", "--no-rebuild", "--domain", "unit.brainsos.ai"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    m = re.search(r"^LITELLM_MASTER_KEY=(.+)$", env_text, re.MULTILINE)
    assert m is not None
    assert re.fullmatch(r"sk-master-[0-9a-f]{32}", m.group(1).strip())

    provision_txt = (REPO_ROOT / "packages/brainsOS-appliance/packer/provision.sh").read_text(encoding="utf-8")
    assert "sk-(brainsos|master)-[0-9a-f]{32}" in provision_txt


def test_route53_ddns_syncs_api_subdomain_and_supports_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify sync_route53_record atomically upserts api.<fqdn> + _brainsos-owner.api.<fqdn> and supports opt-out."""
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", "c" * 64)
    mod = _load_ddns_module()

    class _FakeR53:
        def __init__(self) -> None:
            self.batches: list[dict[str, Any]] = []

        def list_resource_record_sets(self, **kwargs: Any) -> dict[str, Any]:
            return {"ResourceRecordSets": []}

        def change_resource_record_sets(self, HostedZoneId: str, ChangeBatch: dict[str, Any]) -> dict[str, Any]:
            self.batches.append(ChangeBatch)
            return {"ChangeInfo": {"Id": "/change/C410"}}

    r53 = _FakeR53()
    res = mod.sync_route53_record(
        route53_client=r53,
        domain="alice.demo.brainsos.ai",
        ip="54.10.20.30",
        zone_id="Z1234567890",
        instance_id="i-0123456789abcdef0",
    )
    assert res["status"] == "updated"
    assert res["api_domain"] == "api.alice.demo.brainsos.ai"
    names = [c["ResourceRecordSet"]["Name"] for c in r53.batches[0]["Changes"]]
    assert names == [
        "alice.demo.brainsos.ai",
        "_brainsos-owner.alice.demo.brainsos.ai",
        "api.alice.demo.brainsos.ai",
        "_brainsos-owner.api.alice.demo.brainsos.ai",
    ]

    r53_no_api = _FakeR53()
    res_no_api = mod.sync_route53_record(
        route53_client=r53_no_api,
        domain="alice.demo.brainsos.ai",
        ip="54.10.20.30",
        zone_id="Z1234567890",
        sync_api_subdomain=False,
    )
    assert "api_domain" not in res_no_api
    assert [c["ResourceRecordSet"]["Name"] for c in r53_no_api.batches[0]["Changes"]] == [
        "alice.demo.brainsos.ai",
        "_brainsos-owner.alice.demo.brainsos.ai",
    ]


def test_terminal_urls_advertises_https_api_subdomain_without_master_key() -> None:
    """Verify get_service_directory advertises https://api.<domain>/v1 and never leaks LITELLM_MASTER_KEY."""
    svcs = get_service_directory(
        {
            "BRAINSOS_DOMAIN": "box.brainsos.ai",
            "LITELLM_MASTER_KEY": "sk-master-supersecret1234567890abcdef",
        }
    )
    gw = next(s for s in svcs if s["name"] == "LiteLLM OpenAI Gateway")
    assert gw["public_url"] == "https://api.box.brainsos.ai/v1"
    for s in svcs:
        assert "sk-master-supersecret1234567890abcdef" not in s["auth"]


def test_live_caddy_external_api_gateway_enforces_virtual_keys_and_blocks_master_and_admin(tmp_path: Path) -> None:
    """Live local Caddy L7 test verifying api.{host} virtual-key-only enforcement, master-key 403, and admin-route 403."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        pytest.skip("docker binary not available")
    inspect = subprocess.run(
        [docker_bin, "image", "inspect", "brainsos-caddy:latest"],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip("brainsos-caddy:latest image not built locally")

    recorded: list[dict[str, Any]] = []

    class _UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            recorded.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"object":"list","data":[{"id":"brainsos-core"}]}')

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length) if length else b""
            recorded.append({"method": "POST", "path": self.path, "headers": dict(self.headers)})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"chatcmpl-ok"}')

        def log_message(self, fmt: str, *args: Any) -> None:
            del fmt, args

    upstream = HTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    upstream_port = upstream.server_address[1]
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s1, socket.socket(
        socket.AF_INET, socket.SOCK_STREAM
    ) as s2:
        s1.bind(("127.0.0.1", 0))
        s2.bind(("127.0.0.1", 0))
        https_port = s1.getsockname()[1]
        http_port = s2.getsockname()[1]

    ca_file = tmp_path / "ca.crt"
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
            str(ca_file),
            "-days",
            "1",
            "-subj",
            "/CN=openbao-test",
        ],
        check=True,
        capture_output=True,
    )

    raw_caddy = (REPO_ROOT / "config/caddy/Caddyfile.appliance").read_text(encoding="utf-8")
    patched_caddy = raw_caddy.replace(
        "{\n\tadmin off\n",
        f"{{\n\tadmin off\n\thttp_port {http_port}\n\thttps_port {https_port}\n",
        1,
    ).replace("\n:80 {\n", f"\n:{http_port} {{\n", 1)
    test_caddy_file = tmp_path / "Caddyfile.test"
    test_caddy_file.write_text(patched_caddy, encoding="utf-8")

    cname = f"brainsos-test-api410-{os.getpid()}"
    master_key = "sk-custom-env-master-999999999999"
    try:
        subprocess.run(
            [
                docker_bin,
                "run",
                "-d",
                "--rm",
                "--name",
                cname,
                "--network",
                "host",
                "-e",
                "BRAINSOS_DOMAIN=test.brainsos.ai",
                "-e",
                "BRAINSOS_TLS_MODE=internal",
                "-e",
                f"LITELLM_UPSTREAM=127.0.0.1:{upstream_port}",
                "-e",
                f"LITELLM_MASTER_KEY={master_key}",
                "-v",
                f"{test_caddy_file}:/etc/caddy/Caddyfile.test:ro",
                "-v",
                f"{ca_file}:/etc/ssl/openbao/ca.crt:ro",
                "--entrypoint",
                "caddy",
                "brainsos-caddy:latest",
                "run",
                "--config",
                "/etc/caddy/Caddyfile.test",
                "--adapter",
                "caddyfile",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        def _req(host: str, method: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            raw_sock = socket.create_connection(("127.0.0.1", https_port), timeout=2.0)
            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
            conn = http.client.HTTPSConnection(host, https_port, context=ctx)
            conn.sock = tls_sock
            try:
                req_headers = {"Host": host, **(headers or {})}
                conn.request(method, path, body=(b"{}" if method == "POST" else None), headers=req_headers)
                resp = conn.getresponse()
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, body
            finally:
                conn.close()

        # Wait for Caddy TLS listener readiness
        ready = False
        for _ in range(30):
            try:
                code, _ = _req("api.test.brainsos.ai", "GET", "/v1/models")
                if code in (200, 401, 403):
                    ready = True
                    break
            except OSError:
                time.sleep(0.2)
        assert ready, "Caddy test listener did not become ready"
        recorded.clear()

        # 1. Missing key -> 401 before upstream
        st, body = _req("api.test.brainsos.ai", "GET", "/v1/models")
        assert st == 401 and "virtual key" in body
        assert len(recorded) == 0

        # 2. Exact LITELLM_MASTER_KEY -> 403 before upstream (both Bearer and x-api-key)
        st, body = _req(
            "api.test.brainsos.ai",
            "POST",
            "/v1/chat/completions",
            {"Authorization": f"Bearer {master_key}"},
        )
        assert st == 403 and "Master key prohibited" in body
        st, _ = _req(
            "api.test.brainsos.ai",
            "POST",
            "/v1/messages",
            {"x-api-key": master_key},
        )
        assert st == 403
        # 3. sk-master-* prefix -> 403 before upstream
        st, _ = _req(
            "api.test.brainsos.ai",
            "GET",
            "/v1/models",
            {"Authorization": "Bearer sk-master-" + ("a" * 32)},
        )
        assert st == 403
        assert len(recorded) == 0

        # 4. Control-plane & OpenBao paths on api.{host} -> 403 even with valid virtual key
        for forbidden_method, forbidden_path in (
            ("GET", "/ui/"),
            ("POST", "/key/generate"),
            ("POST", "/model/new"),
            ("GET", "/config/update"),
            ("GET", "/v1/sys/health"),
        ):
            st, body = _req(
                "api.test.brainsos.ai",
                forbidden_method,
                forbidden_path,
                {"Authorization": "Bearer sk-virt-tenant-1234567890"},
            )
            assert st == 403 and "not exposed" in body
        assert len(recorded) == 0

        # 5. Valid virtual key on OpenAI & Anthropic inference endpoints -> 200, cookies & spoofed headers stripped
        st, _ = _req(
            "api.test.brainsos.ai",
            "POST",
            "/v1/chat/completions",
            {
                "Authorization": "Bearer sk-virt-tenant-1234567890",
                "Cookie": "authentik_session=secret; token=jwt",
                "X-Authentik-Username": "spoofed-admin",
            },
        )
        assert st == 200
        assert len(recorded) == 1
        fwd_hdrs = {k.lower(): v for k, v in recorded[-1]["headers"].items()}
        assert fwd_hdrs.get("authorization") == "Bearer sk-virt-tenant-1234567890"
        assert "cookie" not in fwd_hdrs
        assert "x-authentik-username" not in fwd_hdrs

        st, _ = _req(
            "api.test.brainsos.ai",
            "POST",
            "/v1/messages",
            {"x-api-key": "sk-virt-claude-1234567890"},
        )
        assert st == 200

        st, _ = _req(
            "api.test.brainsos.ai",
            "GET",
            "/v1/models",
            {"Authorization": "Bearer sk-virt-tenant-1234567890"},
        )
        assert st == 200
        assert len(recorded) == 3

        # 6. Single-origin management route (/key/generate) on primary host blocks unauthenticated internet callers
        st_mgmt, _ = _req(
            "test.brainsos.ai",
            "POST",
            "/key/generate",
            {"Authorization": f"Bearer {master_key}"},
        )
        assert st_mgmt in (401, 403, 503)
        assert len(recorded) == 3
    finally:
        subprocess.run([docker_bin, "rm", "-f", cname], capture_output=True, check=False)
        upstream.shutdown()
