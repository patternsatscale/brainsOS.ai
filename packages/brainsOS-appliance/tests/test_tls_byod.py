"""Unit and integration tests for Ticket #323: Appliance TLS & BYOD upgrade path."""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_UPSERT = REPO_ROOT / "scripts" / "control" / "env-upsert.sh"
SET_DOMAIN = REPO_ROOT / "scripts" / "control" / "set-domain.sh"
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
TRUST_CA = REPO_ROOT / "scripts" / "setup" / "trust-caddy-ca.sh"


def test_env_upsert_crud(tmp_path: Path):
    """Verify env-upsert.sh can create, update, and unset keys while enforcing 0600."""
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_KEY=old_value\nANOTHER_KEY=\"keep\"\n", encoding="utf-8")
    env_file.chmod(0o600)

    # 1. Update existing key
    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "EXISTING_KEY=new_value"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    content = env_file.read_text(encoding="utf-8")
    assert "EXISTING_KEY=new_value" in content
    assert 'ANOTHER_KEY="keep"' in content

    # 2. Add new key
    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "NEW_KEY=brand_new"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    content = env_file.read_text(encoding="utf-8")
    assert "NEW_KEY=brand_new" in content

    # Verify permissions remain 0600
    file_stat = env_file.stat()
    assert stat.S_IMODE(file_stat.st_mode) == 0o600

    # 3. Unset a key
    proc = subprocess.run(
        [str(ENV_UPSERT), "--file", str(env_file), "--unset", "EXISTING_KEY"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    content = env_file.read_text(encoding="utf-8")
    assert "EXISTING_KEY" not in content
    assert "NEW_KEY=brand_new" in content


def test_set_domain_help():
    """Verify set-domain.sh --help outputs usage with all required flags."""
    proc = subprocess.run(
        [str(SET_DOMAIN), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--domain" in proc.stdout
    assert "--email" in proc.stdout
    assert "--internal" in proc.stdout
    assert "--dns" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--skip-dns-check" in proc.stdout


def test_set_domain_dry_run_internal(tmp_path: Path):
    """Verify set-domain.sh --internal --dry-run plans reset to internal CA."""
    dummy_env = tmp_path / ".env"
    dummy_env.write_text("BRAINSOS_DOMAIN=\"mycustom.org\"\n", encoding="utf-8")

    env = os.environ.copy()
    env["BRAINSOS_ENV_FILE"] = str(dummy_env)
    proc = subprocess.run(
        [str(SET_DOMAIN), "--internal", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert "BRAINSOS_TLS_MODE=internal" in proc.stdout
    assert "BRAINSOS_DOMAIN=mycustom.org" in proc.stdout
    assert "Domain configuration simulation complete" in proc.stdout


def test_set_domain_dry_run_acme(tmp_path: Path):
    """Verify set-domain.sh with public domain and email in dry run mode."""
    dummy_env = tmp_path / ".env"
    dummy_env.write_text("BRAINSOS_DOMAIN=\"localhost\"\n", encoding="utf-8")

    env = os.environ.copy()
    env["BRAINSOS_ENV_FILE"] = str(dummy_env)
    proc = subprocess.run(
        [
            str(SET_DOMAIN),
            "--domain", "agent.example.com",
            "--email", "admin@example.com",
            "--skip-dns-check",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert "BRAINSOS_DOMAIN=agent.example.com" in proc.stdout
    assert "BRAINSOS_TLS_MODE=acme" in proc.stdout
    assert "ACME_EMAIL=admin@example.com" in proc.stdout
    assert "Domain configuration simulation complete" in proc.stdout


def test_set_domain_validation_errors():
    """Verify set-domain.sh rejects invalid domains or missing required params."""
    # 1. Invalid domain format
    proc = subprocess.run(
        [str(SET_DOMAIN), "--domain", "not_a_valid_domain", "--email", "test@example.com", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Invalid fully qualified domain name" in proc.stderr or "Invalid fully qualified domain name" in proc.stdout

    # 2. Missing email for ACME
    proc = subprocess.run(
        [str(SET_DOMAIN), "--domain", "valid.example.com", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--email" in proc.stderr or "--email" in proc.stdout

    # 3. Invalid email format
    proc = subprocess.run(
        [str(SET_DOMAIN), "--domain", "valid.example.com", "--email", "not-an-email", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Invalid ACME email" in proc.stderr or "Invalid ACME email" in proc.stdout


def test_firstboot_parses_user_data_file(tmp_path: Path):
    """Verify firstboot.sh correctly extracts user-data parameters."""
    user_data = tmp_path / "user-data"
    user_data.write_text(
        """#cloud-config
brainsos:
  domain: custom.ai.corp
  email: secops@corp.com
  tls_mode: acme
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["BRAINSOS_FIRSTBOOT_USER_DATA_FILE"] = str(user_data)

    proc = subprocess.run(
        [str(FIRSTBOOT), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert "BRAINSOS_DOMAIN=custom.ai.corp" in proc.stdout
    assert "ACME_EMAIL=secops@corp.com" in proc.stdout
    assert "BRAINSOS_TLS_MODE=acme" in proc.stdout


def test_trust_caddy_ca_export_flag():
    """Verify trust-caddy-ca.sh supports --export flag."""
    proc = subprocess.run(
        [str(TRUST_CA), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--export" in proc.stdout
