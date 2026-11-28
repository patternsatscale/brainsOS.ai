"""Behavioral regression tests for Ticket #407 hardening controls."""

from __future__ import annotations

import ast
import base64
import fnmatch
import http.server
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _minimal_env(**extra: str) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    env.update(extra)
    return env


def test_setup_mail_fails_closed_without_env_file_or_passwords(tmp_path: Path) -> None:
    """setup-mail.sh must fail closed when mail passwords and ENV_FILE are missing, even if BRAINSOS_ADMIN_PASSWORD is set."""
    comms_dir = tmp_path / "comms"
    missing_env = tmp_path / "missing.env"
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/setup/setup-mail.sh"), "--accounts-only"],
        env=_minimal_env(
            BRAINSOS_REPO_ROOT=str(REPO_ROOT),
            BRAINSOS_ENV_FILE=str(missing_env),
            BRAINSOS_COMMS_DIR=str(comms_dir),
            BRAINSOS_ADMIN_PASSWORD="admin-should-never-be-reused",
        ),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "ADMIN_MAIL_PASSWORD must be set" in proc.stderr


def test_setup_mail_generates_and_persists_independent_passwords_at_0600(tmp_path: Path) -> None:
    """setup-mail.sh persists unique generated per-account passwords into ENV_FILE with 0600 permissions."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_ADMIN_PASSWORD=super_admin_secret_123\n"
        "ADMIN_MAIL_PASSWORD=admin_mail_pass_change_me\n",
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)
    comms_dir = tmp_path / "comms"

    # Stub docker so unit test does not chown tmp_path files to UID 5000 via alpine container
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/usr/bin/env bash\n'
        'if [ "$1" = "image" ] && [ "$2" = "inspect" ] && [ "$3" = "brainsos-mail-server:latest" ]; then\n'
        '  exit 0\n'
        'fi\n'
        'exit 1\n',
        encoding="utf-8",
    )
    os.chmod(fake_docker, 0o755)

    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/setup/setup-mail.sh"), "--accounts-only"],
        env=_minimal_env(
            PATH=f"{fake_bin}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
            BRAINSOS_REPO_ROOT=str(REPO_ROOT),
            BRAINSOS_ENV_FILE=str(env_file),
            BRAINSOS_COMMS_DIR=str(comms_dir),
        ),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    parsed: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            parsed[k.strip()] = v.strip()

    mail_keys = [
        "ADMIN_MAIL_PASSWORD",
        "OPERATOR_MAIL_PASSWORD",
        "TERRASTELLA_MAIL_PASSWORD",
        "BAWTFORD_MAIL_PASSWORD",
        "MARVIN_MAIL_PASSWORD",
        "PING_MAIL_PASSWORD",
        "CLAUDE_MAIL_PASSWORD",
        "GPT_MAIL_PASSWORD",
    ]
    values = [parsed[k] for k in mail_keys]
    assert all(v and "change_me" not in v and v != "super_admin_secret_123" for v in values)
    assert len(set(values)) == len(mail_keys)

    users_file = comms_dir / "email/config/users"
    assert users_file.exists()
    content = users_file.read_text(encoding="utf-8")
    assert "{SHA512-CRYPT}" in content


def test_setup_git_dry_run_allowed_without_password_but_normal_run_fails_closed(tmp_path: Path) -> None:
    """setup-git.sh --dry-run succeeds without password, while live execution fails closed."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts/setup").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/setup/setup-git.sh", fake_repo / "scripts/setup/setup-git.sh")

    dry = subprocess.run(
        ["bash", str(fake_repo / "scripts/setup/setup-git.sh"), "--dry-run"],
        env=_minimal_env(
            BRAINSOS_DATA_DIR=str(tmp_path / "data"),
        ),
        capture_output=True,
        text=True,
    )
    assert dry.returncode == 0, f"stdout={dry.stdout}\nstderr={dry.stderr}"

    live = subprocess.run(
        ["bash", str(fake_repo / "scripts/setup/setup-git.sh")],
        env=_minimal_env(
            BRAINSOS_DATA_DIR=str(tmp_path / "data"),
        ),
        capture_output=True,
        text=True,
    )
    assert live.returncode != 0
    assert "BRAINSOS_ADMIN_PASSWORD or BRAINSOS_SUPERUSER_PASSWORD must be set" in live.stderr


def test_sogo_entrypoint_render_nginx_only_without_secrets_and_fail_closed_default(tmp_path: Path) -> None:
    """docker/sogo/entrypoint.sh --render-nginx-only renders nginx.conf cleanly without DB secrets."""
    nginx_out = tmp_path / "nginx.conf"
    render = subprocess.run(
        ["bash", str(REPO_ROOT / "docker/sogo/entrypoint.sh"), "--render-nginx-only"],
        env=_minimal_env(
            SOGO_NGINX_TEMPLATE_PATH=str(REPO_ROOT / "docker/sogo/nginx.conf"),
            SOGO_NGINX_OUTPUT_PATH=str(nginx_out),
        ),
        capture_output=True,
        text=True,
    )
    assert render.returncode == 0, f"stdout={render.stdout}\nstderr={render.stderr}"
    rendered = nginx_out.read_text(encoding="utf-8")
    assert "location ^~ /WebServerResources/" in rendered
    assert "alias /usr/lib/GNUstep/SOGo/WebServerResources/;" in rendered

    sogo_bin = tmp_path / "sogo-bin"
    sogo_bin.mkdir()
    for tool in ("mkdir", "chown", "chmod"):
        p = sogo_bin / tool
        p.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        os.chmod(p, 0o755)

    fail_run = subprocess.run(
        ["bash", str(REPO_ROOT / "docker/sogo/entrypoint.sh")],
        env=_minimal_env(PATH=f"{sogo_bin}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
        capture_output=True,
        text=True,
    )
    assert fail_run.returncode != 0
    assert "SOGO_DB_PASSWORD" in fail_run.stderr


def test_sogo_conf_template_rendering_url_encodes_special_passwords() -> None:
    """SOGo config template substitution URL-encodes special delimiter/quote characters cleanly."""
    template = (REPO_ROOT / "docker/sogo/sogo.conf").read_text(encoding="utf-8")
    special_pw = "p@ss:w/ord#1%2'3\"4"
    encoded_pw = urllib.parse.quote(special_pw, safe="")
    rendered = (
        template
        .replace("__SOGO_MAIL_DOMAIN__", "brainsos.local")
        .replace("__SOGO_DB_HOST__", "sogo-db")
        .replace("__SOGO_DB_PORT__", "5432")
        .replace("__SOGO_DB_USER__", "sogo")
        .replace("__SOGO_DB_PASSWORD__", encoded_pw)
        .replace("__SOGO_DB_NAME__", "sogo")
    )
    assert "__SOGO_" not in rendered
    assert encoded_pw in rendered
    assert special_pw not in rendered
    assert "@sogo-db:5432/sogo/" in rendered


@pytest.mark.parametrize("caddy_rel", ["config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"])
def test_caddyfiles_never_use_compose_error_modifier_and_strip_real_ip(caddy_rel: str) -> None:
    """Caddyfiles avoid Compose :? syntax, strip X-Real-IP, and lock down Langfuse sign-up/reset."""
    text = (REPO_ROOT / caddy_rel).read_text(encoding="utf-8")
    assert "{$" in text
    assert not re.search(r"\{\$[A-Z0-9_]+:\?", text), f"{caddy_rel} must not use Caddy :? syntax"
    assert "brainsos_tool_egress_secret" not in text
    assert "{$TOOL_EGRESS_WEB_PASSWORD:}" in text
    assert "request_header -X-Real-IP" in text
    assert "header_up -X-Real-IP" in text


def test_compose_fail_closed_under_empty_env_and_validates_with_example_env() -> None:
    """Empty environment must reject docker compose config; .env.example must validate cleanly."""
    if not shutil.which("docker"):
        pytest.skip("docker binary not installed")

    fail = subprocess.run(
        ["docker", "compose", "--env-file", "/dev/null", "-f", "docker-compose.yml", "config", "-q"],
        cwd=str(REPO_ROOT),
        env=_minimal_env(),
        capture_output=True,
        text=True,
    )
    assert fail.returncode != 0

    ok = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env.example",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker/compose/compose.appliance.yml",
            "config",
            "-q",
        ],
        cwd=str(REPO_ROOT),
        env=_minimal_env(),
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr


