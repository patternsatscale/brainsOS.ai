"""Shared offline fixtures, factories, and opaque-box helpers for v0.5.3 RC2 E2E tests."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[4]

VALID_SIGNER_ARN = (
    "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/brainsos-alb/0123456789abcdef"
)
VALID_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool1"


def resolve_node_bin() -> str:
    found = shutil.which("node")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "node"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("node binary not found in PATH or ~/.local/bin/node")


def read_repo_text(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def load_yaml(rel_path: str) -> dict[str, Any]:
    data = yaml.safe_load(read_repo_text(rel_path))
    return data if isinstance(data, dict) else {}


def load_module_from_path(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None, f"Unable to load {file_path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_caddy_block(text: str, marker: str) -> str:
    """Extract a brace-balanced Caddyfile block starting at a line containing `marker`."""
    lines = text.splitlines()
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if marker in line and "{" in line:
            start_idx = idx
            break
    if start_idx is None:
        return ""
    depth = 0
    collected: list[str] = []
    for line in lines[start_idx:]:
        collected.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0 and len(collected) > 0:
            break
    return "\n".join(collected)


def find_unquoted_python_heredocs_with_expansion(script_text: str) -> list[tuple[int, str]]:
    """Return (line_no, tag) for unquoted python heredocs whose bodies contain `$` expansion."""
    lines = script_text.splitlines()
    findings: list[tuple[int, str]] = []
    header_re = re.compile(
        r"""(?:python3|\$\{?PYTHON_BIN\}?)\s+-\s*<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1"""
    )
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        m = header_re.search(line)
        if m:
            quote = m.group(1)
            tag = m.group(2)
            start_line = idx + 1
            body_lines: list[str] = []
            idx += 1
            while idx < len(lines) and lines[idx].strip() != tag:
                body_lines.append(lines[idx])
                idx += 1
            if not quote:
                body = "\n".join(body_lines)
                if "$" in body:
                    findings.append((start_line, tag))
        idx += 1
    return findings


@pytest.fixture(scope="session")
def ec_keypair() -> tuple[Any, str]:
    """Generate an ephemeral ES256 keypair for offline ALB OIDC JWT tests."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_key, public_pem


@pytest.fixture(scope="session")
def make_alb_jwt(ec_keypair: tuple[Any, str]) -> Callable[..., str]:
    private_key, _ = ec_keypair

    def _build(
        *,
        kid: str = "test-alb-key-id-0001",
        signer: str = VALID_SIGNER_ARN,
        alg: str = "ES256",
        sub: str = "sub-owner-1234",
        iss: str | None = VALID_ISSUER,
        exp: int | None = None,
        extra_claims: dict[str, Any] | None = None,
        extra_headers: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": sub,
            "exp": exp if exp is not None else now + 300,
            "email": "operator@brainsos.ai",
            "preferred_username": "operator",
        }
        if iss is not None:
            payload["iss"] = iss
        if extra_claims:
            payload.update(extra_claims)
        headers: dict[str, Any] = {"kid": kid, "signer": signer}
        if extra_headers:
            headers.update(extra_headers)
        if alg == "none":
            return jwt.encode(payload, "", algorithm="none", headers=headers)
        return jwt.encode(payload, private_key, algorithm=alg, headers=headers)

    return _build


@pytest.fixture
def isolated_repo(tmp_path: Path) -> Path:
    """Create an isolated temporary repository tree for offline script & API tests."""
    (tmp_path / "data" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "settings").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "control").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "setup").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "default_settings").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text(
        "BRAINSOS_STAGE=test\n"
        "BRAINSOS_DATA_DIR=./data\n"
        "BRAINSOS_DOMAIN=test.brainsos.ai\n"
        "BRAINSOS_LOCAL_DOMAIN=test.brainsos.ai\n"
        "SYSTEM_API_TOKEN=e2e-internal-token-12345\n",
        encoding="utf-8",
    )
    os.chmod(tmp_path / ".env", 0o600)
    return tmp_path


@pytest.fixture
def fake_bin_dir(tmp_path: Path) -> Path:
    """Create a directory for executable PATH shims in offline shell-script tests."""
    bdir = tmp_path / "fake_bin"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


@pytest.fixture
def system_api_client_factory(monkeypatch: pytest.MonkeyPatch):
    """Build an isolated FastAPI TestClient for `brainsos_telemetry.system`."""
    from brainsos_telemetry import system as sys_mod

    monkeypatch.setenv("BRAINSOS_STAGE", "test")
    monkeypatch.setenv("SYSTEM_API_TOKEN", "e2e-internal-token-12345")

    def _create(repo_root: Path, env_text: str | None = None, *, wizard_completed: bool = False) -> dict[str, Any]:
        if env_text is not None:
            (repo_root / ".env").write_text(env_text, encoding="utf-8")
            os.chmod(repo_root / ".env", 0o600)
        marker = repo_root / ".brainsos-wizard-completed"
        if wizard_completed:
            marker.write_text("2026-11-27T00:00:00Z\n", encoding="utf-8")
        elif marker.exists():
            marker.unlink()

        # Reset any module-level status TTL cache if implemented
        for cache_attr in ("_STATUS_CACHE", "_status_cache", "_SYSTEM_STATUS_CACHE"):
            cache_obj = getattr(sys_mod, cache_attr, None)
            if isinstance(cache_obj, dict):
                cache_obj.clear()

        patcher = patch("brainsos_telemetry.system.get_repo_root", return_value=str(repo_root))
        patcher.start()
        app = sys_mod.create_system_api_app()
        client = TestClient(app)
        csrf_tok = sys_mod.issue_csrf_token()
        client.cookies.set("brainsos_csrf_token", csrf_tok)
        return {
            "client": client,
            "csrf": csrf_tok,
            "internal_headers": {"X-BrainsOS-Internal": "e2e-internal-token-12345"},
            "admin_headers": {
                "X-BrainsOS-Internal": "e2e-internal-token-12345",
                "X-Authentik-Username": "su",
                "X-Authentik-Groups": "authentik Admins",
                "X-CSRF-Token": csrf_tok,
                "Origin": "http://localhost",
            },
            "viewer_headers": {
                "X-BrainsOS-Internal": "e2e-internal-token-12345",
                "X-Authentik-Username": "viewer",
                "X-Authentik-Groups": "brainsos-viewers",
                "X-CSRF-Token": csrf_tok,
                "Origin": "http://localhost",
            },
            "stop": patcher.stop,
        }

    created: list[dict[str, Any]] = []

    def _factory(repo_root: Path, env_text: str | None = None, *, wizard_completed: bool = False) -> dict[str, Any]:
        bundle = _create(repo_root, env_text, wizard_completed=wizard_completed)
        created.append(bundle)
        return bundle

    yield _factory

    for item in created:
        item["stop"]()


