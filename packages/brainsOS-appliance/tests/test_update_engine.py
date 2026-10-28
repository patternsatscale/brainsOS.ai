"""Unit and regression tests for Ticket #324: Update Engine Appliance-Awareness, Version Targeting & Safe Rollback."""

import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "scripts" / "control" / "update.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "control" / "backup.sh"


def test_update_requires_env_file(tmp_path: Path):
    """Verify update.sh exits with code 1 if .env is missing (Rule 13)."""
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "scripts" / "control").mkdir(parents=True)

    env = os.environ.copy()
    env["BRAINSOS_REPO_ROOT"] = str(fake_repo)

    # Run in directory with no .env
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--check"],
        cwd=fake_repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    assert "Rule 13" in proc.stderr or "Missing .env" in proc.stderr


def test_backup_requires_env_file(tmp_path: Path):
    """Verify backup.sh exits with code 1 if .env is missing (Rule 13)."""
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "scripts" / "control").mkdir(parents=True)

    env = os.environ.copy()
    env["BRAINSOS_REPO_ROOT"] = str(fake_repo)

    proc = subprocess.run(
        [str(BACKUP_SCRIPT), "--backup"],
        cwd=fake_repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    assert "Rule 13" in proc.stderr or "Missing .env" in proc.stderr


def test_update_check_json_reports_clean_semver():
    """Verify update.sh --check --json reports clean semvers without interpolation artifacts."""
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--check", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "platform" in data
    assert "services" in data

    services = data["services"]
    assert "litellm" in services
    assert "langfuse" in services
    assert "caddy" in services
    assert "runner-hermes" in services

    litellm_ver = services["litellm"]["current_version"]
    langfuse_ver = services["langfuse"]["current_version"]
    caddy_ver = services["caddy"]["current_version"]
    hermes_ver = services["runner-hermes"]["current_version"]

    # Verify no raw bash expansion artifacts like "-v1.105.0}"
    assert "}" not in litellm_ver
    assert "{" not in litellm_ver
    assert "$" not in litellm_ver
    assert re.match(r"^[0-9]+\.[0-9]+(\.[0-9]+)?", litellm_ver)

    assert "}" not in langfuse_ver
    assert "{" not in langfuse_ver
    assert re.match(r"^[0-9]+\.[0-9]+(\.[0-9]+)?", langfuse_ver)

    assert caddy_ver in ("local build", "2.8.4") or re.match(r"^[0-9]+", caddy_ver)
    assert hermes_ver in ("local build", "1.0.0") or re.match(r"^[0-9]+", hermes_ver)


def test_update_version_targeting_dry_run():
    """Verify --service <name> --version <tag> --dry-run plans correct env overrides."""
    # 1. LiteLLM targeting
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--service", "litellm", "--version", "1.106.0", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Would set LITELLM_IMAGE_TAG=v1.106.0 in .env" in proc.stdout
    assert "docker compose pull litellm" in proc.stdout

    # 2. Langfuse targeting
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--service", "langfuse", "--version", "4.60.0", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Would set LANGFUSE_IMAGE_TAG=4.60.0 in .env" in proc.stdout
    assert "docker compose pull langfuse-web langfuse-worker" in proc.stdout

    # 3. Reset version override
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--service", "litellm", "--reset", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Would unset LITELLM_IMAGE_TAG in .env to restore default image tag" in proc.stdout


def test_appliance_compose_overlay_port_lockdown_with_update():
    """Regression test (Audit #12): With appliance overlay, update.sh never exposes internal ports."""
    env = os.environ.copy()
    env["COMPOSE_FILE"] = f"{REPO_ROOT}/docker-compose.yml:{REPO_ROOT}/docker/compose/compose.appliance.yml"

    proc = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    cfg = json.loads(proc.stdout)
    services = cfg.get("services", {})

    published_ports = []
    for svc_name, svc_cfg in services.items():
        for port in svc_cfg.get("ports", []):
            if isinstance(port, dict):
                published = port.get("published")
                if published:
                    published_ports.append((svc_name, str(published)))
            elif isinstance(port, str):
                parts = port.split(":")
                if len(parts) >= 2:
                    published_ports.append((svc_name, parts[0]))

    # Only caddy should have published ports (80, 443)
    non_caddy_published = [p for p in published_ports if p[0] != "caddy"]
    assert non_caddy_published == [], f"Unexpected exposed ports in appliance mode: {non_caddy_published}"


def test_update_unattended_rejects_dirty_repo():
    """Verify update.sh -y refuses to run unattended on a dirty repo (Audit #18)."""
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "-y", "--full"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # If the working tree has edits, it must refuse to run unattended
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        assert proc.returncode != 0
        assert "Refusing to run unattended update on a dirty repository" in proc.stderr