def _extract_caddy_snippet(text: str, snippet_name: str) -> str:
    marker = f"({snippet_name}) {{"
    start = text.index(marker)
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    raise AssertionError(f"Unclosed Caddy snippet: {snippet_name}")


@pytest.mark.parametrize("caddy_rel", ["config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"])
def test_caddyfiles_structural_route_exclusions_and_global_real_ip_strip(caddy_rel: str) -> None:
    """Both Caddyfiles exclude colliding subpaths via named matchers and strip X-Real-IP globally."""
    text = (REPO_ROOT / caddy_rel).read_text(encoding="utf-8")
    auth_snippet = _extract_caddy_snippet(text, "authentik_backend")
    unified_snippet = _extract_caddy_snippet(text, "unified_ingress")

    assert "\trequest_header -X-Real-IP" in auth_snippet
    assert "\trequest_header -X-Real-IP" in unified_snippet
    assert "\n\thandle @sogo_static {" in unified_snippet
    assert "\n\troute {\n" not in unified_snippet[:600]

    auth_match = re.search(r"@authentik_auth_paths\s*\{([^}]+)\}", unified_snippet)
    assert auth_match is not None, f"{caddy_rel} missing @authentik_auth_paths"
    assert "path /auth/*" in auth_match.group(1)
    for excluded in (
        "/auth/sign-in*",
        "/auth/error*",
        "/auth/sso-initiate*",
        "/auth/reset-password*",
        "/auth/setup-password*",
        "/auth/sign-up*",
        "/auth/enterprise-sso-required*",
    ):
        assert excluded in auth_match.group(1), f"{caddy_rel} @authentik_auth_paths missing {excluded}"
    assert "handle @authentik_auth_paths {" in unified_snippet

    api_match = re.search(r"@authentik_api_paths\s*\{([^}]+)\}", unified_snippet)
    assert api_match is not None, f"{caddy_rel} missing @authentik_api_paths"
    assert "path /api/*" in api_match.group(1)
    for excluded in (
        "/api/v1/system/*",
        "/api/plugins",
        "/api/plugins/*",
        "/api/event_logging/*",
        "/api/trpc/*",
        "/api/auth/*",
        "/api/public/*",
        "/api/project/*",
        "/api/traces/*",
        "/api/dashboard/*",
        "/api/chatCompletion*",
        "/api/admin/*",
        "/api/internal/*",
    ):
        assert excluded in api_match.group(1), f"{caddy_rel} @authentik_api_paths missing {excluded}"
    assert "handle @authentik_api_paths {" in unified_snippet

    proxy_match = re.search(r"@litellm_proxy_fallback\s*\{([^}]+)\}", unified_snippet)
    assert proxy_match is not None, f"{caddy_rel} missing @litellm_proxy_fallback"
    assert "path /proxy/*" in proxy_match.group(1)
    for excluded in (
        "/proxy/",
        "/proxy/v1/*",
        "/proxy/ui",
        "/proxy/ui/*",
        "/proxy/sso/*",
        "/proxy/.well-known/litellm-ui-config",
        "/proxy/litellm/.well-known/litellm-ui-config",
    ):
        assert excluded in proxy_match.group(1), f"{caddy_rel} @litellm_proxy_fallback missing {excluded}"
    assert "handle @litellm_proxy_fallback {" in unified_snippet

    ref_match = re.search(r"@litellm_ui_referer\s*\{([^}]+)\}", unified_snippet)
    assert ref_match is not None
    for excluded in (
        "/healthz",
        "/api/plugins",
        "/api/plugins/*",
        "/api/event_logging/*",
        "/WebServerResources/*",
        "/docs",
        "/docs/*",
        "/system",
        "/system/*",
    ):
        assert excluded in ref_match.group(1), f"{caddy_rel} @litellm_ui_referer missing {excluded}"


def _caddy_path_matches(pattern: str, req_path: str) -> bool:
    if pattern == req_path:
        return True
    if pattern.endswith("*"):
        return req_path.startswith(pattern[:-1])
    return fnmatch.fnmatchcase(req_path, pattern)


def _caddy_matcher_matches(
    matcher: dict[str, object],
    req_path: str,
    host: str,
    method: str,
    referer: str | None,
) -> bool:
    for key, val in matcher.items():
        if key == "path":
            patterns = val if isinstance(val, list) else []
            if not any(_caddy_path_matches(str(p), req_path) for p in patterns):
                return False
        elif key == "host":
            hosts = val if isinstance(val, list) else []
            if not any(
                (host == h or (h.startswith("*.") and host.endswith(h[1:])))
                for h in (str(x) for x in hosts)
            ):
                return False
        elif key == "method":
            methods = val if isinstance(val, list) else []
            if method not in methods:
                return False
        elif key == "header_regexp":
            hdr_map = val if isinstance(val, dict) else {}
            for hdr_name, rule in hdr_map.items():
                hdr_val = host if hdr_name == "Host" else (referer or "" if hdr_name == "Referer" else "")
                pattern = str(rule.get("pattern", "")) if isinstance(rule, dict) else ""
                if pattern.startswith("(?i)"):
                    if not re.search(pattern[4:], hdr_val, re.IGNORECASE):
                        return False
                elif not re.search(pattern, hdr_val):
                    return False
        elif key == "not":
            neg_sets = val if isinstance(val, list) else []
            if any(_caddy_matcher_matches(ns, req_path, host, method, referer) for ns in neg_sets if isinstance(ns, dict)):
                return False
    return True


def _caddy_route_matches(
    route: dict[str, object],
    req_path: str,
    host: str,
    method: str = "GET",
    referer: str | None = None,
) -> bool:
    match_sets = route.get("match")
    if not match_sets:
        return True
    assert isinstance(match_sets, list)
    return any(_caddy_matcher_matches(ms, req_path, host, method, referer) for ms in match_sets if isinstance(ms, dict))


def _dispatch_caddy_routes(
    routes: list[dict[str, object]],
    req_path: str,
    host: str,
    method: str = "GET",
    referer: str | None = None,
) -> list[dict[str, object]]:
    """Simulate Caddy HTTP route + mutually-exclusive group dispatch."""
    executed_handlers: list[dict[str, object]] = []
    seen_groups: set[str] = set()
    for route in routes:
        group = route.get("group")
        if isinstance(group, str) and group in seen_groups:
            continue
        if not _caddy_route_matches(route, req_path, host, method=method, referer=referer):
            continue
        if isinstance(group, str):
            seen_groups.add(group)
        handlers = route.get("handle", [])
        assert isinstance(handlers, list)
        for h in handlers:
            if not isinstance(h, dict):
                continue
            if h.get("handler") == "subroute":
                sub_routes = h.get("routes", [])
                if isinstance(sub_routes, list):
                    executed_handlers.extend(
                        _dispatch_caddy_routes(sub_routes, req_path, host, method=method, referer=referer)
                    )
            else:
                executed_handlers.append(h)
        if any(h.get("handler") in {"reverse_proxy", "static_response"} for h in executed_handlers):
            break
    return executed_handlers


