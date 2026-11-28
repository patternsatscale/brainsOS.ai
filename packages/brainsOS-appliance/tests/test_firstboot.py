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
    assert "[DRY-RUN] BRAINSOS_AUTO_PULL_ON_BOOT=false" in proc.stdout
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


def test_firstboot_persists_ddns_owner_secret_before_step_1d(tmp_path: Path):
    """Verify firstboot.sh generates & persists 256-bit BRAINSOS_DDNS_OWNER_SECRET before Step 1d and matches .env."""
    import os
    import re
    import shutil
    import stat

    real_root = Path(__file__).resolve().parents[3]
    fake_repo = tmp_path / "repo"
    (fake_repo / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True)
    (fake_repo / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(real_root / ".env.example", fake_repo / ".env.example")
    for rel in (
        "packages/brainsOS-appliance/scripts/firstboot.sh",
        "scripts/control/generate-env.sh",
        "scripts/control/env-upsert.sh",
    ):
        dst = fake_repo / rel
        shutil.copy2(real_root / rel, dst)
        dst.chmod(0o755)

    recorded_secret = tmp_path / "recorded-step1d-secret.txt"
    mock_ddns = fake_repo / "scripts" / "control" / "sync-route53-ddns.py"
    mock_ddns.write_text(
        f"#!/usr/bin/env python3\n"
        f"import os, pathlib\n"
        f"pathlib.Path({str(recorded_secret)!r}).write_text(os.environ.get('BRAINSOS_DDNS_OWNER_SECRET', ''), encoding='utf-8')\n",
        encoding="utf-8",
    )
    mock_ddns.chmod(0o755)

    user_data = tmp_path / "user-data"
    user_data.write_text(
        "BRAINSOS_DOMAIN=alice.demo.infotechlabs.io\nHOSTED_ZONE_ID=Z0987654321DEMO\n",
        encoding="utf-8",
    )
    mount_root = tmp_path / "mnt"
    mount_root.mkdir()

    env = {
        **{
            k: v
            for k, v in os.environ.items()
            if k != "BRAINSOS_DATA_DIR" and not (k.startswith("BRAINSOS_") and k.endswith("_DIR"))
        },
        "BRAINSOS_REPO_ROOT": str(fake_repo),
        "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
        "BRAINSOS_FIRSTBOOT_USER_DATA_FILE": str(user_data),
        "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "i-0123456789abcdef0",
        "BRAINSOS_FIRSTBOOT_PUBLIC_IPV4": "54.210.11.22",
    }
    proc = subprocess.run(
        [
            str(fake_repo / "packages/brainsOS-appliance/scripts/firstboot.sh"),
            "--skip-imds",
            "--skip-portal",
            "--mount-root",
            str(mount_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    step1d_secret = recorded_secret.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", step1d_secret)

    secret_file = mount_root / "data" / "control_plane" / "ddns-owner-secret"
    assert secret_file.is_file()
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    assert secret_file.read_text(encoding="utf-8").strip() == step1d_secret

    mnt_env = mount_root / ".env"
    assert mnt_env.is_file()
    assert stat.S_IMODE(mnt_env.stat().st_mode) == 0o600
    assert f"BRAINSOS_DDNS_OWNER_SECRET={step1d_secret}" in mnt_env.read_text(encoding="utf-8")


def test_firstboot_dry_run_logs_ddns_secret_without_writing(tmp_path: Path):
    """Verify --dry-run logs BRAINSOS_DDNS_OWNER_SECRET without creating files on disk."""
    import os

    repo_root = Path(__file__).resolve().parents[3]
    firstboot_script = repo_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
    mnt = tmp_path / "mnt_dry"
    env = {**os.environ, "BRAINSOS_MOUNT_ROOT": str(mnt)}
    proc = subprocess.run(
        [str(firstboot_script), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    import re

    assert "[DRY-RUN] BRAINSOS_DDNS_OWNER_SECRET=<auto-generated-256bit>" in proc.stdout
    assert "[DRY-RUN] TOOL_EGRESS_PROXY_SECRET=<auto-generated-256bit>" in proc.stdout
    assert re.search(r"\[DRY-RUN\] BRAINSOS_BOOTSTRAP_TOKEN=(?:bt-[0-9a-f]{32}|i-[a-z0-9]+)", proc.stdout)
    assert not mnt.exists()


def test_firstboot_non_ec2_persists_random_bootstrap_token_and_independent_passwords(tmp_path: Path):
    """Verify non-EC2 firstboot generates random 128-bit bootstrap token (0600), independent Authentik password, and locks OS admin (#405)."""
    import os
    import re
    import shutil
    import stat

    real_root = Path(__file__).resolve().parents[3]
    fake_repo = tmp_path / "repo"
    (fake_repo / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True)
    (fake_repo / "scripts" / "control").mkdir(parents=True)
    shutil.copy2(real_root / ".env.example", fake_repo / ".env.example")
    for rel in (
        "packages/brainsOS-appliance/scripts/firstboot.sh",
        "scripts/control/generate-env.sh",
        "scripts/control/env-upsert.sh",
    ):
        dst = fake_repo / rel
        shutil.copy2(real_root / rel, dst)
        dst.chmod(0o755)

    mount_root = tmp_path / "mnt"
    mount_root.mkdir()
    env = {
        **{
            k: v
            for k, v in os.environ.items()
            if k != "BRAINSOS_DATA_DIR" and not (k.startswith("BRAINSOS_") and k.endswith("_DIR"))
        },
        "BRAINSOS_REPO_ROOT": str(fake_repo),
        "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
        "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "",
        "BRAINSOS_FIRSTBOOT_PUBLIC_IPV4": "",
    }
    proc = subprocess.run(
        [
            str(fake_repo / "packages/brainsOS-appliance/scripts/firstboot.sh"),
            "--skip-imds",
            "--skip-portal",
            "--mount-root",
            str(mount_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    boot_file = mount_root / "data" / "control_plane" / "bootstrap-token"
    assert boot_file.is_file()
    assert stat.S_IMODE(boot_file.stat().st_mode) == 0o600
    boot_tok = boot_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"bt-[0-9a-f]{32}", boot_tok), f"Unexpected token: {boot_tok}"
    assert "i-appliance-" not in boot_tok

    env_text = (mount_root / ".env").read_text(encoding="utf-8")
    kv = {}
    for line in env_text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip().strip('"').strip("'")

    assert kv["BRAINSOS_BOOTSTRAP_TOKEN"] == boot_tok
    assert kv["BRAINSOS_INSTANCE_ID"] == boot_tok
    assert kv["BRAINSOS_ADMIN_PASSWORD"] != boot_tok
    assert kv["BRAINSOS_INSTANCE_ADMIN_PASSWORD"] != boot_tok
    assert kv["AUTHENTIK_BOOTSTRAP_PASSWORD"] != boot_tok
    assert kv["AUTHENTIK_BOOTSTRAP_PASSWORD"] != kv["BRAINSOS_ADMIN_PASSWORD"]
    assert len(kv["AUTHENTIK_BOOTSTRAP_PASSWORD"]) >= 24
    assert len(kv.get("TOOL_EGRESS_PROXY_SECRET", "")) >= 64
    assert kv.get("TOOL_EGRESS_REQUIRE_PROXY_AUTH") == "true"

    # Verify OS admin password locking and zero INSTANCE_ID password assignment across shell scripts
    fb_src = (real_root / "packages/brainsOS-appliance/scripts/firstboot.sh").read_text(encoding="utf-8")
    assert "passwd -l admin" in fb_src
    assert 'echo "admin:${' not in fb_src

    reload_src = (real_root / "scripts/control/reload-env.sh").read_text(encoding="utf-8")
    assert "passwd -l admin" in reload_src
    assert "BRAINSOS_INSTANCE_ADMIN_PASSWORD=${DETECTED_INSTANCE_ID}" not in reload_src
    assert "set_unusable_password" in reload_src


