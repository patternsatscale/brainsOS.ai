"""Unit tests for B1 (Ticket #330): Quoting .env values containing whitespace in env-upsert.sh."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_UPSERT = REPO_ROOT / "scripts" / "control" / "env-upsert.sh"
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"


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
    shutil.copy2(ENV_UPSERT, root / "scripts" / "control")
    shutil.copy2(FIRSTBOOT, root / "packages" / "brainsOS-appliance" / "scripts")
    shutil.copy2(REPO_ROOT / ".env.example", root)
    _git(root, "init", "--quiet")
    return root


def _run_firstboot(root: Path) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BRAINSOS_")
    }
    env.update(
        {
            "BRAINSOS_REPO_ROOT": str(root),
            "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
            "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
            "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
        }
    )
    return subprocess.run(
        ["bash", str(root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_upsert_quotes_values_with_spaces(tmp_path: Path):
    """Values containing whitespace are single-quoted and bash-sourceable under set -e."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "BRAINSOS_IP_SITES=3.91.10.20 172.31.5.6"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert "BRAINSOS_IP_SITES='3.91.10.20 172.31.5.6'" in lines

    source_proc = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; set -a; . "$1"; printf %s "$BRAINSOS_IP_SITES"', "_", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert source_proc.returncode == 0, source_proc.stderr
    assert source_proc.stdout == "3.91.10.20 172.31.5.6"


def test_upsert_leaves_safe_values_unquoted(tmp_path: Path):
    """Safe values without whitespace or shell metacharacters remain unquoted."""
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=old\n", encoding="utf-8")

    proc = subprocess.run(
        [
            str(ENV_UPSERT),
            "--file",
            str(env_file),
            "KEY=sk-abc123",
            "URL=https://x.example/a",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert "KEY=sk-abc123" in lines
    assert "URL=https://x.example/a" in lines


def test_upsert_normalizes_prequoted_values_to_single_quotes(tmp_path: Path):
    """Caller-quoted values have outer quotes stripped and are POSIX single-quoted (#384)."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), 'X="a b"'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert "X='a b'" in lines


def test_upsert_neutralizes_double_quoted_command_substitution(tmp_path: Path):
    """Double-quoted $(...) or backtick payloads are single-quoted so sourcing .env never executes commands (#384)."""
    env_file = tmp_path / ".env"
    marker = tmp_path / "pwned_marker"
    env_file.write_text("A=1\n", encoding="utf-8")

    payload = f'BRAINSOS_UNIT_NAME="Unit $({{ touch {marker}; }} 2>/dev/null)"'
    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), payload],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    source_proc = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; set -a; . "$1"; printf %s "$BRAINSOS_UNIT_NAME"', "_", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert source_proc.returncode == 0, source_proc.stderr
    assert not marker.exists(), "Command substitution executed when sourcing .env!"
    assert "$(" in source_proc.stdout


def test_upsert_rejects_single_quote(tmp_path: Path):
    """Unquoted values containing a single quote are rejected without modifying the file."""
    env_file = tmp_path / ".env"
    original = b"A=1\n"
    env_file.write_bytes(original)

    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "X=it's"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "single quote" in proc.stderr
    assert env_file.read_bytes() == original


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not on PATH")
def test_compose_reads_quoted_value(tmp_path: Path):
    """docker compose reads single-quoted .env values written by env-upsert without quotes."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "V=a b"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        "services:\n  svc:\n    image: alpine\n    environment:\n      - V=${V}\n",
        encoding="utf-8",
    )

    cfg_proc = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cfg_proc.returncode == 0, cfg_proc.stderr
    data = json.loads(cfg_proc.stdout)
    assert data["services"]["svc"]["environment"]["V"] == "a b"


def test_firstboot_env_is_bash_sourceable(firstboot_tree: Path):
    """After firstboot.sh runs, the generated .env can be sourced in bash under set -euo pipefail."""
    proc = _run_firstboot(firstboot_tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    source_proc = subprocess.run(
        ["bash", "-c", "set -euo pipefail; set -a; . .env"],
        cwd=firstboot_tree,
        capture_output=True,
        text=True,
        check=False,
    )
    assert source_proc.returncode == 0, source_proc.stderr


@pytest.mark.parametrize(
    "payload",
    [
        "BRAINSOS_ZONE_NAME=ok\nINJECT=1",
        "BRAINSOS_ZONE_NAME=ok\rINJECT_CR=1",
        "BRAINSOS_ZONE_NAME=ok\r\nINJECT_CRLF=1",
        "BAD\nKEY=val",
        "BAD\rKEY=val",
        "# COMMENT=1\nINJECT=1",
    ],
)
def test_upsert_rejects_newline_and_cr_injection(tmp_path: Path, payload: str):
    """CLI KEY=VALUE pairs containing LF/CR in key or value are rejected atomically without splitting."""
    env_file = tmp_path / ".env"
    original = b"A=1\n"
    env_file.write_bytes(original)
    env_file.chmod(0o600)

    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), payload],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "INJECT" not in env_file.read_text(encoding="utf-8")
    assert env_file.read_bytes() == original


def test_upsert_from_file_rejects_cr_and_preserves_multiline_valid_entries(tmp_path: Path):
    """--from-file accepts normal multi-line files and rejects CR injection within a line."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")
    env_file.chmod(0o600)

    good_overrides = tmp_path / "good.env"
    good_overrides.write_text("# comment\nA=2\nB=hello world\n", encoding="utf-8")
    proc_ok = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "--from-file", str(good_overrides)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_ok.returncode == 0, proc_ok.stderr
    assert "A=2" in env_file.read_text(encoding="utf-8")
    assert "B='hello world'" in env_file.read_text(encoding="utf-8")

    bad_overrides = tmp_path / "bad.env"
    bad_overrides.write_bytes(b"BRAINSOS_ZONE_NAME=ok\rINJECT_FILE=1\n")
    before_bad = env_file.read_bytes()
    proc_bad = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "--from-file", str(bad_overrides)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bad.returncode != 0
    assert env_file.read_bytes() == before_bad

