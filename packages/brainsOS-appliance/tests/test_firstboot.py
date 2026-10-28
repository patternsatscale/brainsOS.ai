"""Tests for appliance first-boot cloud-init logic and inspector functions."""

import subprocess
from pathlib import Path

from brainsos_appliance.inspector import (
    audit_host_hardening,
    inspect_firstboot_status,
    query_imdsv2_metadata,
)


def test_firstboot_script_dry_run():
    """Verify firstboot.sh executes successfully in dry-run mode."""
    repo_root = Path(__file__).resolve().parents[3]
    firstboot_script = repo_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
    assert firstboot_script.is_file()

    proc = subprocess.run(
        [str(firstboot_script), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "[DRY-RUN] BRAINSOS_ADMIN_PASSWORD=" in proc.stdout
    assert "[DRY-RUN] BRAINSOS_DOMAIN=" in proc.stdout


def test_firstboot_script_check_mode():
    """Verify firstboot.sh --check returns exit code reflecting init status."""
    repo_root = Path(__file__).resolve().parents[3]
    firstboot_script = repo_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"

    proc = subprocess.run(
        [str(firstboot_script), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    # If .brainsos-initialized does not exist yet, code is 1
    init_flag = repo_root / ".brainsos-initialized"
    expected_code = 0 if init_flag.exists() else 1
    assert proc.returncode == expected_code


def test_inspect_firstboot_status():
    """Verify status inspector returns expected schema."""
    status = inspect_firstboot_status()
    assert isinstance(status, dict)
    assert "initialized" in status
    assert "env_file_exists" in status
    assert "env_permissions" in status
    assert "env_permissions_secure" in status


def test_query_imdsv2_metadata_non_ec2():
    """Verify imds query behaves cleanly in local non-EC2 environments."""
    imds = query_imdsv2_metadata(timeout=0.2)
    assert isinstance(imds, dict)
    assert "imds_available" in imds
    assert imds["imds_available"] is False


def test_audit_host_hardening():
    """Verify host hardening auditor returns expected keys."""
    audit = audit_host_hardening()
    assert isinstance(audit, dict)
    assert "docker_daemon_logging" in audit
    assert "journald_dropin_present" in audit
    assert "logrotate_present" in audit
    assert "ufw" in audit