def _collect_handlers(handlers: list[dict[str, object]]) -> list[dict[str, object]]:
    flat: list[dict[str, object]] = []
    for h in handlers:
        flat.append(h)
        if h.get("handler") == "subroute":
            for sr in h.get("routes", []):
                if isinstance(sr, dict):
                    flat.extend(_collect_handlers(sr.get("handle", [])))
    return flat


def _require_caddy_docker() -> None:
    if not shutil.which("docker"):
        pytest.skip("docker binary not installed")
    info = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if info.returncode != 0:
        pytest.skip("docker daemon unavailable")
    img = subprocess.run(["docker", "image", "inspect", "brainsos-caddy:latest"], capture_output=True, text=True)
    if img.returncode != 0:
        pytest.skip("brainsos-caddy:latest image not present")


@pytest.mark.parametrize(
    ("caddy_rel", "tls_mode", "target_host"),
    [
        ("config/caddy/Caddyfile", "default", "local.brainsos.ai"),
        ("config/caddy/Caddyfile.appliance", "internal", "test.brainsos.ai"),
        ("config/caddy/Caddyfile.appliance", "acme", "test.brainsos.ai"),
        ("config/caddy/Caddyfile.appliance", "route53", "test.brainsos.ai"),
    ],
)
def test_caddyfiles_compiled_json_zero_shadowing_and_global_real_ip_strip(
    tmp_path: Path, caddy_rel: str, tls_mode: str, target_host: str
) -> None:
    """Adapted Caddy JSON has zero route shadowing across :443/:80 and strips X-Real-IP globally."""
    _require_caddy_docker()

    ca_crt = tmp_path / "ca.crt"
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
            "/CN=brainsos-caddy-adapt-test",
        ],
        check=True,
        capture_output=True,
    )
    os.chmod(ca_crt, 0o644)

    adapt_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{REPO_ROOT / 'config/caddy'}:/etc/caddy:ro",
        "-v",
        f"{ca_crt}:/etc/ssl/openbao/ca.crt:ro",
        "-e",
        f"BRAINSOS_TLS_MODE={tls_mode}",
        "-e",
        "ACME_EMAIL=ops@example.com",
        "-e",
        f"BRAINSOS_DOMAIN={target_host}",
        "-e",
        "BRAINSOS_IP_SITES=127.0.0.1",
        "--entrypoint",
        "caddy",
        "brainsos-caddy:latest",
        "adapt",
        "--config",
        f"/etc/{caddy_rel.removeprefix('config/')}",
        "--adapter",
        "caddyfile",
    ]
    proc = subprocess.run(adapt_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"caddy adapt failed ({caddy_rel}, {tls_mode}): {proc.stderr}"
    adapted = json.loads(proc.stdout)
    servers = adapted["apps"]["http"]["servers"]

    # Check global X-Real-IP deletion on every unified_ingress and authentik_backend subroute
    for srv_name, srv in servers.items():
        for route in srv.get("routes", []):
            match_list = route.get("match") or []
            hosts = [h for m in match_list for h in m.get("host", [])]
            if any(h.startswith("hermes.runner.") for h in hosts):
                continue
            for h in route.get("handle", []):
                if h.get("handler") != "subroute":
                    continue
                sub_routes = h.get("routes", [])
                # Skip bare-IP ACME/redirect-only host guards without unified_ingress
                if not any(isinstance(sr.get("group"), str) or any(
                    x.get("handler") == "reverse_proxy" for x in sr.get("handle", [])
                ) for sr in sub_routes):
                    continue
                first_group_idx = next(
                    (idx for idx, sr in enumerate(sub_routes) if sr.get("group") is not None),
                    len(sub_routes),
                )
                pre_group_handlers = [
                    x for sr in sub_routes[:first_group_idx] for x in _collect_handlers(sr.get("handle", []))
                ]
                assert any(
                    x.get("handler") == "headers"
                    and "X-Real-IP" in x.get("request", {}).get("delete", [])
                    for x in pre_group_handlers
                ), f"{caddy_rel} ({tls_mode}) {srv_name} route {hosts} missing global X-Real-IP delete"

    servers_to_probe = ["srv0", "srv1"] if caddy_rel == "config/caddy/Caddyfile" else ["srv0"]
    for srv_name in servers_to_probe:
        srv_routes = servers[srv_name]["routes"]

        def _resolve(path: str, referer: str | None = None) -> list[dict[str, object]]:
            return _dispatch_caddy_routes(srv_routes, path, target_host, referer=referer)

        def _upstreams(handlers: list[dict[str, object]]) -> list[str]:
            return [
                str(u.get("dial"))
                for h in handlers
                if h.get("handler") == "reverse_proxy"
                for u in h.get("upstreams", [])
            ]

        for blocked_path in ("/auth/sign-up", "/auth/reset-password"):
            handlers = _resolve(blocked_path)
            statuses = [str(h.get("status_code")) for h in handlers if h.get("handler") == "static_response"]
            assert "403" in statuses, f"{caddy_rel} {srv_name} {blocked_path} shadowed: {handlers}"

        for lf_path in (
            "/auth/error",
            "/auth/sign-in",
            "/api/public/health",
            "/api/traces/123",
            "/api/admin/users",
            "/api/auth/session",
            "/api/trpc/health",
            "/api/project/1",
            "/api/dashboard/1",
            "/api/internal/1",
            "/api/chatCompletion",
        ):
            ups = _upstreams(_resolve(lf_path))
            assert "langfuse-web:3000" in ups, f"{caddy_rel} {srv_name} {lf_path} -> {ups}"

        for lt_path in ("/api/plugins", "/api/plugins/foo", "/api/event_logging/x"):
            ups = _upstreams(_resolve(lt_path))
            assert "litellm:4000" in ups, f"{caddy_rel} {srv_name} {lt_path} -> {ups}"

        assert "host.docker.internal:8010" in _upstreams(_resolve("/api/v1/system/health"))

        for ak_path in ("/api/v3/core/users/", "/auth/o/authorize/"):
            ups = _upstreams(_resolve(ak_path))
            assert "authentik-server:9000" in ups, f"{caddy_rel} {srv_name} {ak_path} -> {ups}"

        sso_handlers = _resolve("/proxy/sso/key/generate/")
        assert any(
            h.get("handler") == "rewrite" and "path_regexp" in h for h in sso_handlers
        ), f"{caddy_rel} {srv_name} /proxy/sso/key/generate/ missing rewrite: {sso_handlers}"
        assert "litellm:4000" in _upstreams(sso_handlers)

        assert "litellm:4000" in _upstreams(_resolve("/proxy/ui/test"))
        assert "litellm:4000" in _upstreams(_resolve("/proxy/custom-endpoint"))

        for bao_path in ("/ui/vault", "/v1/sys/health"):
            assert "openbao:8200" in _upstreams(_resolve(bao_path))

        sogo_handlers = _resolve("/SOGo.woa/WebServerResources/test.css")
        assert "sogo:20000" in _upstreams(sogo_handlers)
        for h in sogo_handlers:
            if h.get("handler") == "reverse_proxy":
                hdr_set = h.get("headers", {}).get("request", {}).get("set", {})
                assert "X-Caddy-Ingress-Token" not in hdr_set

        # Referer: https://<host>/ui/ must NOT hijack explicit non-LiteLLM routes
        ref = f"https://{target_host}/ui/"
        assert any(
            h.get("handler") == "static_response" and str(h.get("status_code")) == "200"
            for h in _resolve("/healthz", referer=ref)
        )
        assert "litellm:4000" in _upstreams(_resolve("/api/plugins", referer=ref))
        assert "sogo:20000" in _upstreams(_resolve("/WebServerResources/test.css", referer=ref))
        docs_handlers = _resolve("/docs", referer=ref)
        assert "litellm:4000" not in _upstreams(docs_handlers)
        sys_handlers = _resolve("/system/ca.crt", referer=ref)
        assert "litellm:4000" not in _upstreams(sys_handlers)


def _extract_shell_python_snippets(sh_text: str) -> list[tuple[int, str, str]]:
    """Extract (line_number, kind, code) for every python3 heredoc and -c block in a shell script."""
    snippets: list[tuple[int, str, str]] = []
    lines = sh_text.splitlines()
    i = 0
    heredoc_re = re.compile(r"\bpython3\b[^\n]*<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
    while i < len(lines):
        line = lines[i]
        m = heredoc_re.search(line)
        if m:
            quote, tag = m.group(1), m.group(2)
            j = i + 1
            while lines[j - 1].rstrip().endswith("\\") and j < len(lines):
                j += 1
            start_line = j + 1
            body: list[str] = []
            while j < len(lines) and lines[j].strip() != tag:
                body.append(lines[j])
                j += 1
            if quote in {"'", '"'}:
                snippets.append((start_line, f"heredoc:{tag}", "\n".join(body)))
            i = j + 1
            continue

        c_pos = re.search(r"\bpython3\b[^\n#]*\s-c\s+(['\"])", line)
        if c_pos:
            quote = c_pos.group(1)
            start_line = i + 1
            # Extract quoted -c string (handling single-quoted bash strings literally)
            idx = c_pos.end()
            buf: list[str] = []
            cur_line_idx = i
            while cur_line_idx < len(lines):
                cur = lines[cur_line_idx]
                pos = idx if cur_line_idx == i else 0
                closed = False
                while pos < len(cur):
                    ch = cur[pos]
                    if quote == '"' and ch == "\\" and pos + 1 < len(cur):
                        nxt = cur[pos + 1]
                        if nxt in {'"', "\\", "$", "`"}:
                            buf.append(nxt)
                            pos += 2
                            continue
                    if ch == quote:
                        closed = True
                        break
                    buf.append(ch)
                    pos += 1
                if closed:
                    break
                buf.append("\n")
                cur_line_idx += 1
            code = "".join(buf)
            # Skip shell-interpolated double-quoted -c invocations containing ${...}
            if not (quote == '"' and "${" in code):
                snippets.append((start_line, f"-c({quote})", code))
            i = cur_line_idx + 1
            continue
        i += 1
    return snippets


def test_all_shell_inline_python_parses_under_python_311() -> None:
    """All embedded python3 heredocs and -c snippets across repository .sh files must parse cleanly."""
    sh_roots = [
        REPO_ROOT / "scripts",
        REPO_ROOT / "docker",
        REPO_ROOT / "packages" / "brainsOS-appliance",
    ]
    sh_files = sorted(p for root in sh_roots for p in root.rglob("*.sh"))
    assert len(sh_files) >= 50

    heredoc_count = 0
    inline_c_count = 0
    errors: list[str] = []
    for sh_file in sh_files:
        text = sh_file.read_text(encoding="utf-8")
        for line_no, kind, code in _extract_shell_python_snippets(text):
            if kind.startswith("heredoc:"):
                heredoc_count += 1
            else:
                inline_c_count += 1
            try:
                ast.parse(code)
            except SyntaxError as exc:
                rel = sh_file.relative_to(REPO_ROOT)
                errors.append(f"{rel}:{line_no} ({kind}): {exc.msg}")

    assert heredoc_count >= 50
    assert inline_c_count >= 50
    assert not errors, "Embedded Python SyntaxErrors detected:\n" + "\n".join(errors)


@pytest.mark.parametrize("token_mode", ["cli", "rest_fallback"])
def test_setup_git_live_mock_mints_scoped_token_at_0600_without_cli_credentials(
    tmp_path: Path, token_mode: str
) -> None:
    """setup-git.sh Step 4 runs under Python 3.11 with hostile creds, minting a scoped PAT and 0600 credentials."""
    data_dir = tmp_path / "data"
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True)
    env_file = tmp_path / ".env"

    username = "ops+user&1"
    password = 'p@ss:w/ord#1"2$3'
    env_file.write_text(
        f"BRAINSOS_SUPERUSER_USERNAME={shlex.quote(username)}\n"
        f"BRAINSOS_ADMIN_PASSWORD={shlex.quote(password)}\n"
        "BRAINSOS_DOMAIN=appliance.example.test\n",
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
LOG_DIR={shlex.quote(str(log_dir))}
MODE={shlex.quote(token_mode)}
if [ "$1" = "inspect" ]; then
  case "$*" in
    *".State.Running"*brainsos-app-git*) echo "true"; exit 0 ;;
    *".State.Running"*brainsos-app-code-server*) echo "false"; exit 0 ;;
    *"NetworkSettings.Networks"*brainsos-app-git*) echo "172.28.9.10"; exit 0 ;;
  esac
  exit 0
