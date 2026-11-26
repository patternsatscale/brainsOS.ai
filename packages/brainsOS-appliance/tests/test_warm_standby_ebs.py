"""Tests for Ticket #382 (Part B): Warm-standby boot mode & persistent user EBS volume lifecycle."""

import http.server
import os
import shutil
import socket
import ssl
import stat
import struct
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"
CLAIM_VOL = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "claim-user-volume.sh"
RELEASE_VOL = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "release-user-volume.sh"
CLAIM_WRAPPER = REPO_ROOT / "scripts" / "control" / "claim-user-volume.sh"
RELEASE_WRAPPER = REPO_ROOT / "scripts" / "control" / "release-user-volume.sh"
ENV_UPSERT = REPO_ROOT / "scripts" / "control" / "env-upsert.sh"
GENERATE_ENV = REPO_ROOT / "scripts" / "control" / "generate-env.sh"
BOOTSTRAP_ENV = REPO_ROOT / "scripts" / "control" / "bootstrap-env.sh"
PROVISION_SH = REPO_ROOT / "packages" / "brainsOS-appliance" / "packer" / "provision.sh"
BRAINSOS_SERVICE = REPO_ROOT / "packages" / "brainsOS-appliance" / "configs" / "brainsos.service"
FIRSTBOOT_SERVICE = REPO_ROOT / "packages" / "brainsOS-appliance" / "configs" / "brainsos-firstboot.service"


def _find_sbin_tool(name: str) -> str | None:
    for candidate in (shutil.which(name), f"/usr/sbin/{name}", f"/sbin/{name}"):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


BLKID_BIN = _find_sbin_tool("blkid")
MKFS_EXT4_BIN = _find_sbin_tool("mkfs.ext4")


def _can_sudo_mount() -> bool:
    if os.geteuid() == 0:
        return True
    res = subprocess.run(["sudo", "-n", "true"], capture_output=True, check=False)
    return res.returncode == 0


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@brainsos.ai", "-c", "user.name=test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        val = value.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key.strip()] = val
    return values


def _stage_appliance_host(base_dir: Path, name: str) -> Path:
    """Create an isolated appliance repository root in tmp_path (never touches live host)."""
    root = base_dir / name
    (root / "scripts" / "control").mkdir(parents=True)
    (root / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True)
    (root / "config" / "default_settings").mkdir(parents=True)
    (root / "config" / "default_runners" / "hermes").mkdir(parents=True)
    (root / "config" / "default_agents" / "demo_agent").mkdir(parents=True)

    for src in (GENERATE_ENV, ENV_UPSERT, BOOTSTRAP_ENV, CLAIM_WRAPPER, RELEASE_WRAPPER):
        shutil.copy2(src, root / "scripts" / "control" / src.name)
    for src in (FIRSTBOOT, CLAIM_VOL, RELEASE_VOL):
        shutil.copy2(src, root / "packages" / "brainsOS-appliance" / "scripts" / src.name)
    shutil.copy2(REPO_ROOT / ".env.example", root / ".env.example")

    (root / "config" / "default_settings" / "agents.yaml").write_text("agents: []\n", encoding="utf-8")
    (root / "config" / "default_runners" / "hermes" / "config.yaml").write_text("model: brainsos-core\n", encoding="utf-8")
    (root / "config" / "default_agents" / "demo_agent" / "SOUL.md").write_text("# Demo Agent\n", encoding="utf-8")

    _git(root, "init", "--quiet")
    return root


