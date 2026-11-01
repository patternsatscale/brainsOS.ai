"""Unit tests for B6 (Ticket #330): IMDS container isolation guard (scripts/setup/imds-guard.sh)."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
IMDS_GUARD = REPO_ROOT / "scripts" / "setup" / "imds-guard.sh"
BRAINSOS_SERVICE = REPO_ROOT / "packages" / "brainsOS-appliance" / "configs" / "brainsos.service"


def _make_shims(
    bin_dir: Path,
    ipt_log: Path,
    docker_output: str = "",
    check_exit: int = 1,
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)

    uname_shim = bin_dir / "uname"
    uname_shim.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
    uname_shim.chmod(0o755)

    docker_shim = bin_dir / "docker"
    docker_shim.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{docker_output}'\n",
        encoding="utf-8",
    )
    docker_shim.chmod(0o755)

    ipt_shim = bin_dir / "iptables"
    ipt_shim.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{ipt_log}"
for arg in "$@"; do
  if [ "$arg" = "-C" ]; then
    exit {check_exit}
  fi
done
exit 0
""",
        encoding="utf-8",
    )
    ipt_shim.chmod(0o755)


def test_noop_on_non_appliance(tmp_path: Path):
    """Without BRAINSOS_APPLIANCE=true, imds-guard.sh exits 0, logs not applicable, and invokes no iptables."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    env.pop("BRAINSOS_APPLIANCE", None)

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "not applicable" in proc.stdout
    assert not ipt_log.exists() or ipt_log.read_text(encoding="utf-8") == ""


def test_apply_allows_litellm_and_drops_rest(tmp_path: Path):
    """With LiteLLM container IPs present, BRAINSOS-IMDS allows each IP with RETURN, ends with DROP, and inserts into DOCKER-USER."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="172.20.0.5 172.21.0.7 ", check_exit=1)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [
        ln.removeprefix("iptables ")
        for ln in proc.stdout.splitlines()
        if ln.startswith("iptables ")
    ]
    expected_sequence = [
        "-F BRAINSOS-IMDS",
        "-A BRAINSOS-IMDS -s 172.20.0.5/32 -j RETURN",
        "-A BRAINSOS-IMDS -s 172.21.0.7/32 -j RETURN",
        "-A BRAINSOS-IMDS -j DROP",
    ]
    indices = [lines.index(cmd) for cmd in expected_sequence]
    assert indices == sorted(indices)
    assert any(
        "DOCKER-USER" in ln and "-d 169.254.169.254/32 -j BRAINSOS-IMDS" in ln and "-I" in ln
        for ln in lines
    )


def test_apply_fails_closed_without_litellm(tmp_path: Path):
    """When LiteLLM is not running (no IPs), BRAINSOS-IMDS contains only -j DROP."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="", check_exit=1)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    chain_rules = [
        ln.removeprefix("iptables ")
        for ln in proc.stdout.splitlines()
        if ln.startswith("iptables -A BRAINSOS-IMDS")
    ]
    assert chain_rules == ["-A BRAINSOS-IMDS -j DROP"]


def test_apply_is_idempotent(tmp_path: Path):
    """When iptables -C exits 0, no second -I DOCKER-USER is issued."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="172.20.0.5 ", check_exit=0)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "-I DOCKER-USER" not in proc.stdout


def test_brainsos_service_applies_guard():
    """brainsos.service includes ExecStartPost=/opt/brainsos/scripts/setup/imds-guard.sh --apply."""
    content = BRAINSOS_SERVICE.read_text(encoding="utf-8")
    assert "ExecStartPost=/opt/brainsos/scripts/setup/imds-guard.sh --apply" in content