@pytest.fixture
def egress_addon_factory(monkeypatch: pytest.MonkeyPatch):
    """Load `config/egress/addons/github_auth.py` offline with minimal `mitmproxy` stub."""

    class FakeResponse:
        @staticmethod
        def make(status_code: int, content: bytes = b"", headers: dict[str, str] | None = None):
            return SimpleNamespace(status_code=status_code, content=content, headers=headers or {})

    fake_http = ModuleType("mitmproxy.http")
    fake_http.HTTPFlow = object  # type: ignore[attr-defined]
    fake_http.Response = FakeResponse  # type: ignore[attr-defined]
    fake_mitm = ModuleType("mitmproxy")
    fake_mitm.http = fake_http  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mitmproxy", fake_mitm)
    monkeypatch.setitem(sys.modules, "mitmproxy.http", fake_http)

    addon_path = REPO_ROOT / "config" / "egress" / "addons" / "github_auth.py"
    mod = load_module_from_path("e2e_github_auth", addon_path)

    def _create_addon(
        *,
        secrets_map: dict[str, str] | None = None,
        allowed_ips: set[str] | None = None,
        allow_private_hosts: list[str] | None = None,
    ):
        addon = mod.OpenBaoEgressAddon()
        addon._secrets_cache = dict(secrets_map or {"TAVILY_API_KEY": "tvly-secret-token-e2e", "GITHUB_TOKEN": "ghp_e2etoken123456"})
        addon._secrets_expires_at = 9999999999.0
        addon._allowed_ips = set(allowed_ips if allowed_ips is not None else {"172.22.0.10"})
        addon._last_dns_check = 9999999999.0
        if allow_private_hosts is not None:
            addon.allow_private_hosts = list(allow_private_hosts)
        return addon

    def _make_flow(
        host: str,
        *,
        pretty_host: str | None = None,
        scheme: str = "https",
        sni: str | None = None,
        client_ip: str = "172.22.0.10",
        peer_ip: str | None = "93.184.216.34",
        path: str = "/v1/search",
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ):
        p_host = host if pretty_host is None else pretty_host

        class _Flow:
            def __init__(self) -> None:
                self.killed = False
                self.response = None
                req = SimpleNamespace(
                    host=host,
                    pretty_host=p_host,
                    scheme=scheme,
                    path=path,
                    url=f"{scheme}://{p_host}{path}",
                    headers=dict(headers or {}),
                    content=content,
                )
                req.set_text = lambda txt: setattr(req, "content", txt.encode("utf-8"))
                self.request = req
                self.client_conn = SimpleNamespace(peername=(client_ip, 50000), address=(client_ip, 50000))
                self.server_conn = SimpleNamespace(
                    sni=sni,
                    address=(p_host, 443),
                    peername=(peer_ip, 443) if peer_ip is not None else None,
                )

            def kill(self) -> None:
                self.killed = True

        return _Flow()

    return mod, _create_addon, _make_flow


@pytest.fixture(scope="session")
def compiled_sanitizer_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile `infra/src/functions/sanitizer/*.ts` once per session for offline Node execution."""
    out_dir = tmp_path_factory.mktemp("sanitizer_js")
    tsc_bin = REPO_ROOT / "infra" / "node_modules" / ".bin" / "tsc"
    src_dir = REPO_ROOT / "infra" / "src" / "functions" / "sanitizer"
    res = subprocess.run(
        [
            str(tsc_bin),
            "--outDir",
            str(out_dir),
            "--rootDir",
            str(src_dir),
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            "--target",
            "ESNext",
            "--esModuleInterop",
            "--skipLibCheck",
            str(src_dir / "types.ts"),
            str(src_dir / "pipeline.ts"),
            str(src_dir / "handler.ts"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"tsc failed compiling sanitizer: {res.stderr}\n{res.stdout}"
    (out_dir / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    nm_link = out_dir / "node_modules"
    if not nm_link.exists():
        nm_link.symlink_to(REPO_ROOT / "infra" / "node_modules")
    return out_dir


@pytest.fixture(scope="session")
def run_node_sanitizer(compiled_sanitizer_dir: Path) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    node_bin = resolve_node_bin()

    def _run(script_body: str, payload: dict[str, Any]) -> dict[str, Any]:
        env = dict(os.environ)
        env["SANITIZER_OUT_DIR"] = str(compiled_sanitizer_dir)
        env["SANITIZER_INPUT"] = json.dumps(payload)
        res = subprocess.run(
            [node_bin, "--input-type=module", "-e", script_body],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert res.returncode == 0, f"Node sanitizer harness failed:\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}"
        return json.loads(res.stdout.strip().splitlines()[-1])

    return _run
