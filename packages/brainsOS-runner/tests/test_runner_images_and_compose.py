"""Unit tests for runner SDK servers, Hermes WebUI auth, and brainsos-litellm-session (M3 F13-F15)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_mod(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hermes_webui_requires_runner_auth_token_and_escapes_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("RUNNER_AUTH_TOKEN", raising=False)

    webui = _load_mod("test_hermes_webui_m3", REPO_ROOT / "docker/runners/hermes/webui.py")
    client = TestClient(webui.app)

    # Fail closed 503 when RUNNER_AUTH_TOKEN is unset
    assert client.get("/").status_code == 503
    assert client.get("/api/config").status_code == 503
    assert client.post("/api/config", json={}).status_code == 503

    # 401 when missing or invalid token
    monkeypatch.setenv("RUNNER_AUTH_TOKEN", "webui-secret-tok")
    assert client.get("/").status_code == 401
    assert client.post("/api/config", json={}, headers={"X-Runner-Token": "wrong"}).status_code == 401

    # Valid token allows access and escapes XSS in config values
    (tmp_path / "config.yaml").write_text(
        'model:\n  default: \'x"><script>alert(1)</script>\'\n  base_url: "http://litellm:4000/v1"\n',
        encoding="utf-8",
    )
    res = client.get("/", headers={"X-Runner-Token": "webui-secret-tok"})
    assert res.status_code == 200
    assert "<script>alert(1)</script>" not in res.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in res.text
    assert "cdn.tailwindcss.com" not in res.text
    assert "fonts.googleapis.com" not in res.text


def test_runner_servers_support_litellm_api_key_and_cli_mode() -> None:
    for rel in (
        "docker/runners/hermes/server.py",
        "docker/runners/openai-sdk/server.py",
        "docker/runners/claude-sdk/server.py",
    ):
        txt = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "LITELLM_API_KEY" in txt
        assert "LITELLM_MASTER_KEY" not in txt
        assert 'if __name__ == "__main__":' in txt
        assert "BRAINSOS_REQUEST_FILE" in txt


def test_litellm_session_plugin_anchored_and_honors_pinned_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_providers = ModuleType("providers")
    fake_providers._REGISTRY = {}  # type: ignore[attr-defined]
    fake_providers.register_provider = lambda *a, **kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "providers", fake_providers)
    monkeypatch.setenv("ALICE_LITELLM_KEY", "sk-alice-1")
    monkeypatch.setenv("BOB_LITELLM_KEY", "sk-bob-2")

    mod = _load_mod(
        "test_litellm_session_m3",
        REPO_ROOT / "docker/hermes/plugins/model-providers/brainsos-litellm-session/__init__.py",
    )

    assert mod._resolve_agent_virtual_key("unmatched-session-xyz") is None
    assert mod._resolve_agent_virtual_key("chat-alice-thread-1") is None
    assert mod._resolve_agent_virtual_key("mail-bob-alice-thread-1") == "sk-bob-2"
    assert mod._resolve_agent_virtual_key("mail-alice-thread-1") == "sk-alice-1"

    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-pinned-alice")
    assert mod._resolve_agent_virtual_key("mail-bob-thread-1") == "sk-pinned-alice"


def test_hermes_webui_empty_hermes_home_falls_back_to_tmp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_HOME", "")
    webui = _load_mod("test_hermes_webui_empty_home", REPO_ROOT / "docker/runners/hermes/webui.py")
    assert webui.CONFIG_DIR == Path("/tmp/.hermes")


def test_caddyfile_and_compose_ingress_proxy_token_wiring() -> None:
    for cfg in ("config/caddy/Caddyfile", "config/caddy/Caddyfile.appliance"):
        txt = (REPO_ROOT / cfg).read_text(encoding="utf-8")
        assert "{$HERMES_DASHBOARD_PROXY_TOKEN:{$RUNNER_AUTH_TOKEN:}}" not in txt
        assert "header_up X-Hermes-Proxy-Token {$HERMES_DASHBOARD_PROXY_TOKEN:}" in txt
        assert "header_up X-Runner-Token {$RUNNER_AUTH_TOKEN:}" in txt

    ingress_yml = (REPO_ROOT / "docker/compose/compose.ingress.yml").read_text(encoding="utf-8")
    assert "RUNNER_AUTH_TOKEN=${RUNNER_AUTH_TOKEN:-}" in ingress_yml
    assert "HERMES_DASHBOARD_PROXY_TOKEN=${HERMES_DASHBOARD_PROXY_TOKEN:-${RUNNER_AUTH_TOKEN:-}}" in ingress_yml

    dockerfile_txt = (REPO_ROOT / "docker/hermes/Dockerfile").read_text(encoding="utf-8")
    assert "01-tool-egress-ca || true" not in dockerfile_txt


def test_01_tool_egress_ca_patcher_handles_fastapi_and_create_app_and_verifies_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import re
    import subprocess

    hook_txt = (REPO_ROOT / "docker/hermes/01-tool-egress-ca").read_text(encoding="utf-8")
    m = re.search(r"<< 'PYEOF'\n(.*?)\nPYEOF", hook_txt, re.DOTALL)
    assert m is not None
    patcher_src = m.group(1)

    # 1. Test against app = FastAPI(...) pattern
    fastapi_ws = tmp_path / "web_server_tail.py"
    fastapi_ws.write_text(
        "from __future__ import annotations\nfrom fastapi import FastAPI\n"
        "app = FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n",
        encoding="utf-8",
    )
    script_tail = patcher_src.replace('Path("/opt/hermes/hermes_cli/web_server.py")', f"Path({str(fastapi_ws)!r})")
    res_tail = subprocess.run([sys.executable, "-c", script_tail], capture_output=True, text=True, check=False)
    assert res_tail.returncode == 0, res_tail.stderr
    patched_tail = fastapi_ws.read_text(encoding="utf-8")
    assert patched_tail.startswith("from __future__ import annotations")
    assert "BRAINSOS_VERIFIED_PROXY_TOKEN_MIDDLEWARE" in patched_tail
    assert "_brainsos_attach_proxy_gate(app)" in patched_tail

    mod_tail = _load_mod("patched_ws_tail", fastapi_ws)
    tc = TestClient(mod_tail.app)

    monkeypatch.delenv("HERMES_DASHBOARD_PROXY_TOKEN", raising=False)
    monkeypatch.delenv("RUNNER_AUTH_TOKEN", raising=False)
    assert tc.get("/health").status_code == 503

    monkeypatch.setenv("RUNNER_AUTH_TOKEN", "runner-secret")
    assert tc.get("/health").status_code == 401
    # Unexpanded or empty X-Hermes-Proxy-Token must NOT shadow valid X-Runner-Token
    assert tc.get("/health", headers={"X-Hermes-Proxy-Token": "", "X-Runner-Token": "runner-secret"}).status_code == 200
    assert (
        tc.get(
            "/health", headers={"X-Hermes-Proxy-Token": "{$RUNNER_AUTH_TOKEN:}", "X-Runner-Token": "runner-secret"}
        ).status_code
        == 200
    )
    assert tc.get("/health", headers={"X-Hermes-Proxy-Token": "runner-secret"}).status_code == 200

    # Strict isolation when distinct HERMES_DASHBOARD_PROXY_TOKEN is configured
    monkeypatch.setenv("HERMES_DASHBOARD_PROXY_TOKEN", "dash-only-secret")
    assert tc.get("/health", headers={"X-Runner-Token": "runner-secret"}).status_code == 401
    assert tc.get("/health", headers={"X-Hermes-Proxy-Token": "dash-only-secret"}).status_code == 200

    # 2. Test create_app() pattern preserves `return app_state` and wraps `return app`
    create_app_ws = tmp_path / "web_server_factory.py"
    create_app_ws.write_text(
        "from fastapi import FastAPI\n"
        "def helper():\n    return app_state\n"
        "def create_app():\n    app = FastAPI()\n    return app\n",
        encoding="utf-8",
    )
    script_factory = patcher_src.replace(
        'Path("/opt/hermes/hermes_cli/web_server.py")', f"Path({str(create_app_ws)!r})"
    )
    res_factory = subprocess.run([sys.executable, "-c", script_factory], capture_output=True, text=True, check=False)
    assert res_factory.returncode == 0, res_factory.stderr
    factory_txt = create_app_ws.read_text(encoding="utf-8")
    assert "return app_state" in factory_txt
    assert "return _brainsos_attach_proxy_gate(app)" in factory_txt

    # 3. Unrecognized structure fails loudly
    bad_ws = tmp_path / "web_server_bad.py"
    bad_ws.write_text("print('not a fastapi app')\n", encoding="utf-8")
    script_bad = patcher_src.replace('Path("/opt/hermes/hermes_cli/web_server.py")', f"Path({str(bad_ws)!r})")
    res_bad = subprocess.run([sys.executable, "-c", script_bad], capture_output=True, text=True, check=False)
    assert res_bad.returncode != 0


def test_emergency_stop_does_not_false_match_hyphenated_sibling_container(tmp_path: Path) -> None:
    import os
    import subprocess

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    curl_log = tmp_path / "curl.log"

    (fake_bin / "docker").write_text(
        f"""#!/usr/bin/env bash
