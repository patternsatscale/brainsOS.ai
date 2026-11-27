"""Unit and regression tests for SOGo nginx token rendering & ingress guard (#399)."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SOGO_ENTRYPOINT = REPO_ROOT / "docker" / "sogo" / "entrypoint.sh"
SOGO_NGINX_CONF = REPO_ROOT / "docker" / "sogo" / "nginx.conf"
COMPOSE_APPS = REPO_ROOT / "docker" / "compose" / "compose.apps.yml"


def _render_sogo_nginx(
    tmp_path: Path,
    *,
    template: Path = SOGO_NGINX_CONF,
    token: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    out_conf = tmp_path / "nginx-rendered.conf"
    env = os.environ.copy()
    if token is None:
        env.pop("CADDY_INGRESS_TOKEN", None)
    else:
        env["CADDY_INGRESS_TOKEN"] = token

    proc = subprocess.run(
        ["bash", str(SOGO_ENTRYPOINT), "--render-nginx-only", str(template), str(out_conf)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return proc, out_conf


def test_sogo_entrypoint_bash_syntax() -> None:
    """docker/sogo/entrypoint.sh passes bash -n syntax validation."""
    proc = subprocess.run(
        ["bash", "-n", str(SOGO_ENTRYPOINT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "bad_token",
    [
        None,
        "",
        "short123",
        "a" * 257,
        'foo"; return 200; #',
        "valid_prefix_123\nvalid_suffix_456",
        "__CADDY_INGRESS_TOKEN__",
        "prefix__CADDY_INGRESS_TOKEN__",
        "__CADDY_INGRESS_TOKEN__suffix",
        "aa__CADDY_INGRESS_TOKEN__bb",
    ],
)
def test_sogo_entrypoint_rejects_placeholder_and_invalid_tokens(
    tmp_path: Path, bad_token: str | None
) -> None:
    """Placeholder-bearing or invalid CADDY_INGRESS_TOKEN fails closed rapidly without hanging."""
    proc, out_conf = _render_sogo_nginx(tmp_path, token=bad_token)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "failing closed (403)" in proc.stderr

    rendered = out_conf.read_text(encoding="utf-8")
    assert "__CADDY_INGRESS_TOKEN__" not in rendered
    assert re.search(r'if \(\$http_x_caddy_ingress_token != "failclosed-[0-9a-f]{64}"\)', rendered)
    assert stat.S_IMODE(out_conf.stat().st_mode) == 0o600
    assert not (tmp_path / "nginx-rendered.conf.tmp").exists()


@pytest.mark.parametrize("token", ["Abc_123.def-456_7890", "a" * 64])
def test_sogo_entrypoint_renders_valid_token_and_preserves_file_mode(
    tmp_path: Path, token: str
) -> None:
    """Valid CADDY_INGRESS_TOKEN renders cleanly into nginx.conf with 0600 permissions."""
    proc, out_conf = _render_sogo_nginx(tmp_path, token=token)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "failing closed" not in proc.stderr

    rendered = out_conf.read_text(encoding="utf-8")
    assert "__CADDY_INGRESS_TOKEN__" not in rendered
    assert f'if ($http_x_caddy_ingress_token != "{token}")' in rendered
    assert stat.S_IMODE(out_conf.stat().st_mode) == 0o600


def test_sogo_entrypoint_awk_single_pass_cursor_advances(tmp_path: Path) -> None:
    """SOGo entrypoint uses single-pass cursor-advancing awk substitution and handles multi-placeholder lines."""
    script_txt = SOGO_ENTRYPOINT.read_text(encoding="utf-8")
    assert "*__CADDY_INGRESS_TOKEN__*" in script_txt
    assert "rest = substr(rest, idx + ph_len)" in script_txt
    assert "idx = index($0, ph)" not in script_txt

    synth = tmp_path / "template.conf"
    synth.write_text(
        "line1 __CADDY_INGRESS_TOKEN__ middle __CADDY_INGRESS_TOKEN__ end __CADDY_INGRESS_TOKEN__\n",
        encoding="utf-8",
    )
    tok = "valid_token_with_special_chars_123456"
    proc, out_conf = _render_sogo_nginx(tmp_path, template=synth, token=tok)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_conf.read_text(encoding="utf-8") == f"line1 {tok} middle {tok} end {tok}\n"


def test_sogo_compose_and_nginx_contract() -> None:
    """compose.apps.yml and nginx.conf maintain the X-Caddy-Ingress-Token contract."""
    compose_txt = COMPOSE_APPS.read_text(encoding="utf-8")
    assert "../../docker/sogo/entrypoint.sh:/entrypoint.sh:ro" in compose_txt
    assert "../../docker/sogo/nginx.conf:/etc/nginx/sites-available/default.template:ro" in compose_txt
    assert "CADDY_INGRESS_TOKEN=${CADDY_INGRESS_TOKEN:-}" in compose_txt

    nginx_txt = SOGO_NGINX_CONF.read_text(encoding="utf-8")
    assert 'if ($http_x_caddy_ingress_token = "")' in nginx_txt
    assert 'if ($http_x_caddy_ingress_token != "__CADDY_INGRESS_TOKEN__")' in nginx_txt
    assert "return 403;" in nginx_txt