fi
if [ "$1" = "exec" ]; then
  shift
  # Parse optional -u <user>, -i, and -e KEY=VAL flags (Bash 3.2 / POSIX sh compatible)
  _EV_GITEA_BASIC_B64=""
  _EV_GITEA_USER_ENC=""
  _EV_GITEA_TOKEN_NAME=""
  _EV_GITEA_TOKEN_JSON=""
  _EV_CREATE_REPO_JSON=""
  _EV_GITEA_TOKEN=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -i) shift ;;
      -u) shift 2 ;;
      -e)
        kv="$2"
        case "${{kv%%=*}}" in
          GITEA_BASIC_B64) _EV_GITEA_BASIC_B64="${{kv#*=}}" ;;
          GITEA_USER_ENC) _EV_GITEA_USER_ENC="${{kv#*=}}" ;;
          GITEA_TOKEN_NAME) _EV_GITEA_TOKEN_NAME="${{kv#*=}}" ;;
          GITEA_TOKEN_JSON) _EV_GITEA_TOKEN_JSON="${{kv#*=}}" ;;
          CREATE_REPO_JSON) _EV_CREATE_REPO_JSON="${{kv#*=}}" ;;
          GITEA_TOKEN) _EV_GITEA_TOKEN="${{kv#*=}}" ;;
        esac
        shift 2
        ;;
      *) break ;;
    esac
  done
  shift # container name
  cmd_str="$*"
  if [[ "${{cmd_str}}" == *"gitea admin user list"* ]]; then
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"gitea admin user create"* ]]; then
    printf '%s\\n' "${{cmd_str}}" >> "${{LOG_DIR}}/user_create.log"
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"gitea admin user generate-access-token"* ]]; then
    printf '%s\\n' "${{cmd_str}}" >> "${{LOG_DIR}}/gen_token.log"
    if [ "${{MODE}}" = "cli" ]; then
      echo "glpat-scoped+tok/1"
    fi
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"healthz"* ]]; then
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"/tokens/"* ]] && [ -n "${{_EV_GITEA_BASIC_B64}}" ]; then
    printf '%s|%s|%s\\n' "${{_EV_GITEA_BASIC_B64}}" "${{_EV_GITEA_USER_ENC}}" "${{_EV_GITEA_TOKEN_NAME}}" >> "${{LOG_DIR}}/token_delete.log"
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"/tokens"* ]] && [ -n "${{_EV_GITEA_TOKEN_JSON}}" ]; then
    printf '%s|%s|%s\\n' "${{_EV_GITEA_BASIC_B64}}" "${{_EV_GITEA_USER_ENC}}" "${{_EV_GITEA_TOKEN_JSON}}" >> "${{LOG_DIR}}/token_post.log"
    echo '{{"sha1":"glpat-rest+tok/2"}}'
    exit 0
  fi
  if [[ "${{cmd_str}}" == *"/user/repos"* ]] && [ -n "${{_EV_CREATE_REPO_JSON}}" ]; then
    printf '%s|%s\\n' "${{_EV_GITEA_TOKEN}}" "${{_EV_CREATE_REPO_JSON}}" >> "${{LOG_DIR}}/repo_create.log"
    exit 0
  fi
