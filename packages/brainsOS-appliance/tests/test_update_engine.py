"""Unit and regression tests for Ticket #324: Update Engine Appliance-Awareness, Version Targeting & Safe Rollback."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_SCRIPT = REPO_ROOT / "scripts" / "control" / "update.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "control" / "backup.sh"
ENV_UPSERT = REPO_ROOT / "scripts" / "control" / "env-upsert.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@brainsos.ai", "-c", "user.name=test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
def _ensure_repo_env():
    """Ensure REPO_ROOT/.env exists in CI runners where .env is not present."""
    env_file = REPO_ROOT / ".env"
    created = False
    if not env_file.exists():
        shutil.copy2(REPO_ROOT / ".env.example", env_file)
        created = True
    try:
        yield
    finally:
        if created and env_file.exists():
            env_file.unlink()


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> Path:
    """Disposable git repository that update.sh can run in safely via BRAINSOS_REPO_ROOT."""
    repo = tmp_path / "scratch_repo"
    (repo / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(UPDATE_SCRIPT, repo / "scripts" / "control")
    shutil.copy2(ENV_UPSERT, repo / "scripts" / "control")
    shutil.copy2(BACKUP_SCRIPT, repo / "scripts" / "control")
    shutil.copy2(REPO_ROOT / ".gitignore", repo / ".gitignore")
    _git(repo, "init", "--quiet", "--initial-branch=main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "init")
    (repo / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")
    return repo


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
    assert "docker compose pull --ignore-buildable litellm" in proc.stdout

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
    assert "docker compose pull --ignore-buildable langfuse-web langfuse-worker" in proc.stdout

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


def test_untracked_firstboot_artifacts_do_not_block_unattended_update(scratch_repo: Path):
    """Untracked first-boot files (.brainsos-initialized, data/agents/*) do not block unattended updates."""
    (scratch_repo / ".brainsos-initialized").write_text("2026-10-29\n", encoding="utf-8")
    agent_dir = scratch_repo / "data" / "agents" / "ping"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SOUL.md").write_text("# Ping\n", encoding="utf-8")

    env = {**os.environ, "BRAINSOS_REPO_ROOT": str(scratch_repo)}
    proc = subprocess.run(
        [str(scratch_repo / "scripts" / "control" / "update.sh"), "--unattended", "--full", "--dry-run", "--no-backup"],
        cwd=scratch_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dirty repository" not in proc.stderr


def test_tracked_modification_blocks_unattended_update(scratch_repo: Path):
    """Modifications to tracked files refuse unattended updates."""
    with open(scratch_repo / "scripts" / "control" / "env-upsert.sh", "a", encoding="utf-8") as fh:
        fh.write("\n# local edit\n")

    env = {**os.environ, "BRAINSOS_REPO_ROOT": str(scratch_repo)}
    proc = subprocess.run(
        [str(scratch_repo / "scripts" / "control" / "update.sh"), "--unattended", "--full", "--dry-run", "--no-backup"],
        cwd=scratch_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "dirty repository" in proc.stderr


def test_update_script_never_stashes():
    """Verify update.sh does not contain git stash logic."""
    text = UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "git stash" not in text


def test_firstboot_artifacts_are_gitignored():
    """Verify .brainsos-initialized and data/agents/x/SOUL.md are gitignored."""
    for relpath in (".brainsos-initialized", "data/agents/x/SOUL.md"):
        proc = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{relpath} is not gitignored"


def test_update_has_no_log_scraping_for_backup_path():
    """Verify update.sh uses --output-path-file and does not scrape backup stdout with tr -d ' '."""
    text = UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "--output-path-file" in text
    assert "tr -d ' '" not in text


def test_rollback_uses_reset_keep_not_checkout():
    """Verify rollback_handler uses git reset --keep and not git checkout PRE_UPDATE_GIT_REF."""
    text = UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert "git reset --keep" in text
    assert 'git checkout "${PRE_UPDATE_GIT_REF}"' not in text


def test_rollback_skips_db_restore_when_no_containers_changed(scratch_repo: Path, tmp_path: Path):
    """When update fails during pull before any containers are recreated, rollback skips DB restore."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{docker_log}"
for arg in "$@"; do
  if [ "$arg" = "pull" ]; then
    exit 1
  fi
done
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    dummy_tarball = tmp_path / "dummy_backup.tar.gz"
    dummy_tarball.write_bytes(b"dummy")
    backup_log = tmp_path / "backup.log"
    stub_backup = scratch_repo / "scripts" / "control" / "backup.sh"
    stub_backup.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
while [ $# -gt 0 ]; do
  case "$1" in
    --output-path-file)
      printf '%s\\n' "{dummy_tarball}" > "$2"
      shift 2
      ;;
    --restore)
      printf 'RESTORE %s\\n' "$2" >> "{backup_log}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
""",
        encoding="utf-8",
    )
    stub_backup.chmod(0o755)
    _git(scratch_repo, "add", "-A")
    _git(scratch_repo, "commit", "--quiet", "-m", "stub backup")

    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(scratch_repo),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    proc = subprocess.run(
        [str(scratch_repo / "scripts" / "control" / "update.sh"), "--unattended", "--containers-only"],
        cwd=scratch_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "skipping database restore" in combined
    assert not backup_log.exists() or "RESTORE" not in backup_log.read_text(encoding="utf-8")


def test_every_compose_pull_ignores_buildable():
    """Every non-comment docker compose pull line in update.sh must include --ignore-buildable."""
    lines = UPDATE_SCRIPT.read_text(encoding="utf-8").splitlines()
    pull_lines = [
        ln for ln in lines
        if "docker compose pull" in ln and not ln.lstrip().startswith("#")
    ]
    assert pull_lines, "Expected at least one docker compose pull line in update.sh"
    for ln in pull_lines:
        assert "--ignore-buildable" in ln, f"Missing --ignore-buildable in: {ln}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not on PATH")
def test_targeted_buildable_service_is_rebuilt(tmp_path: Path):
    """Targeting a locally built service (caddy) pulls with --ignore-buildable and rebuilds it."""
    real_docker = shutil.which("docker")
    assert real_docker is not None

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
for arg in "$@"; do
  if [ "$arg" = "config" ]; then
    exec "{real_docker}" "$@"
  fi
done
printf '%s\\n' "$*" >> "{docker_log}"
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    # Also shim curl so health check fails deterministically even if Caddy is running on host
    fake_curl = bin_dir / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    subprocess.run(
        [str(UPDATE_SCRIPT), "--service", "caddy", "--unattended", "--no-backup", "--health-timeout", "1"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    log_text = docker_log.read_text(encoding="utf-8")
    assert "compose pull --ignore-buildable caddy" in log_text
    assert "compose build caddy" in log_text


def test_version_rejected_for_caddy():
    """--version is rejected for locally built caddy service."""
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--service", "caddy", "--version", "2.8", "--dry-run", "--unattended"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "not supported" in proc.stderr


def test_shallow_clone_unshallows_and_reports_zero_commits_behind(tmp_path: Path):
    """Shallow repo staged with --depth 1 ahead of origin/main unshallows and reports 0 commits behind."""
    origin_repo = tmp_path / "origin_repo"
    origin_repo.mkdir()
    _git(origin_repo, "init", "--quiet", "--initial-branch=main")
    for idx in range(5):
        (origin_repo / f"f{idx}.txt").write_text(f"{idx}\n", encoding="utf-8")
        _git(origin_repo, "add", "-A")
        _git(origin_repo, "commit", "--quiet", "-m", f"commit {idx}")

    # Create a rehearsal branch 1 commit ahead of main
    _git(origin_repo, "checkout", "--quiet", "-b", "task/rehearsal")
    (origin_repo / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(UPDATE_SCRIPT, origin_repo / "scripts" / "control")
    shutil.copy2(ENV_UPSERT, origin_repo / "scripts" / "control")
    shutil.copy2(BACKUP_SCRIPT, origin_repo / "scripts" / "control")
    shutil.copy2(REPO_ROOT / ".gitignore", origin_repo / ".gitignore")
    _git(origin_repo, "add", "-A")
    _git(origin_repo, "commit", "--quiet", "-m", "rehearsal commit")
    rehearsal_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=origin_repo, text=True).strip()
    _git(origin_repo, "checkout", "--quiet", "main")

    # Stage shallow clone of rehearsal_sha checked out as main
    staged = tmp_path / "staged"
    staged.mkdir()
    _git(staged, "init", "--quiet", "--initial-branch=main")
    _git(staged, "fetch", "--quiet", "--depth", "1", f"file://{origin_repo}", rehearsal_sha)
    _git(staged, "checkout", "--quiet", "-B", "main", "FETCH_HEAD")
    _git(staged, "remote", "add", "origin", f"file://{origin_repo}")
    (staged / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")

    env = {**os.environ, "BRAINSOS_REPO_ROOT": str(staged)}
    proc = subprocess.run(
        [str(staged / "scripts" / "control" / "update.sh"), "--check", "--json"],
        cwd=staged,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["git"]["commits_behind"] == 0
    assert data["git"]["update_available"] is False
    assert "main" in data["git"]["available_branches"]
    assert "task/rehearsal" in data["git"]["available_branches"]


def test_update_branch_selection_dry_run():
    """Verify --branch <name> --dry-run plans branch switch and pull from origin/<branch>."""
    proc = subprocess.run(
        [str(UPDATE_SCRIPT), "--branch", "task/320-appliance-rehearsal", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "task/320-appliance-rehearsal" in proc.stdout
    assert "origin/task/320-appliance-rehearsal" in proc.stdout






