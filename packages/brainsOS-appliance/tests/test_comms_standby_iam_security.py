"""Regression tests for Ticket #388: mail hashing, Postfix SASL, Signal bridge isolation, standby scrub, and scoped Route53 IAM."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mail_and_sogo_configs_hash_passwords_and_lock_postfix_and_signal() -> None:
    dovecot_conf = (REPO_ROOT / "docker/mail/dovecot/dovecot.conf").read_text(encoding="utf-8")
    assert "MAIL_WEBHOOK_SECRET" in dovecot_conf
    assert "allow_nets=172.16.0.0/12" not in dovecot_conf
    assert "!include_try /etc/mail-brainsos/sogo-proxy-passdb.conf" in dovecot_conf
    assert "scheme=SHA512-CRYPT" in dovecot_conf

    mail_ep = (REPO_ROOT / "docker/mail/entrypoint.sh").read_text(encoding="utf-8")
    assert "{PLAIN}" not in mail_ep
    assert "hash_mail_password" in mail_ep
    assert "mynetworks = 127.0.0.0/8 [::1]/128" in mail_ep

    postfix_cf = (REPO_ROOT / "docker/mail/postfix/main.cf").read_text(encoding="utf-8")
    assert "mynetworks = 127.0.0.0/8 [::1]/128" in postfix_cf
    assert "permit_sasl_authenticated" in postfix_cf

    sogo_conf = (REPO_ROOT / "docker/sogo/sogo.conf").read_text(encoding="utf-8")
    assert "userPasswordAlgorithm = sha512-crypt;" in sogo_conf
    assert "userPasswordAlgorithm = plain;" not in sogo_conf

    sogo_ep = (REPO_ROOT / "docker/sogo/entrypoint.sh").read_text(encoding="utf-8")
    assert "sogo_hash_pw" in sogo_ep
    assert "openssl passwd -6" in sogo_ep

    apps = yaml.safe_load((REPO_ROOT / "docker/compose/compose.apps.yml").read_text(encoding="utf-8"))
    assert "signal-cli" not in apps.get("services", {})
    root_compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "brainsos-comms-net" not in root_compose.get("networks", {})
    assert not (REPO_ROOT / "docker/signal").exists()
    assert not (REPO_ROOT / "scripts/setup/link-signal.sh").exists()
    assert not (REPO_ROOT / "scripts/verify/verify-signal.sh").exists()
    assert "MAIL_WEBHOOK_SECRET=${MAIL_WEBHOOK_SECRET:-}" in apps["services"]["mail-server"]["environment"]


def test_scoped_route53_iam_conditions_present() -> None:
    launch_fleet = (REPO_ROOT / "scripts/control/launch-fleet.sh").read_text(encoding="utf-8")
    assert "route53:ChangeResourceRecordSetsNormalizedRecordNames" in launch_fleet
    assert "route53:ChangeResourceRecordSetsRecordTypes" in launch_fleet

    iam_ts = (REPO_ROOT / "infra/src/components/iam.ts").read_text(encoding="utf-8")
    assert "route53:ChangeResourceRecordSetsNormalizedRecordNames" in iam_ts
    assert "route53:ChangeResourceRecordSetsRecordTypes" in iam_ts


def test_release_user_volume_scrubs_host_state_without_touching_ebs(tmp_path: Path) -> None:
    host_repo = tmp_path / "repo"
    (host_repo / "docker" / "langfuse").mkdir(parents=True)
    (host_repo / "data" / "system_jobs").mkdir(parents=True)
    ebs_mount = tmp_path / "ebs"
    ebs_mount.mkdir()

    (host_repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (host_repo / ".brainsos-wizard-completed").write_text("done\n", encoding="utf-8")
    (host_repo / "docker" / "langfuse" / ".env").write_text("NEXTAUTH_SECRET=abc\n", encoding="utf-8")
    (host_repo / "data" / "system_jobs" / "job1.json").write_text("{}\n", encoding="utf-8")
    sudoers_file = tmp_path / "90-brainsos-admin"
    sudoers_file.write_text("admin ALL=(ALL:ALL) ALL\nalice ALL=(ALL:ALL) ALL\n", encoding="utf-8")
    ebs_secret = ebs_mount / ".env"
    ebs_secret.write_text("USER_EBS_ENV=keep\n", encoding="utf-8")

    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_repo),
        "BRAINSOS_SUDOERS_FILE": str(sudoers_file),
    }
    proc = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "release-user-volume.sh"),
            "--mount",
            str(ebs_mount),
            "--skip-service-stop",
            "--skip-umount",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (host_repo / ".env").exists()
    assert not (host_repo / ".brainsos-wizard-completed").exists()
    assert not (host_repo / "docker" / "langfuse" / ".env").exists()
    assert list((host_repo / "data" / "system_jobs").iterdir()) == []
    assert not sudoers_file.exists()
    assert ebs_secret.read_text(encoding="utf-8") == "USER_EBS_ENV=keep\n"


def test_m4_mail_sogo_and_webhook_hardening() -> None:
    setup_mail = (REPO_ROOT / "scripts/setup/setup-mail.sh").read_text(encoding="utf-8")
    assert "{PLAIN}" not in setup_mail
    assert "{SHA512-CRYPT}" in setup_mail
    assert "777" not in setup_mail
    assert "5000:5000" in setup_mail

    setup_sogo = (REPO_ROOT / "scripts/setup/setup-sogo.sh").read_text(encoding="utf-8")
    assert "777" not in setup_sogo
    assert "5000:5000" in setup_sogo

    reload_env = (REPO_ROOT / "scripts/control/reload-env.sh").read_text(encoding="utf-8")
    assert "{SHA512-CRYPT}" in reload_env
    assert "SELECT c_uid, c_name, c_password" not in reload_env

    sogo_ep = (REPO_ROOT / "docker/sogo/entrypoint.sh").read_text(encoding="utf-8")
    assert "SELECT c_uid, c_name, c_password" not in sogo_ep

    postfix_cf = (REPO_ROOT / "docker/mail/postfix/main.cf").read_text(encoding="utf-8")
    assert "smtpd_sender_login_maps" in postfix_cf
    assert "reject_sender_login_mismatch" in postfix_cf

    mail_ep = (REPO_ROOT / "docker/mail/entrypoint.sh").read_text(encoding="utf-8")
    assert "> /etc/environment" not in mail_ep
    assert "chmod 644 /etc/environment" not in mail_ep
    assert "0600" in mail_ep and "vmail:vmail" in mail_ep

    webhook_sh = (REPO_ROOT / "docker/mail/agent-webhook.sh").read_text(encoding="utf-8")
    assert "/etc/environment" not in webhook_sh
    assert "/etc/dovecot/mail-webhook-secret" in webhook_sh
