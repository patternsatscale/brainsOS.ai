"""Unit and integration tests for B2 (Ticket #330): System API bind IP and Caddy reachability."""

import os
import platform
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
from brainsos_telemetry.system import get_default_api_host

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "env-upsert.sh", root / "scripts" / "control")
    shutil.copy2(FIRSTBOOT, root / "packages" / "brainsOS-appliance" / "scripts")
    shutil.copy2(REPO_ROOT / ".env.example", root)
    _git(root, "init", "--quiet")
    return root


def _run_firstboot(root: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(root),
        "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
        "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
    }
    return subprocess.run(
        ["bash", str(root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_firstboot_does_not_pin_system_api_host(firstboot_tree: Path):
    """First boot must not write an active BRAINSOS_SYSTEM_API_HOST= assignment."""
    proc = _run_firstboot(firstboot_tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    env_lines = (firstboot_tree / ".env").read_text(encoding="utf-8").splitlines()
    active_host_lines = [
        ln for ln in env_lines
        if not ln.lstrip().startswith("#") and ln.lstrip().startswith("BRAINSOS_SYSTEM_API_HOST=")
    ]
    assert active_host_lines == []


def test_env_example_does_not_pin_system_api_host():
    """.env.example must have no uncommented BRAINSOS_SYSTEM_API_HOST= line."""
    env_lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    active_host_lines = [
        ln for ln in env_lines
        if not ln.lstrip().startswith("#") and ln.lstrip().startswith("BRAINSOS_SYSTEM_API_HOST=")
    ]
    assert active_host_lines == []


def test_default_bind_rejects_wildcard(monkeypatch: pytest.MonkeyPatch):
    """Wildcard bind addresses (0.0.0.0, ::) are rejected and fall through to auto-detection."""
    monkeypatch.setenv("BRAINSOS_SYSTEM_API_HOST", "0.0.0.0")
    host = get_default_api_host()
    assert host not in ("0.0.0.0", "::")


@pytest.mark.skipif(
    platform.system() != "Linux" or shutil.which("docker") is None,
    reason="Requires Linux + docker",
)
def test_container_reaches_default_bind_address(monkeypatch: pytest.MonkeyPatch):
    """A container with host.docker.internal:host-gateway can reach a listener bound to get_default_api_host()."""
    monkeypatch.delenv("BRAINSOS_SYSTEM_API_HOST", raising=False)
    bind_ip = get_default_api_host()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_ip, 0))
    except OSError as exc:
        srv.close()
        pytest.skip(f"Cannot bind to {bind_ip}: {exc}")

    port = srv.getsockname()[1]
    srv.listen(1)
    srv.settimeout(10)

    def _accept_once() -> None:
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept_once, daemon=True)
    t.start()

    try:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--add-host",
                "host.docker.internal:host-gateway",
                "alpine",
                "nc",
                "-z",
                "-w",
                "3",
                "host.docker.internal",
                str(port),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        srv.close()
        t.join(timeout=2)

