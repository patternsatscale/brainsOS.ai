"""Integration and security boundary tests for Ticket #375 (LiteLLM Lens v0.5.2 & Shared ClickHouse KeeperMap)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_TELEMETRY = REPO_ROOT / "docker" / "compose" / "compose.telemetry.yml"
COMPOSE_CONTROL = REPO_ROOT / "docker" / "compose" / "compose.control.yml"
COMPOSE_AGENTS = REPO_ROOT / "docker" / "compose" / "compose.agents.yml"
COMPOSE_APPLIANCE = REPO_ROOT / "docker" / "compose" / "compose.appliance.yml"
CADDYFILE = REPO_ROOT / "config" / "caddy" / "Caddyfile"
CADDYFILE_APPLIANCE = REPO_ROOT / "config" / "caddy" / "Caddyfile.appliance"
KEEPER_XML = REPO_ROOT / "config" / "clickhouse" / "lens-keeper.xml"
LENS_DOCKERFILE = REPO_ROOT / "docker" / "lens" / "Dockerfile"
GENERATE_ENV = REPO_ROOT / "scripts" / "control" / "generate-env.sh"
SETUP_LENS = REPO_ROOT / "scripts" / "setup" / "setup-lens.sh"


def test_compose_telemetry_defines_hardened_lens_and_clickhouse_keeper() -> None:
    """Verify compose.telemetry.yml defines rootless hardened lens and mounts ClickHouse Keeper config."""
    data = yaml.safe_load(COMPOSE_TELEMETRY.read_text(encoding="utf-8"))
    services = data["services"]
    assert "lens" in services
    assert "clickhouse" in services

    ch = services["clickhouse"]
    ch_env = "\n".join(ch.get("environment", []))
    ch_vols = "\n".join(ch.get("volumes", []))
    assert ch["image"] == "clickhouse/clickhouse-server:26.2"
    assert "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1" in ch_env
    assert "config/clickhouse/lens-keeper.xml:/etc/clickhouse-server/config.d/lens-keeper.xml:ro" in ch_vols

    lens = services["lens"]
    lens_env = "\n".join(lens.get("environment", []))
    assert lens["container_name"] == "brainsos-telemetry-lens"
    assert lens["user"] == "65532:65532"
    assert lens["read_only"] is True
    assert "ALL" in lens["cap_drop"]
    assert "no-new-privileges:true" in lens["security_opt"]
    assert "127.0.0.1:${LENS_PORT:-4318}:4318" in lens["ports"]
    assert "LENS_GATEWAY_URL=${LENS_GATEWAY_URL:-http://litellm:4000}" in lens_env
    assert "LENS_GATEWAY_API_BASE=${LENS_GATEWAY_API_BASE:-http://litellm:4000}" in lens_env

    networks = lens["networks"]
    assert "brainsos-telemetry-net" in networks
    assert "brainsos-internal-net" in networks
    assert "brainsos-ingress-net" in networks
    # Strict Control Plane Isolation (Rule 6): lens never attaches to brainsos-control-net
    assert "brainsos-control-net" not in networks


def test_compose_control_bumps_litellm_1_109_1_and_wires_lens() -> None:
    """Verify compose.control.yml pins LiteLLM v1.109.1 and wires LITELLM_LENS_* variables."""
    data = yaml.safe_load(COMPOSE_CONTROL.read_text(encoding="utf-8"))
    litellm = data["services"]["litellm"]
    env_joined = "\n".join(litellm["environment"])
    assert "v1.109.1" in litellm["image"]
    assert "LANGFUSE_ENABLED=${LANGFUSE_ENABLED:-true}" in env_joined
    assert "LITELLM_LENS_URL=${LITELLM_LENS_URL:-http://lens:4318}" in env_joined
    assert "LITELLM_LENS_PUBLIC_URL=" in env_joined
    assert "LITELLM_LENS_SERVICE_TOKEN=${LITELLM_LENS_SERVICE_TOKEN:-" in env_joined
    assert "LENS_GATEWAY_SECRET=${LENS_GATEWAY_SECRET:-" in env_joined


def test_compose_appliance_resets_lens_ports() -> None:
    """Verify compose.appliance.yml resets lens host port bindings for Single-Origin Port 443."""
    raw = COMPOSE_APPLIANCE.read_text(encoding="utf-8")
    assert "lens:\n    ports: !reset []" in raw


def test_lens_dockerfile_pins_immutable_commit_and_rootless_user() -> None:
    """Verify docker/lens/Dockerfile pins immutable BerriAI/lens commit and runs as 65532:65532."""
    raw = LENS_DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG LENS_GIT_COMMIT=fa1b82f6ad67c63e82b949d73f0ea50914397dd5" in raw
    assert "USER 65532:65532" in raw
    assert 'ENTRYPOINT ["/usr/local/bin/node", "/app/agent-chat/dist/supervisor.js"]' in raw
    assert KEEPER_XML.is_file()
    assert "<keeper_map_path_prefix>/lens/keeper-map</keeper_map_path_prefix>" in KEEPER_XML.read_text(encoding="utf-8")


def test_caddyfiles_route_lens_ui_api_and_scoped_otlp_ingest() -> None:
    """Verify Caddyfile and Caddyfile.appliance route /lens* to litellm:4000 and /lens-ingest/v1/{traces,logs} to lens:4318 without exposing /internal/*."""
    for caddy_path in (CADDYFILE, CADDYFILE_APPLIANCE):
        content = caddy_path.read_text(encoding="utf-8")
        assert "@lens_ingest path /lens-ingest/v1/traces /lens-ingest/v1/logs" in content
        assert "handle @lens_ingest {" in content
        assert "uri strip_prefix /lens-ingest" in content
        assert "reverse_proxy {$LENS_UPSTREAM:lens:4318}" in content
        assert "/lens /lens/*" in content
        assert "/lens-ingest/internal" not in content


def test_generate_env_populates_lens_secrets_and_litellm_1_109_1(tmp_path: Path) -> None:
    """Verify generate-env.sh generates unique 64-char hex Lens tokens and pins v1.109.1."""
    out_env = tmp_path / ".env.generated"
    proc = subprocess.run(
        [
            str(GENERATE_ENV),
            "--non-interactive",
            "--no-rebuild",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "BRAINSOS_ENV_FILE": str(out_env),
            "BRAINSOS_DATA_DIR": str(tmp_path / "data"),
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_env.is_file()

    kv: dict[str, str] = {}
    for line in out_env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")

    assert kv.get("LITELLM_IMAGE_TAG") == "v1.109.1"
    assert kv.get("LANGFUSE_ENABLED") == "true"
    assert kv.get("LENS_ENABLED") == "true"
    for token_key in ("LENS_ADMIN_TOKEN", "LENS_GATEWAY_SECRET", "LITELLM_LENS_SERVICE_TOKEN"):
        val = kv.get(token_key, "")
        assert len(val) == 64 and all(c in "0123456789abcdef" for c in val), f"Invalid {token_key}"
    assert len({kv["LENS_ADMIN_TOKEN"], kv["LENS_GATEWAY_SECRET"], kv["LITELLM_LENS_SERVICE_TOKEN"]}) == 3
    assert len(kv.get("LENS_CLICKHOUSE_PASSWORD", "")) >= 32
    assert SETUP_LENS.is_file() and os.access(SETUP_LENS, os.X_OK)