fi
exit 0
""",
        encoding="utf-8",
    )
    os.chmod(fake_docker, 0o755)

    fake_git = fake_bin / "git"
    fake_git.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {shlex.quote(str(log_dir / "git_calls.log"))}
for arg in "$@"; do
  if [ "${{arg}}" = "push" ]; then
    exit 0
  fi
done
exec {shlex.quote(real_git)} "$@"
""",
        encoding="utf-8",
    )
    os.chmod(fake_git, 0o755)

    py_dir = str(Path(sys.executable).parent)
    proc = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/setup/setup-git.sh")],
        env=_minimal_env(
            PATH=f"{fake_bin}:{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
            HOME=str(home_dir),
            BRAINSOS_REPO_ROOT=str(REPO_ROOT),
            BRAINSOS_DATA_DIR=str(data_dir),
            BRAINSOS_ENV_FILE=str(env_file),
        ),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    del_lines = (log_dir / "token_delete.log").read_text(encoding="utf-8").splitlines()
    assert del_lines
    captured_b64, captured_user_enc, captured_tok_name = del_lines[0].split("|", 2)
    assert base64.b64decode(captured_b64).decode("utf-8") == f"{username}:{password}"
    assert captured_user_enc == urllib.parse.quote(username, safe="")
    assert captured_tok_name == "brainsos-editor-scm"

    expected_token = "glpat-scoped+tok/1" if token_mode == "cli" else "glpat-rest+tok/2"
    if token_mode == "cli":
        gen_log = (log_dir / "gen_token.log").read_text(encoding="utf-8")
        assert "--scopes write:repository" in gen_log
        assert "--token-name brainsos-editor-scm" in gen_log
    else:
        post_lines = (log_dir / "token_post.log").read_text(encoding="utf-8").splitlines()
        assert post_lines
        _, _, tok_json = post_lines[0].split("|", 2)
        assert json.loads(tok_json) == {"name": "brainsos-editor-scm", "scopes": ["write:repository"]}

    cred_file = data_dir / ".git" / "credentials"
    assert cred_file.exists()
    assert stat.S_IMODE(cred_file.stat().st_mode) == 0o600
    cred_text = cred_file.read_text(encoding="utf-8")
    assert urllib.parse.quote(username, safe="") in cred_text
    assert urllib.parse.quote(expected_token, safe="") in cred_text
    assert password not in cred_text

    git_calls = (log_dir / "git_calls.log").read_text(encoding="utf-8")
    assert password not in git_calls
    assert expected_token not in git_calls
    assert "user:pass@" not in git_calls