@pytest.fixture(autouse=True)
def _clean_ambient_brainsos_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent earlier package tests from leaking host .env BRAINSOS_* vars into isolated subprocesses."""
    for key in list(os.environ.keys()):
        if key.startswith("BRAINSOS_"):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "user_data_body",
    [
        "BRAINSOS_WARM_STANDBY=true\n",
        "BRAINSOS_WARM_STANDBY: true\n",
        "#cloud-config\nbrainsos:\n  warm_standby: true\n  domain: warm.demo.example.com\n",
    ],
)
def test_firstboot_warm_standby_userdata_exits_cleanly(tmp_path: Path, user_data_body: str):
    """Warm-standby user-data causes firstboot.sh to exit 0 without creating .env, data/, or init marker."""
    host_root = _stage_appliance_host(tmp_path, "warm_host")
    ud_file = tmp_path / "user-data.txt"
    ud_file.write_text(user_data_body, encoding="utf-8")

    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_root),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
        "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
        "BRAINSOS_FIRSTBOOT_USER_DATA_FILE": str(ud_file),
    }
    proc = subprocess.run(
        ["bash", str(host_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Warm standby mode (BRAINSOS_WARM_STANDBY=true) detected" in proc.stdout
    assert not (host_root / ".env").exists()
    assert not (host_root / ".env").is_symlink()
    assert not (host_root / ".brainsos-initialized").exists()
    assert not (host_root / ".brainsos-initialized").is_symlink()
    assert not (host_root / "data").exists()

    # --check must still report uninitialized (exit 1)
    chk = subprocess.run(
        ["bash", str(host_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert chk.returncode == 1


def test_firstboot_standalone_backwards_compatible(tmp_path: Path):
    """Without BRAINSOS_WARM_STANDBY or BRAINSOS_MOUNT_ROOT, firstboot.sh behaves identically to standalone mode."""
    host_root = _stage_appliance_host(tmp_path, "standalone_host")
    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_root),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
        "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
        "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "i-0standalone1234567",
    }
    proc = subprocess.run(
        ["bash", str(host_root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    env_file = host_root / ".env"
    init_flag = host_root / ".brainsos-initialized"
    assert env_file.is_file() and not env_file.is_symlink()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert init_flag.is_file() and not init_flag.is_symlink()

    parsed = _parse_env(env_file)
    assert parsed["BRAINSOS_INSTANCE_ID"] == "i-0standalone1234567"
    assert parsed["BRAINSOS_DATA_DIR"] == str(host_root / "data")
    assert (host_root / "data" / "runners" / "hermes" / "state").is_dir()
    assert (host_root / "data" / "control_plane" / "caddy_data").is_dir()


def test_env_upsert_preserves_symlink_across_mount(tmp_path: Path):
    """env-upsert.sh, generate-env.sh, and bootstrap-env.sh preserve /opt/brainsos/.env -> /mnt/.env symlinks."""
    host_root = _stage_appliance_host(tmp_path, "symlink_host")
    mount_root = tmp_path / "mnt_brainsos_data"
    mount_root.mkdir(parents=True)

    # 1. bootstrap-env.sh --mount-root creates mount_root/.env and links host_root/.env -> mount_root/.env
    boot_env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_root),
        "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
    }
    boot_proc = subprocess.run(
        [
            "bash",
            str(host_root / "scripts" / "control" / "bootstrap-env.sh"),
            "--mount-root",
            str(mount_root),
            "--skip-images",
            "--skip-portal",
            "--skip-models",
        ],
        env=boot_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert boot_proc.returncode == 0, boot_proc.stdout + boot_proc.stderr

    link_env = host_root / ".env"
    real_env = mount_root / ".env"
    assert real_env.is_file() and not real_env.is_symlink()
    assert link_env.is_symlink()
    assert link_env.resolve() == real_env.resolve()
    assert stat.S_IMODE(real_env.stat().st_mode) == 0o600
    assert (mount_root / "data" / "runners" / "hermes" / "state").is_dir()
    assert (mount_root / "data" / "control_plane" / "caddy_data").is_dir()

    # 2. env-upsert.sh against the symlink updates mount_root/.env in place without replacing the symlink
    upsert_proc = subprocess.run(
        [
            str(host_root / "scripts" / "control" / "env-upsert.sh"),
            "--file",
            str(link_env),
            "BRAINSOS_DOMAIN=user.demo.example.com",
            "CUSTOM_WARM_TEST=preserved_symlink",
        ],
        env=boot_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upsert_proc.returncode == 0, upsert_proc.stderr
    assert link_env.is_symlink()
    assert link_env.resolve() == real_env.resolve()
    assert stat.S_IMODE(real_env.stat().st_mode) == 0o600

    parsed = _parse_env(real_env)
    assert parsed["BRAINSOS_DOMAIN"] == "user.demo.example.com"
    assert parsed["CUSTOM_WARM_TEST"] == "preserved_symlink"

    # Zero leftover temp files in either directory
    assert not list(host_root.glob(".env.upsert.*"))
    assert not list(mount_root.glob(".env.upsert.*"))

    # 3. Re-running bootstrap-env.sh --data-dir preserves the symlink (no sed -i symlink clobber)
    custom_data = mount_root / "data"
    rerun_proc = subprocess.run(
        [
            "bash",
            str(host_root / "scripts" / "control" / "bootstrap-env.sh"),
            "--data-dir",
            str(custom_data),
            "--skip-images",
            "--skip-portal",
            "--skip-models",
        ],
        env=boot_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rerun_proc.returncode == 0, rerun_proc.stdout + rerun_proc.stderr
    assert link_env.is_symlink()
    assert _parse_env(real_env)["BRAINSOS_DATA_DIR"] == str(custom_data)


@pytest.mark.skipif(BLKID_BIN is None or MKFS_EXT4_BIN is None, reason="blkid / mkfs.ext4 required")
def test_claim_and_release_lifecycle_across_two_hosts(tmp_path: Path):
    """Full warm-standby claim -> DB state write -> release -> detach -> attach to Host B resume lifecycle."""
    host_a = _stage_appliance_host(tmp_path, "warm_host_a")
    host_b = _stage_appliance_host(tmp_path, "warm_host_b")

    # Both Host A and Host B were booted into the warm pool with BRAINSOS_WARM_STANDBY=true in IMDS user-data
    ud_warm = tmp_path / "warm-userdata.txt"
    ud_warm.write_text("BRAINSOS_WARM_STANDBY=true\n", encoding="utf-8")

    # Verify Host A parks cleanly on initial boot
    park_proc = subprocess.run(
        ["bash", str(host_a / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env={
            **os.environ,
            "BRAINSOS_REPO_ROOT": str(host_a),
            "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
            "BRAINSOS_FIRSTBOOT_USER_DATA_FILE": str(ud_warm),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert park_proc.returncode == 0
    assert not (host_a / ".env").exists()

    # Create a blank 64 MiB raw EBS volume image + mount directory
    vol_img = tmp_path / "alice-ebs.img"
    with open(vol_img, "wb") as fh:
        fh.truncate(64 * 1024 * 1024)

    # Confirm blkid exits 2 on the blank unformatted volume image
    blank_probe = subprocess.run([BLKID_BIN, str(vol_img)], capture_output=True, text=True, check=False)
    assert blank_probe.returncode == 2

    ebs_mount = tmp_path / "mnt_alice_ebs"

    # --- STEP 1: First-time claim on Warm Host A ---
    env_a = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_a),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
        "BRAINSOS_FIRSTBOOT_USER_DATA_FILE": str(ud_warm),
        "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "i-0hosta11111111111",
        "BRAINSOS_FIRSTBOOT_PUBLIC_IPV4": "54.10.20.30",
    }
    claim_a = subprocess.run(
        [
            "bash",
            str(host_a / "scripts" / "control" / "claim-user-volume.sh"),
            "--device",
            str(vol_img),
            "--mount",
            str(ebs_mount),
            "--domain",
            "alice-v1.demo.example.com",
            "--user-sub",
            "cognito-sub-alice-001",
            "--skip-mount",
            "--skip-service-start",
        ],
        env=env_a,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert claim_a.returncode == 0, claim_a.stdout + claim_a.stderr

    # Verify blank volume image was formatted as ext4 with label brainsos-user
    fs_type = subprocess.run(
        [BLKID_BIN, "-o", "value", "-s", "TYPE", str(vol_img)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fs_label = subprocess.run(
        [BLKID_BIN, "-o", "value", "-s", "LABEL", str(vol_img)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fs_uuid_after_a = subprocess.run(
        [BLKID_BIN, "-o", "value", "-s", "UUID", str(vol_img)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert fs_type == "ext4"
    assert fs_label == "brainsos-user"
    assert fs_uuid_after_a

    # Verify symlinks on Host A point to the persistent volume
    assert (host_a / ".env").is_symlink()
    assert (host_a / ".env").resolve() == (ebs_mount / ".env").resolve()
    assert (host_a / ".brainsos-initialized").is_symlink()
    assert stat.S_IMODE((ebs_mount / ".env").stat().st_mode) == 0o600

    vars_a = _parse_env(ebs_mount / ".env")
    assert vars_a["BRAINSOS_INSTANCE_ID"] == "i-0hosta11111111111"
    assert vars_a["BRAINSOS_DOMAIN"] == "alice-v1.demo.example.com"
    assert vars_a["BRAINSOS_URL"] == "alice-v1.demo.example.com"
    assert vars_a["BRAINSOS_MOUNT_ROOT"] == str(ebs_mount)
    assert vars_a["BRAINSOS_DATA_DIR"] == str(ebs_mount / "data")
    assert vars_a["BRAINSOS_USER_SUB"] == "cognito-sub-alice-001"

    # Simulate live database files & OKF agent memories written during Alice's session on Host A
    pg_sentinel = ebs_mount / "data" / "control_plane" / "litellm_db" / "PG_VERSION"
    pg_sentinel.write_text("16\n", encoding="utf-8")
    caddy_cert_sentinel = ebs_mount / "data" / "control_plane" / "caddy_data" / "acme.crt"
    caddy_cert_sentinel.write_text("CERT_DATA\n", encoding="utf-8")
    hermes_state_sentinel = ebs_mount / "data" / "runners" / "hermes" / "state" / "session.json"
    hermes_state_sentinel.write_text('{"turn": 3}\n', encoding="utf-8")
    memory_sentinel = ebs_mount / "data" / "agents" / "demo_agent" / "memories" / "journal.md"
    memory_sentinel.parent.mkdir(parents=True, exist_ok=True)
    memory_sentinel.write_text("# Persistent OKF Memory\n", encoding="utf-8")

    secret_keys = (
        "LITELLM_DB_PASSWORD",
        "AUTHENTIK_POSTGRESQL__PASSWORD",
        "SOGO_DB_PASSWORD",
        "LANGFUSE_DB_PASSWORD",
        "LENS_CLICKHOUSE_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "LITELLM_MASTER_KEY",
        "AUTHENTIK_SECRET_KEY",
        "CODE_SERVER_PASSWORD",
        "BRAINSOS_ADMIN_PASSWORD",
        "AUTHENTIK_BOOTSTRAP_PASSWORD",
        "DATABASE_URL",
    )
    for k in secret_keys:
        assert vars_a.get(k), f"Expected {k} to be populated on Host A"

    # --- STEP 2: Release volume on Host A before DetachVolume ---
    rel_a = subprocess.run(
        [
            "bash",
            str(host_a / "scripts" / "control" / "release-user-volume.sh"),
            "--mount",
            str(ebs_mount),
            "--skip-service-stop",
            "--skip-umount",
        ],
        env=env_a,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rel_a.returncode == 0, rel_a.stdout + rel_a.stderr
    assert not (host_a / ".env").exists() and not (host_a / ".env").is_symlink()
    assert not (host_a / ".brainsos-initialized").exists() and not (host_a / ".brainsos-initialized").is_symlink()
    assert (ebs_mount / ".env").is_file()

    # --- STEP 3: Attach same volume to fresh Warm Host B & claim ---
    env_b = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(host_b),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
        "BRAINSOS_FIRSTBOOT_USER_DATA_FILE": str(ud_warm),
        "BRAINSOS_FIRSTBOOT_INSTANCE_ID": "i-0hostb22222222222",
        "BRAINSOS_FIRSTBOOT_PUBLIC_IPV4": "3.88.77.66",
        "BRAINSOS_FIRSTBOOT_LOCAL_IPV4": "10.0.4.25",
        "BRAINSOS_FIRSTBOOT_REGION": "us-west-2",
    }
    claim_b = subprocess.run(
        [
            "bash",
            str(host_b / "scripts" / "control" / "claim-user-volume.sh"),
            "--device",
            str(vol_img),
            "--mount",
            str(ebs_mount),
            "--domain",
            "alice.demo.example.com",
            "--user-sub",
            "cognito-sub-alice-001",
            "--skip-mount",
            "--skip-service-start",
        ],
        env=env_b,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert claim_b.returncode == 0, claim_b.stdout + claim_b.stderr
    assert "Existing ext4 filesystem detected" in claim_b.stdout
    assert "Existing user environment detected" in claim_b.stdout

    # Proof mkfs.ext4 was NEVER re-executed: filesystem UUID is unchanged!
    fs_uuid_after_b = subprocess.run(
        [BLKID_BIN, "-o", "value", "-s", "UUID", str(vol_img)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert fs_uuid_after_b == fs_uuid_after_a

    # Host B symlinks are active and point to the volume
    assert (host_b / ".env").is_symlink()
    assert (host_b / ".env").resolve() == (ebs_mount / ".env").resolve()
    assert (host_b / ".brainsos-initialized").is_symlink()

    vars_b = _parse_env(ebs_mount / ".env")
    # Every database & service credential must be 100% preserved across Host A -> Host B
    for k in secret_keys:
        assert vars_b[k] == vars_a[k], f"Credential {k} drifted when resuming volume on Host B!"

    # Host-specific metadata updated cleanly to Host B
    assert vars_b["BRAINSOS_INSTANCE_ID"] == "i-0hostb22222222222"
    assert vars_b["BRAINSOS_DOMAIN"] == "alice.demo.example.com"
    assert vars_b["BRAINSOS_URL"] == "alice.demo.example.com"
    assert vars_b["NEXTAUTH_URL"] == "https://alice.demo.example.com"
    assert vars_b["BRAINSOS_LAST_SYNCED_IP"] == "3.88.77.66"
    assert vars_b["BRAINSOS_IP_SITES"] == "3.88.77.66 10.0.4.25"
    assert vars_b["AWS_REGION"] == "us-west-2"
    assert vars_b["COMPOSE_FILE"].startswith(str(host_b))

    # Sentinel DB, Caddy TLS, Hermes state, and OKF memory files survived intact
    assert pg_sentinel.read_text(encoding="utf-8") == "16\n"
    assert caddy_cert_sentinel.read_text(encoding="utf-8") == "CERT_DATA\n"
    assert hermes_state_sentinel.read_text(encoding="utf-8") == '{"turn": 3}\n'
    assert memory_sentinel.read_text(encoding="utf-8") == "# Persistent OKF Memory\n"


@pytest.mark.skipif(BLKID_BIN is None, reason="blkid required")
def test_claim_refuses_to_format_partitioned_disk_without_direct_fs(tmp_path: Path):
    """Fail-closed: a disk containing a partition table (MBR/GPT) and no direct FS is never formatted."""
    host_root = _stage_appliance_host(tmp_path, "part_guard_host")
    part_img = tmp_path / "partitioned.img"
    with open(part_img, "wb") as fh:
        fh.truncate(16 * 1024 * 1024)
        # Write minimal DOS MBR signature (0x55AA at 510) + one non-empty partition entry at 446
        fh.seek(446)
        fh.write(struct.pack("<BBBBBBBBII", 0x00, 0x01, 0x01, 0x00, 0x83, 0xFE, 0x3F, 0x01, 2048, 8192))
        fh.seek(510)
        fh.write(b"\x55\xaa")

    proc = subprocess.run(
        [
            "bash",
            str(host_root / "scripts" / "control" / "claim-user-volume.sh"),
            "--device",
            str(part_img),
            "--mount",
            str(tmp_path / "mnt_part"),
            "--skip-mount",
            "--skip-service-start",
        ],
        env={
            **os.environ,
            "BRAINSOS_REPO_ROOT": str(host_root),
            "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Refusing to format" in combined or "Partition table" in combined


def test_claim_service_start_and_https_health_gate(tmp_path: Path):
    """Verify claim-user-volume.sh starts systemd units and polls HTTPS health gate until 200/302/401."""
    host_root = _stage_appliance_host(tmp_path, "health_host")
    ebs_mount = tmp_path / "mnt_health"
    ebs_mount.mkdir(parents=True)
    (ebs_mount / ".env").write_text("BRAINSOS_DOMAIN=health.demo.example.com\n", encoding="utf-8")

    # Mock systemctl in a dedicated bin dir prepended to PATH
    mock_bin = tmp_path / "mock_bin"
    mock_bin.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    mock_systemctl = mock_bin / "systemctl"
    mock_systemctl.write_text(
        f'#!/usr/bin/env bash\necho "$@" >> "{systemctl_log}"\nexit 0\n',
        encoding="utf-8",
    )
    mock_systemctl.chmod(0o755)

    # Generate ephemeral self-signed cert via openssl for local HTTPS health server
    cert_file = tmp_path / "srv.crt"
    key_file = tmp_path / "srv.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_file),
            "-out",
            str(cert_file),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )

    attempts = {"count": 0}

    class _GateHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            attempts["count"] += 1
            code = 502 if attempts["count"] == 1 else 302
            self.send_response(code)
            self.end_headers()

        def log_message(self, *_args):
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    httpd = http.server.HTTPServer(("127.0.0.1", port), _GateHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        proc = subprocess.run(
            [
                "bash",
                str(host_root / "scripts" / "control" / "claim-user-volume.sh"),
                "--mount",
                str(ebs_mount),
                "--skip-mount",
                "--health-url",
                f"https://127.0.0.1:{port}/",
                "--health-timeout",
                "15",
            ],
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ.get('PATH', '')}",
                "BRAINSOS_REPO_ROOT": str(host_root),
                "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
                "BRAINSOS_BOOTSTRAP_SKIP_VENV": "true",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert attempts["count"] >= 2
    assert "Ingress health gate passed" in proc.stdout
    logged_units = systemctl_log.read_text(encoding="utf-8")
    assert "start brainsos-system-api.service" in logged_units
    assert "start brainsos.service" in logged_units


def test_wrappers_rule8_no_symlinks_and_snapshot_scan_catches_dangling_symlinks(tmp_path: Path):
    """Rule 8 & AMI hygiene: repo wrappers are regular exec scripts (never symlinks) and scan rejects .env symlinks."""
    for wrapper in (CLAIM_WRAPPER, RELEASE_WRAPPER, CLAIM_VOL, RELEASE_VOL):
        assert wrapper.is_file()
        assert not wrapper.is_symlink(), f"Rule 8 violation: committed symlink at {wrapper}"
        assert os.access(wrapper, os.X_OK), f"Script not executable: {wrapper}"

    svc_content = BRAINSOS_SERVICE.read_text(encoding="utf-8")
    assert "ConditionPathExists=/opt/brainsos/.env" in svc_content
    assert "brainsos-system-api.service" in svc_content

    fb_svc_content = FIRSTBOOT_SERVICE.read_text(encoding="utf-8")
    assert "ConditionPathExists=!/opt/brainsos/.brainsos-initialized" in fb_svc_content

    # Snapshot scan must fail closed even on a dangling .env or .brainsos-initialized symlink
    scan_dir = tmp_path / "ami_stage"
    scan_dir.mkdir()
    (scan_dir / ".env.example").write_text("FOO=\n", encoding="utf-8")
    (scan_dir / ".env").symlink_to("/mnt/brainsos-data/.env")
    scan_proc = subprocess.run(
        ["bash", str(PROVISION_SH), "--scan-only", "--app-dir", str(scan_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan_proc.returncode == 1
    assert "environment file present" in (scan_proc.stdout + scan_proc.stderr)


@pytest.mark.skipif(
    not _can_sudo_mount() or BLKID_BIN is None or MKFS_EXT4_BIN is None,
    reason="Kernel loop mount requires passwordless sudo or root",
)
def test_kernel_loop_mount_claim_and_release(tmp_path: Path):
    """When root/passwordless sudo is available, test real ext4 loop mount and umount."""
    host_root = _stage_appliance_host(tmp_path, "loop_host")
    vol_img = tmp_path / "loop-vol.img"
    with open(vol_img, "wb") as fh:
        fh.truncate(64 * 1024 * 1024)
    mnt_dir = tmp_path / "loop_mnt"
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]

    try:
        claim_proc = subprocess.run(
            [
                *prefix,
                "env",
                f"BRAINSOS_REPO_ROOT={host_root}",
                "BRAINSOS_FIRSTBOOT_SKIP_IMDS=true",
                "BRAINSOS_BOOTSTRAP_SKIP_VENV=true",
                "bash",
                str(host_root / "scripts" / "control" / "claim-user-volume.sh"),
                "--device",
                str(vol_img),
                "--mount",
                str(mnt_dir),
                "--skip-service-start",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert claim_proc.returncode == 0, claim_proc.stdout + claim_proc.stderr
        assert (mnt_dir / ".env").is_file()

        rel_proc = subprocess.run(
            [
                *prefix,
                "env",
                f"BRAINSOS_REPO_ROOT={host_root}",
                "bash",
                str(host_root / "scripts" / "control" / "release-user-volume.sh"),
                "--mount",
                str(mnt_dir),
                "--skip-service-stop",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert rel_proc.returncode == 0, rel_proc.stdout + rel_proc.stderr
    finally:
        subprocess.run([*prefix, "umount", "-l", str(mnt_dir)], capture_output=True, check=False)
