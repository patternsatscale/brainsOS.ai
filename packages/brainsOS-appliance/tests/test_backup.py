"""Unit tests for B5 (Ticket #330): backup.sh --output-path-file contract."""

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "control" / "backup.sh"


def _hermetic_env(scratch: Path, bin_dir: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "BRAINSOS_DATA_DIR" and not (k.startswith("BRAINSOS_") and k.endswith("_DIR"))
    }
    env["BRAINSOS_REPO_ROOT"] = str(scratch)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return env


def test_backup_output_path_file_is_absolute_existing_archive(tmp_path: Path):
    """backup.sh --backup --output-path-file writes an existing absolute .tar.gz path."""
    scratch = tmp_path / "scratch"
    (scratch / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(BACKUP_SCRIPT, scratch / "scripts" / "control" / "backup.sh")
    (scratch / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")

    agent_dir = scratch / "data" / "agents" / "x"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SOUL.md").write_text("# Agent X\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    out_path_file = tmp_path / "p"
    env = _hermetic_env(scratch, bin_dir)

    proc = subprocess.run(
        ["bash", str(scratch / "scripts" / "control" / "backup.sh"), "--backup", "--output-path-file", str(out_path_file)],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_path_file.is_file()

    lines = [ln for ln in out_path_file.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) == 1
    archive_path = Path(lines[0])
    assert archive_path.is_absolute()
    assert archive_path.is_file()
    assert archive_path.name.endswith(".tar.gz")
    assert (archive_path.stat().st_mode & 0o777) == 0o600
    assert (archive_path.parent.stat().st_mode & 0o777) == 0o700


def test_backup_restore_uses_no_same_owner_and_umask_077(tmp_path: Path):
    """F24: backup.sh enforces umask 077 and tar --no-same-owner on restore."""
    script_txt = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert "umask 077" in script_txt
    assert "--no-same-owner" in script_txt

    scratch = tmp_path / "scratch"
    (scratch / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(BACKUP_SCRIPT, scratch / "scripts" / "control" / "backup.sh")
    (scratch / ".env").write_text("BRAINSOS_DATA_DIR=./data\n", encoding="utf-8")

    mem_dir = scratch / "data" / "agent_memories" / "alice"
    mem_dir.mkdir(parents=True)
    note = mem_dir / "NOTES.md"
    note.write_text("# Private Note\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    out_path_file = tmp_path / "backup_path"
    env = _hermetic_env(scratch, bin_dir)
    res_b = subprocess.run(
        ["bash", str(scratch / "scripts" / "control" / "backup.sh"), "--backup", "--output-path-file", str(out_path_file)],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_b.returncode == 0, res_b.stdout + res_b.stderr
    archive_path = Path(out_path_file.read_text(encoding="utf-8").strip())

    note.unlink()
    assert not note.exists()

    res_r = subprocess.run(
        ["bash", str(scratch / "scripts" / "control" / "backup.sh"), "--restore", str(archive_path), "--force"],
        cwd=scratch,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_r.returncode == 0, res_r.stdout + res_r.stderr
    assert note.read_text(encoding="utf-8") == "# Private Note\n"


