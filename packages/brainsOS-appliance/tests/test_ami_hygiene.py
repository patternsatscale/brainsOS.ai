"""AMI hygiene tests (Ticket #322): first-boot secret uniqueness, snapshot scan, staged build."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
PROVISION = REPO_ROOT / "packages" / "brainsOS-appliance" / "packer" / "provision.sh"
BUILD_AMI = REPO_ROOT / "scripts" / "control" / "build-ami.sh"

SECRET_KEY_RE = re.compile(r"(PASSWORD|SECRET|_KEY|TOKEN|SALT)", re.IGNORECASE)
COMPOSE_DEFAULT_RE = re.compile(r"\$\{([A-Z0-9_]+):?-([^}]*)\}")


def _parse_env(path: Path) -> dict:
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _compose_defaults() -> dict:
    """Collect every ${VAR:-default} fallback from the compose topology."""
    defaults: dict = {}
    files = [REPO_ROOT / "docker-compose.yml", *sorted((REPO_ROOT / "docker" / "compose").glob("*.yml"))]
    for compose_file in files:
        for var, default in COMPOSE_DEFAULT_RE.findall(compose_file.read_text(encoding="utf-8")):
            if default:
                defaults.setdefault(var, set()).add(default)
    return defaults


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@brainsos.ai", "-c", "user.name=test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def firstboot_tree(tmp_path: Path) -> Path:
    """Minimal repository subset needed by firstboot.sh + generate-env.sh."""
    root = tmp_path / "brainsos"
    (root / "scripts" / "control").mkdir(parents=True)
    (root / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "generate-env.sh", root / "scripts" / "control")
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "env-upsert.sh", root / "scripts" / "control")
    shutil.copy2(FIRSTBOOT, root / "packages" / "brainsOS-appliance" / "scripts")
    shutil.copy2(REPO_ROOT / ".env.example", root)
    _git(root, "init", "--quiet")
    return root


def _run_firstboot(root: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(root),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
    }
    return subprocess.run(
        ["bash", str(root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_firstboot_generates_unique_secrets_not_equal_to_compose_defaults(firstboot_tree: Path):
    proc = _run_firstboot(firstboot_tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    env_file = firstboot_tree / ".env"
    assert env_file.is_file()
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    values = _parse_env(env_file)

    # Appliance topology is carried by .env so every docker compose call inherits it
    assert values["COMPOSE_FILE"].endswith("docker/compose/compose.appliance.yml")
    assert values["LITELLM_CONFIG"].endswith("config/litellm/config.bedrock.yaml")
    assert values["OLLAMA_ENABLED"] == "false"
    assert values["BRAINSOS_APPLIANCE"] == "true"

    # No secret may fall back to (or equal) a hardcoded compose default
    collisions = []
    for var, defaults in _compose_defaults().items():
        if not SECRET_KEY_RE.search(var):
            continue
        value = values.get(var)
        if value is not None and value in defaults:
            collisions.append(var)
    assert not collisions, f"Secrets equal to compose defaults: {collisions}"

    # Secrets with compose fallbacks that are not in .env.example must be generated explicitly
    for var in ("CLICKHOUSE_PASSWORD", "AUTH_LITELLM_CLIENT_SECRET", "AUTH_LANGFUSE_CLIENT_SECRET"):
        assert values.get(var), f"{var} not generated"

    # The instance-id is only used for operator login; service passwords are independent
    operator_pw = values["BRAINSOS_ADMIN_PASSWORD"]
    for var in ("CODE_SERVER_PASSWORD", "TOOL_EGRESS_WEB_PASSWORD", "ADMIN_MAIL_PASSWORD",
                "LANGFUSE_INIT_USER_PASSWORD", "CLICKHOUSE_PASSWORD"):
        assert values[var] != operator_pw, f"{var} reuses the operator password"

    # Banner must not print the password value on any password line
    password_lines = [ln for ln in proc.stdout.splitlines() if "password" in ln.lower()]
    assert password_lines, "banner should explain the initial password"
    assert not any(operator_pw in ln for ln in password_lines)
    assert (firstboot_tree / ".brainsos-initialized").is_file()


def test_firstboot_secrets_differ_between_instances(firstboot_tree: Path, tmp_path: Path):
    second = tmp_path / "second"
    shutil.copytree(firstboot_tree, second)
    assert _run_firstboot(firstboot_tree).returncode == 0
    assert _run_firstboot(second).returncode == 0
    a, b = _parse_env(firstboot_tree / ".env"), _parse_env(second / ".env")
    for var in ("LITELLM_MASTER_KEY", "CLICKHOUSE_PASSWORD", "CODE_SERVER_PASSWORD"):
        if var in a:
            assert a[var] != b[var], f"{var} identical across instances"


def test_snapshot_scan_passes_clean_tree(tmp_path: Path):
    (tmp_path / "data" / "settings").mkdir(parents=True)
    (tmp_path / ".env.example").write_text("FOO=\n")
    proc = subprocess.run(
        ["bash", str(PROVISION), "--scan-only", "--app-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "relpath,content",
    [
        (".env.bak", "SECRET=1\n"),
        (".env", "SECRET=1\n"),
        ("data/settings/agents.yaml", "agents: []\n"),
        ("config/leak.txt", "key: sk-brainsos-" + "a" * 32 + "\n"),
        (".brainsos-initialized", "2026-01-01\n"),
    ],
)
def test_snapshot_scan_fails_closed(tmp_path: Path, relpath: str, content: str):
    target = tmp_path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    proc = subprocess.run(
        ["bash", str(PROVISION), "--scan-only", "--app-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 1, f"scan did not reject {relpath}"


@pytest.fixture()
def staged_repo(tmp_path: Path) -> Path:
    """Throwaway git repo carrying the build wrapper and appliance package, tagged v9.9.9."""
    root = tmp_path / "repo"
    (root / "scripts" / "control").mkdir(parents=True)
    (root / "config" / "litellm").mkdir(parents=True)
    shutil.copy2(BUILD_AMI, root / "scripts" / "control")
    shutil.copy2(REPO_ROOT / "config" / "litellm" / "config.bedrock.yaml", root / "config" / "litellm")
    shutil.copytree(
        REPO_ROOT / "packages" / "brainsOS-appliance",
        root / "packages" / "brainsOS-appliance",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", ".pytest_cache"),
    )
    (root / ".env.example").write_text("FOO=\n")
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "init")
    _git(root, "tag", "v9.9.9")
    # Untracked runtime secrets in the working tree must never reach the artifact
    (root / ".env").write_text("LITELLM_MASTER_KEY=sk-brainsos-" + "b" * 32 + "\n")
    return root


def _run_build(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": "/usr/bin:/bin"}  # no packer on PATH -> dry-run skips validate
    return subprocess.run(
        ["bash", str(root / "scripts" / "control" / "build-ami.sh"), *args],
        cwd=root, env=env, capture_output=True, text=True, check=False, timeout=120,
    )


def test_build_ami_refuses_dirty_tree(staged_repo: Path):
    proc = _run_build(staged_repo, "--dry-run")
    assert proc.returncode == 1
    assert "uncommitted changes" in proc.stderr


def test_build_ami_dry_run_stages_clean_artifact_from_latest_tag(staged_repo: Path):
    proc = _run_build(staged_repo, "--dry-run", "--allow-dirty")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "Git Ref:         v9.9.9" in out
    assert "Snapshot scan passed" in out
    assert "-var=brainsos_ref=v9.9.9" in out
    assert "-var=source_dir=" in out


def test_build_ami_scan_rejects_committed_secret(staged_repo: Path):
    (staged_repo / ".env.production").write_text("X=1\n")
    _git(staged_repo, "add", "-f", ".env.production")
    _git(staged_repo, "commit", "--quiet", "-m", "oops")
    proc = _run_build(staged_repo, "--dry-run", "--allow-dirty", "--ref", "HEAD")
    assert proc.returncode == 1
    assert "failed the snapshot scan" in proc.stderr


def test_build_ami_promote_dry_run_validates_ami_id(staged_repo: Path):
    assert _run_build(staged_repo, "--promote", "not-an-ami").returncode == 1
    proc = _run_build(staged_repo, "--promote", "ami-0123456789abcdef0", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Block Public Access" in proc.stdout