echo "docker $*" >> "{docker_log}"
if [ "$1" = "ps" ]; then
  if echo "$*" | grep -q "brainsos.tenant"; then
    exit 0
  fi
  echo "brainsos-agent-alice-bot"
  echo "brainsos-alice-bot"
  exit 0
fi
if [ "$1" = "inspect" ]; then
  echo "172.20.0.5"
  exit 0
fi
if [ "$1" = "pause" ] || [ "$1" = "stop" ]; then
  echo "No such container: $2" >&2
  exit 1
fi
exit 0
""",
        encoding="utf-8",
    )
    (fake_bin / "docker").chmod(0o755)

    (fake_bin / "curl").write_text(
        f"""#!/usr/bin/env bash
echo "curl $*" >> "{curl_log}"
if echo "$*" | grep -q "/health/liveness"; then
  exit 0
fi
echo "200"
exit 0
""",
        encoding="utf-8",
    )
    (fake_bin / "curl").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LITELLM_MASTER_KEY": "sk-master-test",
        "ALICE_LITELLM_KEY": "sk-alice-test",
    }
    res = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/control/emergency-stop.sh"), "alice"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, res.stderr
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert "docker pause brainsos-agent-alice" not in docker_calls
    assert "docker stop brainsos-agent-alice" not in docker_calls
    assert "docker pause brainsos-alice" not in docker_calls
    assert "docker stop brainsos-alice" not in docker_calls
    curl_calls = curl_log.read_text(encoding="utf-8")
    assert "/key/delete" in curl_calls and "sk-alice-test" in curl_calls