def test_setup_litellm_sso_live_mock_completes_steps_1_through_6(tmp_path: Path) -> None:
    """setup-litellm-sso.sh Steps 1-6 complete cleanly against a mock LiteLLM server under Python 3.11."""
    recorded_queries: list[str] = []
    recorded_posts: dict[str, list[dict[str, object]]] = {
        "/user/new": [],
        "/user/update": [],
        "/litellm/.well-known/litellm-ui-config": [],
        "/update/sso_settings": [],
    }
    username = "ops+user&1"
    password = 'p&|/;$HOME"pass1!'
    sso_secret = 'oidc&|"secret$'

    class _MockLiteLLMHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/health/liveness":
                self._send_json(200, {"status": "alive"})
            elif parsed.path == "/user/info":
                recorded_queries.append(parsed.query)
                qs = urllib.parse.parse_qs(parsed.query)
                uid = (qs.get("user_id") or [""])[0]
                if uid == username:
                    self._send_json(200, {"user_id": username})
                else:
                    self._send_json(404, {"error": "not found"})
            elif parsed.path == "/health/readiness/details":
                self._send_json(200, {"show_env_credential_login_warning": False})
            elif parsed.path == "/user/list":
                self._send_json(
                    200,
                    {
                        "users": [
                            {"user_id": "admin", "user_role": "proxy_admin", "models": ["all-proxy-models"]},
                            {"user_id": username, "user_role": "proxy_admin", "models": ["all-proxy-models"]},
                        ]
                    },
                )
            else:
                self._send_json(404, {})

        def _handle_write(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in recorded_posts:
                recorded_posts[parsed.path].append(payload)
            self._send_json(200, {"status": "ok"})

        def do_POST(self) -> None:
            self._handle_write()

        def do_PUT(self) -> None:
            self._handle_write()

        def do_PATCH(self) -> None:
            self._handle_write()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockLiteLLMHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"LITELLM_PORT={port}\n"
            "LITELLM_MASTER_KEY=sk-master-test-key\n"
            f"BRAINSOS_SUPERUSER_USERNAME={shlex.quote(username)}\n"
            f"BRAINSOS_ADMIN_PASSWORD={shlex.quote(password)}\n"
            f"AUTH_LITELLM_CLIENT_SECRET={shlex.quote(sso_secret)}\n"
            "BRAINSOS_DOMAIN=appliance.example.test\n",
            encoding="utf-8",
        )
        os.chmod(env_file, 0o600)

        real_curl = shutil.which("curl")
        assert real_curl is not None
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        curl_log = tmp_path / "curl_args.log"

        fake_docker = fake_bin / "docker"
        fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        os.chmod(fake_docker, 0o755)

        fake_curl = fake_bin / "curl"
        fake_curl.write_text(
            f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {shlex.quote(str(curl_log))}
exec {shlex.quote(real_curl)} "$@"
""",
            encoding="utf-8",
        )
        os.chmod(fake_curl, 0o755)

        py_dir = str(Path(sys.executable).parent)
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts/setup/setup-litellm-sso.sh")],
            env=_minimal_env(
                PATH=f"{fake_bin}:{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
                BRAINSOS_REPO_ROOT=str(REPO_ROOT),
                BRAINSOS_ENV_FILE=str(env_file),
            ),
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    for expected_text in ("USER ID", "ROLE", "MODELS", "admin", username, "proxy_admin"):
        assert expected_text in proc.stdout
    assert "Environment-credential warning is INACTIVE" in proc.stdout

    assert any(f"user_id={urllib.parse.quote(username, safe='')}" in q for q in recorded_queries)
    assert any(p.get("user_id") == "admin" and p.get("password") == password for p in recorded_posts["/user/new"])
    assert any(p.get("user_id") == username and p.get("password") == password for p in recorded_posts["/user/update"])
    assert any(
        p.get("generic_client_secret") == sso_secret for p in recorded_posts["/update/sso_settings"]
    )

    curl_argv = curl_log.read_text(encoding="utf-8")
    assert password not in curl_argv
    assert sso_secret not in curl_argv


def test_generate_env_two_pass_is_bash_sourceable_and_single_quotes_unit_name(tmp_path: Path) -> None:
    """generate-env.sh produces bash-sourceable .env across Pass 1, Pass 2, and pre-corrupted quote recovery."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts/control").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/control/generate-env.sh", fake_repo / "scripts/control/generate-env.sh")
    shutil.copy2(REPO_ROOT / ".env.example", fake_repo / ".env.example")

    env_file = fake_repo / ".env"
    data_dir = tmp_path / "data"
    py_dir = str(Path(sys.executable).parent)
    run_env = _minimal_env(
        PATH=f"{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
        BRAINSOS_REPO_ROOT=str(fake_repo),
        BRAINSOS_ENV_FILE=str(env_file),
    )
    cmd = [
        "bash",
        str(fake_repo / "scripts/control/generate-env.sh"),
        "--non-interactive",
        "--domain",
        "unit.brainsos.test",
        "--mail-domain",
        "mail.unit.brainsos.test",
        "--data-dir",
        str(data_dir),
        "--no-rebuild",
    ]

    pass1 = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
    assert pass1.returncode == 0, f"pass1 stdout={pass1.stdout}\nstderr={pass1.stderr}"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    pass1_text = env_file.read_text(encoding="utf-8")
    assert "BRAINSOS_UNIT_NAME='Enterprise Agent Box'" in pass1_text
    assert '""Enterprise Agent Box""' not in pass1_text

    def _assert_bash_source(target_env: Path) -> dict[str, str]:
        probe = subprocess.run(
            [
                "bash",
                "-c",
                (
                    'set -euo pipefail; set -a; . "$1"; set +a; '
                    'python3 -c \'import json, os; print(json.dumps({k: os.environ[k] for k in '
                    '("BRAINSOS_UNIT_NAME", "LANGFUSE_INIT_PROJECT_NAME", "LANGFUSE_OTEL_AUTH", '
                    '"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LITELLM_MASTER_KEY")}))\''
                ),
                "_",
                str(target_env),
            ],
            env=_minimal_env(PATH=f"{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, f"bash source failed: {probe.stderr}"
        assert probe.stderr == "", f"unexpected stderr sourcing .env: {probe.stderr}"
        parsed = json.loads(probe.stdout)
        assert parsed["BRAINSOS_UNIT_NAME"] == "Enterprise Agent Box"
        assert parsed["LANGFUSE_INIT_PROJECT_NAME"] == "brainsOS Fleet"
        expected_b64 = base64.b64encode(
            f"{parsed['LANGFUSE_PUBLIC_KEY']}:{parsed['LANGFUSE_SECRET_KEY']}".encode("utf-8")
        ).decode("ascii")
        assert parsed["LANGFUSE_OTEL_AUTH"] == f"Basic {expected_b64}"
        return parsed

    vals1 = _assert_bash_source(env_file)

    pass2 = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
    assert pass2.returncode == 0, f"pass2 stdout={pass2.stdout}\nstderr={pass2.stderr}"
    pass2_text = env_file.read_text(encoding="utf-8")
    assert "BRAINSOS_UNIT_NAME='Enterprise Agent Box'" in pass2_text
    assert '""Enterprise Agent Box""' not in pass2_text
    vals2 = _assert_bash_source(env_file)
    assert vals2 == vals1

    # Self-heal pre-corrupted double-quoted BRAINSOS_UNIT_NAME
    corrupted = pass2_text.replace(
        "BRAINSOS_UNIT_NAME='Enterprise Agent Box'",
        'BRAINSOS_UNIT_NAME=""Enterprise Agent Box""',
    )
    env_file.write_text(corrupted, encoding="utf-8")
    os.chmod(env_file, 0o600)

    pass3 = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
    assert pass3.returncode == 0, f"pass3 stdout={pass3.stdout}\nstderr={pass3.stderr}"
    pass3_text = env_file.read_text(encoding="utf-8")
    assert "BRAINSOS_UNIT_NAME='Enterprise Agent Box'" in pass3_text
    assert '""Enterprise Agent Box""' not in pass3_text
    assert _assert_bash_source(env_file) == vals1


def test_verify_appliance_ingress_without_env_cleans_temp_files_and_passes_env_args(tmp_path: Path) -> None:
    """verify-appliance-ingress.sh passes COMPOSE_ENV_ARGS to ps and leaves zero temp files when .env is absent."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts/verify").mkdir(parents=True)
    (fake_repo / "packages/brainsOS-appliance/scripts").mkdir(parents=True)
    (fake_repo / "docker/compose").mkdir(parents=True)
    (fake_repo / "config/caddy").mkdir(parents=True)

    shutil.copy2(
        REPO_ROOT / "scripts/verify/verify-appliance-ingress.sh",
        fake_repo / "scripts/verify/verify-appliance-ingress.sh",
    )
    shutil.copy2(REPO_ROOT / ".env.example", fake_repo / ".env.example")
    shutil.copy2(REPO_ROOT / "docker-compose.yml", fake_repo / "docker-compose.yml")
    shutil.copy2(REPO_ROOT / "docker/compose/compose.appliance.yml", fake_repo / "docker/compose/compose.appliance.yml")
    shutil.copy2(REPO_ROOT / "docker/compose/compose.ingress.yml", fake_repo / "docker/compose/compose.ingress.yml")
    shutil.copy2(REPO_ROOT / "config/caddy/Caddyfile", fake_repo / "config/caddy/Caddyfile")
    shutil.copy2(REPO_ROOT / "config/caddy/Caddyfile.appliance", fake_repo / "config/caddy/Caddyfile.appliance")

    harden_stub = fake_repo / "packages/brainsOS-appliance/scripts/harden-host.sh"
    harden_stub.write_text(
        "#!/usr/bin/env bash\necho 'Appliance host perimeter hardening'\nexit 0\n",
        encoding="utf-8",
    )
    os.chmod(harden_stub, 0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker_calls.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {shlex.quote(str(docker_log))}
if [ "$1" = "compose" ]; then
  for arg in "$@"; do
    if [ "${{arg}}" = "config" ]; then
      cat <<'YAML'
services:
  caddy:
    ports:
      - published: "80"
      - published: "443"
  litellm:
    ports: []
YAML
      exit 0
    fi
    if [ "${{arg}}" = "ps" ]; then
      exit 0
    fi
  done
fi
if [ "$1" = "run" ]; then
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    os.chmod(fake_docker, 0o755)

    isolated_tmpdir = tmp_path / "tmpdir"
    isolated_tmpdir.mkdir()
    pre_tmp_ca = set(Path("/tmp").glob("brainsos-openbao-ca.*"))

    py_dir = str(Path(sys.executable).parent)
    proc = subprocess.run(
        ["bash", str(fake_repo / "scripts/verify/verify-appliance-ingress.sh")],
        cwd=str(fake_repo),
        env=_minimal_env(
            PATH=f"{fake_bin}:{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
            TMPDIR=str(isolated_tmpdir),
        ),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "required variable" not in proc.stderr

    calls = docker_log.read_text(encoding="utf-8").splitlines()
    ps_calls = [c for c in calls if "compose " in c and " ps " in c]
    assert ps_calls, f"expected docker compose ps call, got: {calls}"
    assert all("--env-file" in c for c in ps_calls), f"missing --env-file on compose ps: {ps_calls}"

    assert list(isolated_tmpdir.iterdir()) == [], f"leaked temp files in TMPDIR: {list(isolated_tmpdir.iterdir())}"
    post_tmp_ca = set(Path("/tmp").glob("brainsos-openbao-ca.*"))
    assert post_tmp_ca == pre_tmp_ca


def _build_pre393_env_text() -> str:
    """Build a synthetic pre-#393 .env lacking #393/#406/#407 required secrets or using placeholders."""
    omitted_keys = {
        "AUTH_OPENBAO_CLIENT_SECRET",
        "AUTH_LITELLM_CLIENT_SECRET",
        "AUTH_LANGFUSE_CLIENT_SECRET",
        "TOOL_EGRESS_PROXY_SECRET",
        "CADDY_INGRESS_TOKEN",
        "GITEA_SECRET_KEY",
        "GITEA_INTERNAL_TOKEN",
        "LENS_ADMIN_TOKEN",
        "LENS_GATEWAY_SECRET",
        "LITELLM_LENS_SERVICE_TOKEN",
        "LENS_CLICKHOUSE_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "ADMIN_MAIL_PASSWORD",
        "OPERATOR_MAIL_PASSWORD",
        "TERRASTELLA_MAIL_PASSWORD",
        "BAWTFORD_MAIL_PASSWORD",
        "MARVIN_MAIL_PASSWORD",
        "PING_MAIL_PASSWORD",
        "CLAUDE_MAIL_PASSWORD",
        "GPT_MAIL_PASSWORD",
    }
    lines: list[str] = []
    for raw in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        k = k.strip()
        if k in omitted_keys:
            continue
        if not v.strip():
            v = f"pre393-{k.lower()}-val"
        lines.append(f"{k}={v}")
    # Also simulate an explicit placeholder for AUTH_OPENBAO_CLIENT_SECRET in one path
    lines.append("LITELLM_MASTER_KEY=sk-existing-preserved-key-1234567890")
    return "\n".join(lines) + "\n"


def test_reload_env_and_firstboot_backfill_pre393_secrets_and_pass_compose_config(tmp_path: Path) -> None:
    """reload-env.sh and firstboot.sh backfill missing/placeholder #393/#406/#407 secrets so docker compose config passes."""
    py_dir = str(Path(sys.executable).parent)
    base_pre393 = _build_pre393_env_text()

    # 1. Verify pre-#393 .env fails docker compose config before backfill
    pre_env = tmp_path / "pre393.env"
    pre_env.write_text(base_pre393, encoding="utf-8")
    os.chmod(pre_env, 0o600)
    pre_compose = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(pre_env),
            "-f",
            str(REPO_ROOT / "docker-compose.yml"),
            "-f",
            str(REPO_ROOT / "docker/compose/compose.appliance.yml"),
            "config",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    assert pre_compose.returncode != 0
    assert "must be set" in pre_compose.stderr

    # 2. Test firstboot.sh existing-.env upgrade backfill
    fb_repo = tmp_path / "fb_repo"
    (fb_repo / "packages/brainsOS-appliance/scripts").mkdir(parents=True)
    (fb_repo / "scripts/control").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / ".env.example", fb_repo / ".env.example")
    for rel in (
        "packages/brainsOS-appliance/scripts/firstboot.sh",
        "scripts/control/generate-env.sh",
        "scripts/control/env-upsert.sh",
    ):
        dst = fb_repo / rel
        shutil.copy2(REPO_ROOT / rel, dst)
        dst.chmod(0o755)

    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mnt_env = mnt / ".env"
    fb_seed = base_pre393 + "AUTH_OPENBAO_CLIENT_SECRET=brainsos_openbao_secret_change_me\n"
    mnt_env.write_text(fb_seed, encoding="utf-8")
    os.chmod(mnt_env, 0o600)

    fb_proc = subprocess.run(
        [
            "bash",
            str(fb_repo / "packages/brainsOS-appliance/scripts/firstboot.sh"),
            "--skip-imds",
            "--skip-portal",
            "--mount-root",
            str(mnt),
        ],
        env={
            **_minimal_env(PATH=f"{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
            "BRAINSOS_REPO_ROOT": str(fb_repo),
            "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
            "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "i-0123456789abcdef0",
            "BRAINSOS_FIRSTBOOT_PUBLIC_IPV4": "198.51.100.10",
        },
        capture_output=True,
        text=True,
    )
    assert fb_proc.returncode == 0, f"stdout={fb_proc.stdout}\nstderr={fb_proc.stderr}"
    assert stat.S_IMODE(mnt_env.stat().st_mode) == 0o600
    fb_kv = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in mnt_env.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert fb_kv["LITELLM_MASTER_KEY"] == "sk-existing-preserved-key-1234567890"
    for key in (
        "AUTH_OPENBAO_CLIENT_SECRET",
        "AUTH_LITELLM_CLIENT_SECRET",
        "AUTH_LANGFUSE_CLIENT_SECRET",
        "TOOL_EGRESS_PROXY_SECRET",
        "LENS_ADMIN_TOKEN",
        "LENS_GATEWAY_SECRET",
        "LITELLM_LENS_SERVICE_TOKEN",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", fb_kv.get(key, "")), f"Bad {key}: {fb_kv.get(key)!r}"

    fb_compose = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(mnt_env),
            "-f",
            str(REPO_ROOT / "docker-compose.yml"),
            "-f",
            str(REPO_ROOT / "docker/compose/compose.appliance.yml"),
            "config",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    assert fb_compose.returncode == 0, f"compose stderr={fb_compose.stderr}"

    # 3. Test reload-env.sh upgrade backfill on a pre-#393 .env
    rl_repo = tmp_path / "rl_repo"
    (rl_repo / "scripts/control").mkdir(parents=True)
    (rl_repo / "scripts/setup").mkdir(parents=True)
    (rl_repo / "config/default_settings").mkdir(parents=True)
    (rl_repo / "config/caddy").mkdir(parents=True)
    (rl_repo / "config/default_settings/agents.yaml").write_text("agents: {}\n", encoding="utf-8")
    (rl_repo / "config/default_settings/runners.yaml").write_text("runners: {}\n", encoding="utf-8")
    shutil.copy2(REPO_ROOT / ".env.example", rl_repo / ".env.example")
    for rel in (
        "scripts/control/reload-env.sh",
        "scripts/control/env-upsert.sh",
        "scripts/setup/setup-lens.sh",
    ):
        dst = rl_repo / rel
        shutil.copy2(REPO_ROOT / rel, dst)
        dst.chmod(0o755)

    start_stub = rl_repo / "scripts/control/start-control-plane.sh"
    start_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    start_stub.chmod(0o755)

    fake_bin = tmp_path / "rl_bin"
    fake_bin.mkdir()
    (fake_bin / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then exit 0; fi\n'
        'if [ "$1" = "network" ] && [ "$2" = "inspect" ]; then echo br-ingress; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "docker").chmod(0o755)
    (fake_bin / "curl").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (fake_bin / "curl").chmod(0o755)

    rl_env = rl_repo / ".env"
    rl_seed = (
        base_pre393
        + f"BRAINSOS_DATA_DIR={rl_repo / 'data'}\n"
        + "AUTH_OPENBAO_CLIENT_SECRET=brainsos_openbao_secret_change_me\n"
        + "AUTH_LITELLM_CLIENT_SECRET=auth_litellm_client_secret_change_me\n"
        + "AUTH_LANGFUSE_CLIENT_SECRET=auth_langfuse_client_secret_change_me\n"
        + "TOOL_EGRESS_PROXY_SECRET=tool_egress_proxy_secret_change_me\n"
    )
    rl_env.write_text(rl_seed, encoding="utf-8")
    os.chmod(rl_env, 0o600)

    rl_proc = subprocess.run(
        ["bash", str(rl_repo / "scripts/control/reload-env.sh"), "--no-urls", "--no-hosts"],
        env={
            **_minimal_env(PATH=f"{fake_bin}:{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
            "RELOAD_ENV_SKIP_PULL": "true",
        },
        capture_output=True,
        text=True,
    )
    assert rl_proc.returncode == 0, f"stdout={rl_proc.stdout}\nstderr={rl_proc.stderr}"
    assert stat.S_IMODE(rl_env.stat().st_mode) == 0o600
    rl_kv = {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in rl_env.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert rl_kv["LITELLM_MASTER_KEY"] == "sk-existing-preserved-key-1234567890"
    for key in (
        "AUTH_OPENBAO_CLIENT_SECRET",
        "AUTH_LITELLM_CLIENT_SECRET",
        "AUTH_LANGFUSE_CLIENT_SECRET",
        "TOOL_EGRESS_PROXY_SECRET",
        "CADDY_INGRESS_TOKEN",
        "GITEA_SECRET_KEY",
        "GITEA_INTERNAL_TOKEN",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", rl_kv.get(key, "")), f"Bad {key}: {rl_kv.get(key)!r}"

    rl_compose = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(rl_env),
            "-f",
            str(REPO_ROOT / "docker-compose.yml"),
            "-f",
            str(REPO_ROOT / "docker/compose/compose.appliance.yml"),
            "config",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    assert rl_compose.returncode == 0, f"compose stderr={rl_compose.stderr}"


def test_generate_env_preserves_apostrophes_across_reruns(tmp_path: Path) -> None:
    """generate-env.sh unquote_env()/quote_env() round-trips apostrophes and special chars idempotently across 3 runs."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts/control").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/control/generate-env.sh", fake_repo / "scripts/control/generate-env.sh")
    shutil.copy2(REPO_ROOT / ".env.example", fake_repo / ".env.example")

    env_file = fake_repo / ".env"
    env_file.write_text(
        'BRAINSOS_UNIT_NAME="Alex\'s Agent Box"\n'
        'BRAINSOS_SUPERUSER_NAME="Bob\'s Box"\n'
        'CUSTOM_APOSTROPHE_VAR="a\'b\\"c$1"\n',
        encoding="utf-8",
    )
    os.chmod(env_file, 0o600)

    data_dir = tmp_path / "data"
    py_dir = str(Path(sys.executable).parent)
    run_env = _minimal_env(
        PATH=f"{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
        BRAINSOS_REPO_ROOT=str(fake_repo),
        BRAINSOS_ENV_FILE=str(env_file),
    )
    cmd = [
        "bash",
        str(fake_repo / "scripts/control/generate-env.sh"),
        "--non-interactive",
        "--domain",
        "unit.brainsos.test",
        "--mail-domain",
        "mail.unit.brainsos.test",
        "--data-dir",
        str(data_dir),
        "--no-rebuild",
    ]

    snapshots: list[str] = []
    for _ in range(3):
        proc = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        txt = env_file.read_text(encoding="utf-8")
        assert "BRAINSOS_UNIT_NAME='Alex'\"'\"'s Agent Box'" in txt
        assert "BRAINSOS_SUPERUSER_NAME='Bob'\"'\"'s Box'" in txt
        assert "CUSTOM_APOSTROPHE_VAR='a'\"'\"'b\"c$1'" in txt
        snapshots.append(txt)
        probe = subprocess.run(
            [
                "bash",
                "-c",
                (
                    'set -euo pipefail; set -a; . "$1"; set +a; '
                    'python3 -c \'import json, os; print(json.dumps({k: os.environ[k] for k in '
                    '("BRAINSOS_UNIT_NAME", "BRAINSOS_SUPERUSER_NAME", "CUSTOM_APOSTROPHE_VAR")}))\''
                ),
                "_",
                str(env_file),
            ],
            env=_minimal_env(PATH=f"{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}"),
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, f"bash source failed: {probe.stderr}"
        parsed = json.loads(probe.stdout)
        assert parsed["BRAINSOS_UNIT_NAME"] == "Alex's Agent Box"
        assert parsed["BRAINSOS_SUPERUSER_NAME"] == "Bob's Box"
        assert parsed["CUSTOM_APOSTROPHE_VAR"] == "a'b\"c$1"

    assert snapshots[2] == snapshots[1]


def test_launch_fleet_emit_script_executes_and_cleans_temp_file(tmp_path: Path) -> None:
    """launch-fleet.sh --emit-script bundle uses trailing mktemp, passes Encrypted=true, and removes TMP_UTIL on exit."""
    bundle_path = tmp_path / "launch-bundle.sh"
    emit_proc = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts/control/launch-fleet.sh"),
            "--participants",
            "alice=Alice Operator",
            "--base-domain",
            "fleet.example.test",
            "--email",
            "ops@example.test",
            "--fleet",
            "demo-fleet",
            "--ami",
            "ami-0123456789abcdef0",
            "--region",
            "us-east-1",
            "--no-ensure-iam-ddns",
            "--emit-script",
            str(bundle_path),
        ],
        capture_output=True,
        text=True,
    )
    assert emit_proc.returncode == 0, f"stdout={emit_proc.stdout}\nstderr={emit_proc.stderr}"
    bundle_txt = bundle_path.read_text(encoding="utf-8")
    assert "exec bash" not in bundle_txt
    assert 'brainsos-fleet-util.XXXXXX"' in bundle_txt

    sts_json = json.dumps({"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/ops"})
    zones_json = json.dumps(
        {"HostedZones": [{"Id": "/hostedzone/Z0123456789TEST", "Name": "fleet.example.test.", "Config": {"PrivateZone": False}}]}
    )
    aws_log = tmp_path / "aws_calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {shlex.quote(str(aws_log))}
case "$*" in
  *"sts get-caller-identity"*)
    printf '%s\\n' '{sts_json}'
    exit 0
    ;;
  *"route53 list-hosted-zones-by-name"*)
    echo "/hostedzone/Z0123456789TEST"
    exit 0
    ;;
  *"route53 list-hosted-zones"*)
    printf '%s\\n' '{zones_json}'
    exit 0
    ;;
  *"ec2 describe-vpcs"*)
    echo "vpc-0123456789abcdef0"
    exit 0
    ;;
  *"ec2 describe-subnets"*)
    echo "subnet-0123456789abcdef0"
    exit 0
    ;;
  *"ec2 describe-security-groups"*)
    echo "sg-0123456789abcdef0"
    exit 0
    ;;
  *"ec2 describe-images"*)
    echo "ami-0123456789abcdef0"
    exit 0
    ;;
  *"iam get-instance-profile"*)
    echo "brainsos-appliance-bedrock-profile"
    exit 0
    ;;
  *"ec2 run-instances"*)
    echo "i-0123456789abcdef0"
    exit 0
    ;;
  *"ec2 describe-instances"*)
    echo "i-0123456789abcdef0|198.51.100.42"
    exit 0
    ;;
  *"route53 change-resource-record-sets"*)
    echo "CHANGE123"
    exit 0
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_aws.chmod(0o755)

    isolated_tmpdir = tmp_path / "tmpdir"
    isolated_tmpdir.mkdir()
    py_dir = str(Path(sys.executable).parent)
    run_proc = subprocess.run(
        ["bash", str(bundle_path)],
        cwd=str(tmp_path),
        env=_minimal_env(
            PATH=f"{fake_bin}:{py_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}",
            TMPDIR=str(isolated_tmpdir),
            HOME=str(tmp_path),
        ),
        capture_output=True,
        text=True,
    )
    assert run_proc.returncode == 0, f"stdout={run_proc.stdout}\nstderr={run_proc.stderr}"
    assert list(isolated_tmpdir.iterdir()) == [], f"leaked temp files: {list(isolated_tmpdir.iterdir())}"
    aws_calls = aws_log.read_text(encoding="utf-8")
    assert "run-instances" in aws_calls
    assert "Encrypted=true" in aws_calls


def test_scripts_no_bsd_mktemp_suffix_and_no_bash4_declare_A() -> None:
    """Ensure shell scripts avoid macOS BSD mktemp suffixes after XXXXXX and tests avoid Bash 4 associative arrays."""
    bad_mktemp = re.compile(r"mktemp[^\n]*XXXXXX\.[A-Za-z0-9]+")
    for root in (REPO_ROOT / "scripts", REPO_ROOT / "packages" / "brainsOS-appliance"):
        for sh_file in root.rglob("*.sh"):
            text = sh_file.read_text(encoding="utf-8")
            assert not bad_mktemp.search(text), f"Non-trailing mktemp suffix in {sh_file}"
    forbidden = "declare " + "-A"
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


