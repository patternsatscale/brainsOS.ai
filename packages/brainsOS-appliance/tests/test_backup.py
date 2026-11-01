"""Unit tests for B5 (Ticket #330): backup.sh --output-path-file contract."""

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "control" / "backup.sh"


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
    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(scratch),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

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

