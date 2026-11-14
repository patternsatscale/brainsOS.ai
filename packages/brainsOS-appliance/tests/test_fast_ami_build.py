"""Tests for Fast Incremental Golden AMI Builder & gp3 Throughput Tuning (Ticket #374)."""

import os
import subprocess
from pathlib import Path

from brainsos_appliance.builder import build_ami_command, get_build_script, get_packer_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRSTBOOT_SH = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
PROVISION_SH = REPO_ROOT / "packages" / "brainsOS-appliance" / "packer" / "provision.sh"


def test_packer_incremental_and_gp3_throughput_invariants():
    """Verify source_ami parameterization, gp3 500 MB/s / 4000 IOPS, and runtime firstboot masking."""
    packer_dir = get_packer_dir()
    hcl = (packer_dir / "brainsos-ami.pkr.hcl").read_text()
    vars_hcl = (packer_dir / "variables.pkr.hcl").read_text()

    assert 'variable "volume_throughput"' in vars_hcl
    assert "default     = 500" in vars_hcl
    assert 'variable "volume_iops"' in vars_hcl
    assert "default     = 4000" in vars_hcl
    assert 'variable "source_ami"' in vars_hcl
    assert 'variable "incremental_build"' in vars_hcl

    assert 'source_ami = var.source_ami != "" ? var.source_ami : null' in hcl
    assert 'dynamic "source_ami_filter"' in hcl
    assert "throughput            = var.volume_throughput" in hcl
    assert "iops                  = var.volume_iops" in hcl
    assert "BRAINSOS_PACKER_BUILD=true" in hcl
    assert "systemctl mask --runtime brainsos-firstboot.service" in hcl
    assert "BRAINSOS_INCREMENTAL_BUILD=${var.incremental_build}" in hcl


def test_build_ami_validate_only():
    """Verify scripts/control/build-ami.sh --validate-only succeeds."""
    proc = subprocess.run(
        [str(get_build_script()), "--validate-only"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "Validation complete (--validate-only)" in proc.stdout


def test_build_ami_dry_run_with_explicit_from_ami():
    """Verify --from-ami sets source_ami, incremental_build=true, and gp3 throughput/iops vars."""
    proc = subprocess.run(
        [
            str(get_build_script()),
            "--dry-run",
            "--allow-dirty",
            "--ref",
            "HEAD",
            "--from-ami",
            "ami-0eac84eb9a9415531",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "-var=source_ami=ami-0eac84eb9a9415531" in proc.stdout
    assert "-var=incremental_build=true" in proc.stdout
    assert "-var=volume_throughput=500" in proc.stdout
    assert "-var=volume_iops=4000" in proc.stdout
    assert "incremental (base: ami-0eac84eb9a9415531)" in proc.stdout


def test_build_ami_rejects_malformed_from_ami():
    """Verify --from-ami rejects invalid AMI identifiers."""
    proc = subprocess.run(
        [
            str(get_build_script()),
            "--dry-run",
            "--allow-dirty",
            "--ref",
            "HEAD",
            "--from-ami",
            "invalid-ami-id",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Invalid --from-ami ID" in proc.stderr


def test_build_ami_incremental_auto_selects_latest_self_ami(tmp_path):
    """Verify --incremental queries AWS EC2 for the newest self-owned brainsos-* ARM64 AMI."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"describe-images"* ]]; then\n'
        '  printf "ami-0eac84eb9a9415531\\tbrainsos-v0.1.5-arm64-rc6\\n"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    fake_aws.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    proc = subprocess.run(
        [
            str(get_build_script()),
            "--dry-run",
            "--allow-dirty",
            "--ref",
            "HEAD",
            "--incremental",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "Auto-selected incremental base AMI: ami-0eac84eb9a9415531" in proc.stdout
    assert "-var=source_ami=ami-0eac84eb9a9415531" in proc.stdout
    assert "-var=incremental_build=true" in proc.stdout


def test_python_builder_cli_incremental_flags():
    """Verify brainsos_appliance.builder composes --from-ami and --incremental cleanly."""
    cmd_from = build_ami_command(
        region="us-east-1",
        ref="v0.5.1",
        from_ami="ami-0eac84eb9a9415531",
        dry_run=True,
    )
    assert "--from-ami" in cmd_from
    assert "ami-0eac84eb9a9415531" in cmd_from

    cmd_inc = build_ami_command(
        region="us-east-1",
        ref="v0.5.1",
        incremental=True,
        dry_run=True,
    )
    assert "--incremental" in cmd_inc


def test_firstboot_skips_execution_when_packer_build_userdata_present(tmp_path):
    """Verify firstboot.sh exits 0 immediately when Packer builder User-Data guard is present."""
    app_dir = tmp_path / "brainsos"
    app_dir.mkdir()
    userdata_file = tmp_path / "userdata.txt"
    userdata_file.write_text("#cloud-config\n# BRAINSOS_PACKER_BUILD=true\n")

    env = os.environ.copy()
    env["BRAINSOS_REPO_ROOT"] = str(app_dir)
    env["BRAINSOS_FIRSTBOOT_USER_DATA_FILE"] = str(userdata_file)

    proc = subprocess.run(
        ["bash", str(FIRSTBOOT_SH), "--dry-run", "--skip-imds"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "Packer build marker (BRAINSOS_PACKER_BUILD=true) detected in User Data" in proc.stdout
    assert not (app_dir / ".env").exists()


def test_provision_script_incremental_mode_invariants():
    """Verify provision.sh implements incremental delta mode and cleans wizard marker."""
    text = PROVISION_SH.read_text()
    assert 'IS_INCREMENTAL_HOST=true' in text
    assert "docker image prune -f" in text
    assert ".brainsos-wizard-completed" in text
