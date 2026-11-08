import asyncio
import fcntl
import getpass
import json
import logging
import os
import platform
import pty
import pwd
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import termios
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("brainsos_telemetry.system")

# Active CSRF tokens store (token -> creation_timestamp)
CSRF_TOKENS: Dict[str, float] = {}

ALLOWED_SERVICES = {
    "litellm",
    "langfuse",
    "langfuse-web",
    "caddy",
    "sogo",
    "authentik",
    "authentik-server",
    "authentik-worker",
    "code-server",
    "hermes",
    "hermes-runner",
    "litellm-db",
    "langfuse-db",
    "authentik-db",
    "sogo-db",
    "redis",
    "minio",
}


def issue_csrf_token() -> str:
    """Generate and store an ephemeral CSRF token valid for 1 hour."""
    token = secrets.token_hex(24)
    now = time.time()
    # Prune expired tokens older than 1 hour
    expired = [k for k, v in CSRF_TOKENS.items() if now - v > 3600]
    for k in expired:
        CSRF_TOKENS.pop(k, None)
    CSRF_TOKENS[token] = now
    return token


def validate_csrf_token(token: Optional[str]) -> bool:
    """Check if the provided CSRF token is known and not expired."""
    if not token:
        return False
    now = time.time()
    ts = CSRF_TOKENS.get(token)
    if ts and (now - ts <= 3600):
        return True
    return False


def get_repo_root() -> str:
    """Locate REPO_ROOT dynamically."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current = script_dir
    while current != "/" and os.path.dirname(current) != current:
        if os.path.exists(os.path.join(current, "docker-compose.yml")) or os.path.isdir(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return os.path.abspath(os.path.join(script_dir, "../../../.."))


def get_default_api_host() -> str:
    """Resolve the host IP address for the System API daemon.

    Binds strictly to the Docker bridge gateway / private subnet interface, never 0.0.0.0.
    """
    env_host = os.environ.get("BRAINSOS_SYSTEM_API_HOST")
    if env_host:
        if env_host.strip() in ("0.0.0.0", "::"):
            logger.error("Refusing wildcard BRAINSOS_SYSTEM_API_HOST=%r; falling back to auto-detected gateway.", env_host)
        else:
            return env_host

    # Try docker0 on Linux
    try:
        res = subprocess.run(["ip", "-4", "addr", "show", "docker0"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    ip = line.split()[1].split("/")[0]
                    if ip:
                        return ip
    except Exception:
        pass

    if platform.system() != "Linux":
        return "127.0.0.1"

    # Last resort fallback only when docker0 is missing
    return "172.20.0.1"


class JobManager:
    """Manages single-flight execution, detached subprocesses, and job log streaming."""

    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.jobs_dir = os.path.join(repo_root, "data", "system_jobs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        self.active_job: Optional[Dict[str, Any]] = None
        self._lock = asyncio.Lock()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job status, exit code, and execution logs."""
        if self.active_job and self.active_job["id"] == job_id:
            return self._format_job(self.active_job)

        meta_file = os.path.join(self.jobs_dir, f"{job_id}.json")
        log_file = os.path.join(self.jobs_dir, f"{job_id}.log")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if os.path.isfile(log_file):
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        meta["logs"] = [line.rstrip("\r\n") for line in f]
                else:
                    meta["logs"] = []
                return meta
            except Exception as e:
                logger.warning(f"Error reading job metadata {meta_file}: {e}")
        return None

    def _format_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        log_file = job["log_file"]
        logs = []
        if os.path.isfile(log_file):
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    logs = [line.rstrip("\r\n") for line in f]
            except Exception:
                pass
        return {
            "id": job["id"],
            "type": job["type"],
            "cmd": job["cmd"],
            "status": job["status"],
            "exit_code": job["exit_code"],
            "started_at": job["started_at"],
            "completed_at": job.get("completed_at"),
            "logs": logs,
        }

    async def start_job(
        self,
        job_type: str,
        cmd: list[str],
        extra_env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Attempt to start a single-flight job. Returns 409 conflict if already busy."""
        async with self._lock:
            if self.active_job is not None:
                task: Optional[asyncio.Task] = self.active_job.get("task")
                if task and not task.done():
                    return {
                        "error": "conflict",
                        "active_job_id": self.active_job["id"],
                        "type": self.active_job["type"],
                    }

            job_id = f"job-{int(time.time())}-{secrets.token_hex(4)}"
            log_file = os.path.join(self.jobs_dir, f"{job_id}.log")

            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"--- Job {job_id} ({job_type}) started at {datetime.now(timezone.utc).isoformat()} ---\n")
                f.write(f"Command: {' '.join(cmd)}\n\n")

            job_record: Dict[str, Any] = {
                "id": job_id,
                "type": job_type,
                "cmd": cmd,
                "extra_env": extra_env or {},
                "status": "running",
                "exit_code": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "log_file": log_file,
            }

            task = asyncio.create_task(self._run_detached(job_record))
            job_record["task"] = task
            self.active_job = job_record
            return job_record

    async def _run_detached(self, job_record: Dict[str, Any]):
        """Runs the subprocess decoupled from any HTTP request/client lifecycle."""
        log_file = job_record["log_file"]
        cmd = job_record["cmd"]
        extra_env = job_record.get("extra_env") or {}
        meta_file = os.path.join(self.jobs_dir, f"{job_record['id']}.json")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.repo_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1", **extra_env},
            )

            assert proc.stdout is not None
            with open(log_file, "a", encoding="utf-8", buffering=1) as f:
                while True:
                    line_bytes = await proc.stdout.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode(errors="replace").rstrip("\r\n")
                    f.write(line + "\n")

            await proc.wait()
            exit_code = proc.returncode if proc.returncode is not None else 0
            job_record["exit_code"] = exit_code
            job_record["status"] = "success" if exit_code == 0 else "failed"
            job_record["completed_at"] = datetime.now(timezone.utc).isoformat()

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- Job {job_record['id']} completed with status {job_record['status']} (exit code {exit_code}) at {job_record['completed_at']} ---\n")

        except Exception as e:
            logger.error(f"Error executing detached job {job_record['id']}: {e}")
            job_record["status"] = "failed"
            job_record["exit_code"] = 1
            job_record["completed_at"] = datetime.now(timezone.utc).isoformat()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n[ERROR] Exception executing job: {e}\n")
        finally:
            meta = {
                "id": job_record["id"],
                "type": job_record["type"],
                "cmd": job_record["cmd"],
                "status": job_record["status"],
                "exit_code": job_record["exit_code"],
                "started_at": job_record["started_at"],
                "completed_at": job_record["completed_at"],
            }
            try:
                with open(meta_file, "w", encoding="utf-8") as mf:
                    json.dump(meta, mf, indent=2)
            except Exception as e:
                logger.warning(f"Failed writing meta file {meta_file}: {e}")

            async with self._lock:
                if self.active_job and self.active_job["id"] == job_record["id"]:
                    self.active_job = None


async def stream_job_logs(job_record: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """Streams SSE logs by tailing the persistent job log file."""
    log_file = job_record["log_file"]
    job_id = job_record["id"]

    yield f"data: {json.dumps({'type': 'start', 'job_id': job_id, 'cmd': ' '.join(job_record['cmd']), 'status': 'running'})}\n\n"

    for _ in range(20):
        if os.path.exists(log_file):
            break
        await asyncio.sleep(0.05)

    last_pos = 0
    idle_ticks = 0
    while True:
        emitted_any = False
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_data = f.read()
                last_pos = f.tell()

            if new_data:
                for line in new_data.splitlines():
                    if line:
                        emitted_any = True
                        yield f"data: {json.dumps({'type': 'log', 'job_id': job_id, 'line': line, 'status': 'running'})}\n\n"

        if emitted_any:
            idle_ticks = 0
        else:
            idle_ticks += 1
            if idle_ticks >= 15:
                idle_ticks = 0
                yield ": keepalive\n\n"

        task = job_record.get("task")
        if (task and task.done()) or job_record["status"] in ("success", "failed"):
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_pos)
                    remaining = f.read()
                if remaining:
                    for line in remaining.splitlines():
                        if line:
                            yield f"data: {json.dumps({'type': 'log', 'job_id': job_id, 'line': line, 'status': 'running'})}\n\n"

            status = job_record.get("status", "success")
            exit_code = job_record.get("exit_code", 0)
            yield f"data: {json.dumps({'type': 'complete', 'job_id': job_id, 'exit_code': exit_code, 'status': status})}\n\n"
            break

        await asyncio.sleep(0.2)


async def stream_system_update(
    service: Optional[str] = None,
    version: Optional[str] = None,
    reset_version: bool = False,
    containers_only: bool = False,
    full: bool = False,
    branch: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Execute update.sh and stream output lines as Server-Sent Events (SSE)."""
    repo_root = get_repo_root()
    update_script = os.path.join(repo_root, "scripts/control/update.sh")

    if not os.path.isfile(update_script):
        err_msg = json.dumps({"type": "error", "line": "scripts/control/update.sh not found", "status": "failed"})
        yield f"data: {err_msg}\n\n"
        return

    cmd = [update_script, "--unattended"]
    if service:
        cmd.extend(["--service", service])
        if reset_version:
            cmd.append("--reset-version")
        elif version:
            cmd.extend(["--version", version.strip()])
    elif containers_only:
        cmd.append("--containers-only")
    elif full:
        cmd.append("--full")
        if branch:
            cmd.extend(["--branch", branch.strip()])

    manager = JobManager(repo_root)
    job = await manager.start_job("update", cmd)
    if "error" in job and job["error"] == "conflict":
        err_msg = json.dumps({"type": "error", "line": "Job already in progress", "status": "failed"})
        yield f"data: {err_msg}\n\n"
        return

    async for chunk in stream_job_logs(job):
        yield chunk


async def stream_prune_logs(
    dry_run: bool = False,
    check: bool = False,
    retention_days: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """Execute prune-logs.sh and stream output lines as Server-Sent Events (SSE)."""
    repo_root = get_repo_root()
    prune_script = os.path.join(repo_root, "scripts/control/prune-logs.sh")

    if not os.path.isfile(prune_script):
        err_msg = json.dumps({"type": "error", "line": "scripts/control/prune-logs.sh not found", "status": "failed"})
        yield f"data: {err_msg}\n\n"
        return

    cmd = [prune_script]
    if check:
        cmd.append("--check")
    elif dry_run:
        cmd.append("--dry-run")
    if retention_days:
        cmd.extend(["--retention-days", str(retention_days)])

    manager = JobManager(repo_root)
    job = await manager.start_job("prune", cmd)
    if "error" in job and job["error"] == "conflict":
        err_msg = json.dumps({"type": "error", "line": "Job already in progress", "status": "failed"})
        yield f"data: {err_msg}\n\n"
        return

    async for chunk in stream_job_logs(job):
        yield chunk


def detect_appliance_platform(repo_root: str) -> tuple[str, str]:
    """Detect whether the host is an AWS EC2 AMI, ASUS Ascent GX10, macOS, or Linux host."""
    arch = platform.machine() or "ARM64"
    sys_name = platform.system()
    if sys_name == "Darwin":
        return "macOS Workstation", f"Apple Silicon • {arch}"

    def _read_dmi(field: str) -> str:
        for base in ("/sys/class/dmi/id", "/sys/devices/virtual/dmi/id"):
            p = os.path.join(base, field)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        val = f.read().strip()
                        if val:
                            return val
                except Exception:
                    pass
        return ""

    vendor = _read_dmi("sys_vendor")
    product = _read_dmi("product_name")
    board = _read_dmi("board_name")

    is_aws = (
        "amazon" in vendor.lower()
        or os.path.isfile(os.path.join(repo_root, ".brainsos-initialized"))
        or "compose.appliance.yml" in os.environ.get("COMPOSE_FILE", "")
    )
    if is_aws:
        inst_type = product if product and "amazon" not in product.lower() and "gx10" not in product.lower() else ""
        arch_label = "ARM64 Graviton" if arch in ("aarch64", "arm64") else arch
        detail = f"AWS {arch_label} • {inst_type}" if inst_type else f"AWS {arch_label} • EC2"
        return "AWS EC2 Appliance (AMI)", detail

    if "gx10" in product.lower() or ("asus" in vendor.lower() and "gx10" in board.lower()):
        return "ASUS Ascent GX10", "NVIDIA GB10 ARM64 • 273 GB/s"

    return f"Linux Host ({arch})", f"{sys_name} {arch}"


_IMDS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}


def parse_env_file_only(repo_root: str) -> Dict[str, str]:
    """Read key-value pairs strictly from .env on disk."""
    parsed: Dict[str, str] = {}
    env_path = os.path.join(repo_root, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    parsed[k] = v
        except Exception:
            pass
    return parsed


def parse_env_file(repo_root: str) -> Dict[str, str]:
    """Read key-value pairs from .env on disk, falling back to os.environ."""
    merged: Dict[str, str] = dict(os.environ)
    merged.update(parse_env_file_only(repo_root))
    return merged


def normalize_url_host(raw: str) -> str:
    """Normalize an input URL or hostname (e.g. 'https://host:443/path' -> 'host')."""
    v = (raw or "").strip()
    v = re.sub(r"^https?://", "", v, flags=re.IGNORECASE)
    v = v.split("/")[0]
    v = re.sub(r":[0-9]+$", "", v)
    return v.strip().lower()


def _strip_mail_prefix(domain: str) -> str:
    """Strip a leading 'mail.' subdomain prefix from a hostname/domain."""
    return re.sub(r"^mail\.", "", (domain or "").strip(), flags=re.IGNORECASE)


def _resolve_console_user(su_username: str = "") -> str:
    """Resolve the effective Linux user for the interactive host console."""
    try:
        if os.geteuid() == 0:
            known_users = {p.pw_name for p in pwd.getpwall()}
            if su_username and su_username in known_users:
                return su_username
            if "admin" in known_users:
                return "admin"
    except Exception:
        pass
    try:
        return getpass.getuser()
    except Exception:
        return "admin"


def _query_imds_metadata() -> Dict[str, str]:
    """Query EC2 IMDSv2 for instance-id, public-ipv4, local-ipv4, and public-hostname (cached 60s)."""
    now = time.time()
    if now - _IMDS_CACHE["ts"] < 60.0 and _IMDS_CACHE["data"]:
        return _IMDS_CACHE["data"]

    if os.environ.get("BRAINSOS_STAGE") == "test":
        return {
            "instance_id": os.environ.get("BRAINSOS_TEST_INSTANCE_ID", ""),
            "public_ipv4": os.environ.get("BRAINSOS_TEST_PUBLIC_IPV4", ""),
            "local_ipv4": os.environ.get("BRAINSOS_TEST_LOCAL_IPV4", "127.0.0.1"),
            "public_hostname": os.environ.get("BRAINSOS_TEST_PUBLIC_HOSTNAME", ""),
        }

    result = {"instance_id": "", "public_ipv4": "", "local_ipv4": "", "public_hostname": ""}
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(req, timeout=0.4) as resp:
            token = resp.read().decode("utf-8", errors="ignore").strip()
        if token:
            for key, path in (
                ("instance_id", "instance-id"),
                ("public_ipv4", "public-ipv4"),
                ("local_ipv4", "local-ipv4"),
                ("public_hostname", "public-hostname"),
            ):
                try:
                    mreq = urllib.request.Request(
                        f"http://169.254.169.254/latest/meta-data/{path}",
                        headers={"X-aws-ec2-metadata-token": token},
                    )
                    with urllib.request.urlopen(mreq, timeout=0.4) as mresp:
                        result[key] = mresp.read().decode("utf-8", errors="ignore").strip()
                except Exception:
                    pass
    except Exception:
        pass

    if not result["local_ipv4"]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                result["local_ipv4"] = s.getsockname()[0]
        except Exception:
            result["local_ipv4"] = "127.0.0.1"

    _IMDS_CACHE["ts"] = now
    _IMDS_CACHE["data"] = result
    return result


def validate_password_complexity(
    password: str,
    username: str = "",
    instance_id: str = "",
) -> Optional[str]:
    """Validate superuser/administrator password complexity (#332).

    Returns None when valid, or a descriptive error message when invalid.
    """
    if not password or len(password) < 8 or "\n" in password or "\r" in password:
        return "Password must be at least 8 characters long and contain no control characters."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter (A-Z)."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter (a-z)."
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number (0-9)."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character (e.g. !@#$%^&*)."
    if username and password.strip().lower() == username.strip().lower():
        return "Password must not match the username."
    if instance_id and password.strip().lower() == instance_id.strip().lower():
        return "Password must not equal the EC2 Instance ID."
    return None


def get_host_os_status(repo_root: str) -> Dict[str, Any]:
    """Inspect Host OS distribution, kernel, pending APT security packages, and reboot state (#336)."""
    kernel = platform.release() or "unknown"
    distro = f"{platform.system()} {platform.machine()}"
    os_release_path = os.environ.get("BRAINSOS_OS_RELEASE_FILE", "/etc/os-release")
    if os.path.isfile(os_release_path):
        try:
            with open(os_release_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        distro = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass

    pending_packages = 0
    security_packages = 0
    updates_avail_path = os.environ.get(
        "BRAINSOS_UPDATES_AVAILABLE_FILE", "/var/lib/update-notifier/updates-available"
    )
    if os.path.isfile(updates_avail_path):
        try:
            with open(updates_avail_path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            m_all = re.search(r"(\d+)\s+updates?\s+can\s+be\s+applied", txt, re.IGNORECASE)
            if m_all:
                pending_packages = int(m_all.group(1))
            m_sec = re.search(
                r"(\d+)\s+of\s+these\s+updates?\s+(?:are|is)\s+(?:standard\s+)?security",
                txt,
                re.IGNORECASE,
            )
            if m_sec:
                security_packages = int(m_sec.group(1))
        except Exception:
            pass

    reboot_req_path = os.environ.get("BRAINSOS_REBOOT_REQUIRED_FILE", "/var/run/reboot-required")
    reboot_pkgs_path = os.environ.get("BRAINSOS_REBOOT_PACKAGES_FILE", "/var/run/reboot-required.pkgs")
    reboot_required = os.path.isfile(reboot_req_path)
    reboot_packages: list[str] = []
    if os.path.isfile(reboot_pkgs_path):
        try:
            with open(reboot_pkgs_path, "r", encoding="utf-8", errors="ignore") as f:
                reboot_packages = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        except Exception:
            pass

    unattended_active = os.path.isfile("/etc/apt/apt.conf.d/20auto-upgrades") or os.path.isfile(
        "/etc/apt/apt.conf.d/50unattended-upgrades"
    )
    return {
        "distro": distro,
        "kernel": kernel,
        "pending_packages": pending_packages,
        "security_packages": security_packages,
        "reboot_required": reboot_required,
        "reboot_packages": reboot_packages,
        "unattended_upgrades_active": unattended_active,
    }


def _mask_api_key(val: str) -> Dict[str, Any]:
    """Return boolean configured status and masked prefix without exposing the raw secret."""
    clean = (val or "").strip()
    if not clean:
        return {"configured": False, "masked": ""}
    if len(clean) >= 8:
        masked = f"{clean[:4]}...{clean[-3:]}"
    else:
        masked = "****"
    return {"configured": True, "masked": masked}


def get_runners_status(repo_root: str) -> Dict[str, Any]:
    """Inspect Agent Runners & Tool API Key configuration (#334)."""
    file_env = parse_env_file_only(repo_root)
    env = parse_env_file(repo_root)

    # Also inspect data/runners/hermes/.env if present
    data_dir = file_env.get("BRAINSOS_DATA_DIR") or env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(repo_root, data_dir.lstrip("./"))
    hermes_env_path = os.path.join(data_dir, "runners", "hermes", ".env")
    hermes_env: Dict[str, str] = {}
    if os.path.isfile(hermes_env_path):
        try:
            with open(hermes_env_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    hermes_env[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

    tool_key_names = (
        "FIRECRAWL_API_KEY",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "BRAVE_SEARCH_API_KEY",
    )
    tool_keys: Dict[str, Any] = {}
    for k in tool_key_names:
        raw_val = hermes_env.get(k) or file_env.get(k) or ""
        tool_keys[k] = _mask_api_key(raw_val)

    return {
        "hermes": {
            "id": "hermes-warm",
            "name": "Nous Hermes Warm Runner",
            "container": "brainsos-agent-runner-hermes",
            "endpoint": "http://runner-hermes:8642",
            "dashboard_path": "/runner/",
            "status": "configured",
            "firecrawl_configured": tool_keys["FIRECRAWL_API_KEY"]["configured"],
            "tool_keys": tool_keys,
        },
        "claude": {
            "id": "claude-warm",
            "name": "Anthropic Claude SDK Warm Runner",
            "container": "brainsos-agent-runner-claude",
            "endpoint": "http://runner-claude:8001",
            "status": "configured",
        },
        "openai": {
            "id": "openai-warm",
            "name": "OpenAI SDK Warm Runner",
            "container": "brainsos-agent-runner-openai",
            "endpoint": "http://runner-openai:8002",
            "status": "configured",
        },
        "tool_keys": tool_keys,
    }


def _upsert_env_keys(repo_root: str, target_file: str, updates: Dict[str, str]) -> None:
    """Safely upsert key=value pairs into an .env file with 0600 permissions."""
    os.makedirs(os.path.dirname(os.path.abspath(target_file)), exist_ok=True)
    env_upsert = os.path.join(repo_root, "scripts", "control", "env-upsert.sh")
    if not os.path.isfile(env_upsert):
        fallback_root = get_repo_root()
        candidate = os.path.join(fallback_root, "scripts", "control", "env-upsert.sh")
        if os.path.isfile(candidate):
            env_upsert = candidate

    pairs = [f"{k}={v}" for k, v in updates.items()]
    if os.path.isfile(env_upsert) and os.access(env_upsert, os.X_OK):
        if not os.path.isfile(target_file):
            with open(target_file, "w", encoding="utf-8") as f:
                f.write("")
            os.chmod(target_file, 0o600)
        res = subprocess.run(
            [env_upsert, "--file", target_file, *pairs],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res.returncode == 0:
            return

    existing_lines: list[str] = []
    if os.path.isfile(target_file):
        with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
            existing_lines = f.read().splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in remaining:
                new_lines.append(f"{k}={remaining.pop(k)}")
                continue
        new_lines.append(line)
    for k, v in remaining.items():
        new_lines.append(f"{k}={v}")

    with open(target_file, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    os.chmod(target_file, 0o600)


def get_appliance_identity(repo_root: str) -> Dict[str, Any]:
    """Assemble live Appliance Identity, Custom Domain, TLS & First-Boot Wizard state (#332/#333)."""
    file_env = parse_env_file_only(repo_root)
    env = parse_env_file(repo_root)
    imds = _query_imds_metadata()

    local_domain = _strip_mail_prefix(
        normalize_url_host(
            file_env.get("BRAINSOS_LOCAL_DOMAIN")
            or env.get("BRAINSOS_LOCAL_DOMAIN")
            or file_env.get("BRAINSOS_MAIL_DOMAIN")
            or file_env.get("BRAINSOS_DOMAIN")
            or env.get("BRAINSOS_DOMAIN")
            or "local.brainsos.ai"
        )
    )
    url = _strip_mail_prefix(
        normalize_url_host(
            file_env.get("BRAINSOS_URL")
            or env.get("BRAINSOS_URL")
            or file_env.get("BRAINSOS_DOMAIN")
            or env.get("BRAINSOS_DOMAIN")
            or imds.get("public_hostname")
            or imds.get("public_ipv4")
            or "local.brainsos.ai"
        )
    )
    raw_mail_dom = (file_env.get("BRAINSOS_MAIL_DOMAIN") or env.get("BRAINSOS_MAIL_DOMAIN") or "").strip()
    if raw_mail_dom and raw_mail_dom.lower().startswith("mail."):
        mail_domain = raw_mail_dom
    else:
        mail_domain = f"mail.{local_domain}"

    raw_data_dir = file_env.get("BRAINSOS_DATA_DIR") or env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")
    if not os.path.isabs(raw_data_dir):
        data_dir = os.path.abspath(os.path.join(repo_root, raw_data_dir))
    else:
        data_dir = os.path.abspath(raw_data_dir)

    unit_name = (
        file_env.get("BRAINSOS_UNIT_NAME")
        or env.get("BRAINSOS_UNIT_NAME")
        or "Enterprise Agent Box"
    ).strip() or "Enterprise Agent Box"
    superuser_name = file_env.get("BRAINSOS_SUPERUSER_NAME") or env.get("BRAINSOS_SUPERUSER_NAME") or ""
    raw_su = (
        file_env.get("BRAINSOS_SUPERUSER_USERNAME")
        or env.get("BRAINSOS_SUPERUSER_USERNAME")
        or file_env.get("BRAINSOS_ADMIN_USERNAME")
        or ""
    ).strip()
    superuser_username = "" if raw_su.lower() == "admin" else raw_su
    admin_username = (
        superuser_username
        or file_env.get("BRAINSOS_ADMIN_USERNAME")
        or env.get("BRAINSOS_ADMIN_USERNAME")
        or "admin"
    )
    if "BRAINSOS_ADMIN_EMAIL" in file_env and file_env["BRAINSOS_ADMIN_EMAIL"]:
        raw_adm_email = file_env["BRAINSOS_ADMIN_EMAIL"]
        if "@" in raw_adm_email:
            eu, ed = raw_adm_email.split("@", 1)
            admin_email = f"{eu}@{_strip_mail_prefix(ed)}"
        else:
            admin_email = raw_adm_email
    elif "BRAINSOS_LOCAL_DOMAIN" in file_env or "BRAINSOS_ADMIN_USERNAME" in file_env or "BRAINSOS_SUPERUSER_USERNAME" in file_env:
        admin_email = f"{admin_username}@{local_domain}"
    else:
        admin_email = env.get("BRAINSOS_ADMIN_EMAIL") or f"{admin_username}@{local_domain}"
        if "@" in admin_email:
            eu, ed = admin_email.split("@", 1)
            admin_email = f"{eu}@{_strip_mail_prefix(ed)}"
    tls_mode = env.get("BRAINSOS_TLS_MODE") or (
        "route53" if env.get("ACME_DNS_PROVIDER") == "route53" else "internal"
    )
    acme_email = env.get("ACME_EMAIL") or ""

    cloud_cfg_dir = env.get("BRAINSOS_CLOUD_CFG_DIR") or "/etc/cloud/cloud.cfg.d"
    preserve_cfg_path = os.path.join(cloud_cfg_dir, "99-brainsos-hostname.cfg")
    preserve_hostname = False
    if os.path.isfile(preserve_cfg_path):
        try:
            with open(preserve_cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                preserve_hostname = "preserve_hostname: true" in f.read()
        except Exception:
            pass

    wizard_flag = os.path.join(repo_root, ".brainsos-wizard-completed")
    init_flag = os.path.join(repo_root, ".brainsos-initialized")
    force_wizard = env.get("BRAINSOS_APPLIANCE_FORCE_WIZARD", "").lower() == "true"
    env_wizard = file_env.get("BRAINSOS_WIZARD_COMPLETED", "").strip().lower()

    if os.path.isfile(wizard_flag) or env_wizard == "true":
        firstboot_wizard_completed = True
    elif force_wizard or env_wizard == "false" or os.path.isfile(init_flag):
        firstboot_wizard_completed = False
    else:
        firstboot_wizard_completed = True

    try:
        os_hostname = _strip_mail_prefix(socket.getfqdn() or socket.gethostname())
    except Exception:
        os_hostname = local_domain

    masked_instance_id = imds.get("instance_id", "")
    if not firstboot_wizard_completed and masked_instance_id:
        masked_instance_id = ""

    su_prefix = superuser_username.lower() if superuser_username else "username"
    suggested_local_domain = f"{su_prefix}.aws.cloud.brainsos.ai"
    console_user = _resolve_console_user(superuser_username)

    return {
        "firstboot_wizard_completed": firstboot_wizard_completed,
        "unit_name": unit_name,
        "url": url,
        "local_domain": local_domain,
        "mail_domain": mail_domain,
        "suggested_local_domain": suggested_local_domain,
        "superuser_name": superuser_name,
        "superuser_username": superuser_username,
        "admin_username": admin_username,
        "admin_email": admin_email,
        "admin_bound_to_instance_id": True,
        "tls_mode": tls_mode,
        "acme_email": acme_email,
        "hostname": os_hostname,
        "preserve_hostname": preserve_hostname,
        "public_ipv4": imds.get("public_ipv4", ""),
        "local_ipv4": imds.get("local_ipv4", ""),
        "instance_id": masked_instance_id,
        "repo_root": str(repo_root),
        "data_dir": str(data_dir),
        "console_user": console_user,
    }


def get_system_status() -> Dict[str, Any]:
    """Query current platform status and available updates via scripts/control/update.sh."""
    repo_root = get_repo_root()
    update_script = os.path.join(repo_root, "scripts/control/update.sh")
    identity = get_appliance_identity(repo_root)
    runners_info = get_runners_status(repo_root)
    os_info = get_host_os_status(repo_root)

    if os.path.isfile(update_script) and os.access(update_script, os.X_OK):
        try:
            res = subprocess.run(
                [update_script, "--check", "--json"],
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=15,
            )
            if res.returncode == 0 and res.stdout.strip():
                status = json.loads(res.stdout)
                if "disk" in status:
                    if "platform_name" not in status:
                        pname, pdetail = detect_appliance_platform(repo_root)
                        status["platform_name"] = pname
                        status["platform_detail"] = pdetail
                    if "os" not in status:
                        status["os"] = os_info
                    status["runners"] = runners_info
                    status.update(identity)
                    status["identity"] = identity
                    return status
        except Exception as e:
            logger.warning(f"Error querying update.sh: {e}")

    try:
        total, used, free = shutil.disk_usage(repo_root)
        disk_info = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "free_pct": round((free / total) * 100.0, 1),
            "warning": (free / total) < 0.15,
        }
    except Exception:
        disk_info = {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "free_pct": 100.0,
            "warning": False,
        }

    platform_name, platform_detail = detect_appliance_platform(repo_root)
    base_status: Dict[str, Any] = {
        "platform": "brainsOS",
        "platform_name": platform_name,
        "platform_detail": platform_detail,
        "git": {
            "is_git": os.path.isdir(os.path.join(repo_root, ".git")),
            "branch": "unknown",
            "current_commit": "unknown",
            "remote_commit": "unknown",
            "commits_behind": 0,
            "update_available": False,
        },
        "services": {},
        "disk": disk_info,
        "os": os_info,
        "runners": runners_info,
        "overall_update_available": False,
        "identity": identity,
    }
    base_status.update(identity)
    return base_status


def verify_internal_auth(request: Request):
    """Enforce shared internal secret injected by Caddy reverse proxy (Rule 2)."""
    expected_token = os.environ.get("SYSTEM_API_TOKEN")
    if not expected_token:
        # Fails closed in production if token is unconfigured
        if os.environ.get("BRAINSOS_STAGE") == "test":
            return
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: SYSTEM_API_TOKEN is not configured on the host",
        )

    provided = request.headers.get("X-BrainsOS-Internal")
    valid_tokens = {expected_token}
    try:
        disk_token = parse_env_file_only(get_repo_root()).get("SYSTEM_API_TOKEN", "").strip()
        if disk_token:
            valid_tokens.add(disk_token)
    except Exception:
        pass
    if not provided or not any(secrets.compare_digest(provided, tok) for tok in valid_tokens if tok):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid or missing internal system API token",
        )


def verify_state_change_security(request: Request):
    """Enforce CSRF token, Origin check, and Authentik identity on state-changing endpoints."""
    # 1. Authentik identity header
    username = (
        request.headers.get("X-Authentik-Username")
        or request.headers.get("X-Authentik-Email")
        or request.headers.get("Remote-User")
    )
    if not username:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: missing authenticated identity header (X-Authentik-Username)",
        )

    # 2. Sec-Fetch-Site check
    sec_fetch_site = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site and sec_fetch_site.lower() == "cross-site":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: cross-site requests rejected",
        )

    # 3. Origin check
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlparse(origin)
        origin_host = parsed.hostname or ""
        req_host = request.headers.get("Host", "").split(":")[0]
        env = parse_env_file(get_repo_root())
        domain = normalize_url_host(env.get("BRAINSOS_DOMAIN", "localhost"))
        url_host = normalize_url_host(env.get("BRAINSOS_URL", domain))
        local_dom = normalize_url_host(env.get("BRAINSOS_LOCAL_DOMAIN", domain))
        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            domain.lower(),
            url_host.lower(),
            local_dom.lower(),
            f"proxy.{domain.lower()}",
            req_host.lower(),
        }
        if origin_host.lower() not in allowed_hosts:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: Origin '{origin}' is not permitted",
            )

    # 4. CSRF Token check
    csrf_token = request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(csrf_token):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: missing or invalid CSRF token",
        )


def verify_setup_security(request: Request):
    """Enforce CSRF token, Origin check, and either Authentik SSO identity or Pre-Login First-Boot Wizard mode."""
    repo_root = get_repo_root()
    ident = get_appliance_identity(repo_root)
    username = (
        request.headers.get("X-Authentik-Username")
        or request.headers.get("X-Authentik-Email")
        or request.headers.get("Remote-User")
    )
    if not username and ident.get("firstboot_wizard_completed", True):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: missing authenticated identity header (X-Authentik-Username)",
        )

    sec_fetch_site = request.headers.get("Sec-Fetch-Site")
    if sec_fetch_site and sec_fetch_site.lower() == "cross-site":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: cross-site requests rejected",
        )

    origin = request.headers.get("Origin")
    if origin:
        parsed = urlparse(origin)
        origin_host = parsed.hostname or ""
        req_host = request.headers.get("Host", "").split(":")[0]
        env = parse_env_file(repo_root)
        domain = normalize_url_host(env.get("BRAINSOS_DOMAIN", "localhost"))
        url_host = normalize_url_host(env.get("BRAINSOS_URL", domain))
        local_dom = normalize_url_host(env.get("BRAINSOS_LOCAL_DOMAIN", domain))
        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            domain.lower(),
            url_host.lower(),
            local_dom.lower(),
            f"proxy.{domain.lower()}",
            req_host.lower(),
        }
        if origin_host.lower() not in allowed_hosts:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: Origin '{origin}' is not permitted",
            )

    csrf_token = request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(csrf_token):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: missing or invalid CSRF token",
        )


def create_system_api_app():
    """Create a hardened FastAPI application exposing system telemetry & update management endpoints."""
    repo_root = get_repo_root()
    job_manager = JobManager(repo_root)

    app = FastAPI(
        title="brainsOS System Management & Telemetry API",
        version="0.1.0",
        description="Universal status, version inspection, and live update management API for brainsOS appliances.",
    )

    class UpdateRequest(BaseModel):
        service: Optional[str] = Field(None, description="Optional targeted service name (e.g. litellm, langfuse)")
        version: Optional[str] = Field(None, description="Optional target upstream image version tag (e.g. 1.108.0)")
        reset_version: bool = Field(False, description="Remove .env version override and restore default image tag")
        containers_only: bool = Field(False, description="Update upstream containers only without pulling git source")
        full: bool = Field(True, description="Full update including git source code and containers")
        branch: Optional[str] = Field(None, description="Optional target git branch name (e.g. main, task/320-appliance-rehearsal)")

    class PruneRequest(BaseModel):
        dry_run: bool = Field(False, description="Simulate actions without deleting")
        check: bool = Field(False, description="Audit disk and log usage only")
        retention_days: Optional[int] = Field(None, description="Retention days")

    class DnsCheckRequest(BaseModel):
        domain: str = Field(..., description="Domain or URL to verify DNS resolution against this appliance")

    class SetupRequest(BaseModel):
        bootstrap_token: Optional[str] = Field(None, description="EC2 Instance ID / initial bootstrap password for pre-login first-boot verification")
        unit_name: Optional[str] = Field(default=None, description="Logical unit display name for this appliance")
        local_domain: Optional[str] = Field(None, description="Coherent unit FQDN & local mail domain (BRAINSOS_LOCAL_DOMAIN)")
        superuser_name: Optional[str] = Field(None, description="Superuser full display name (BRAINSOS_SUPERUSER_NAME)")
        superuser_username: Optional[str] = Field(None, description="Named superuser username (BRAINSOS_SUPERUSER_USERNAME)")
        superuser_password: Optional[str] = Field(None, description="Named superuser password (never logged)")
        admin_username: Optional[str] = Field(None, description="Primary administrator username (alias for superuser_username)")
        admin_password: Optional[str] = Field(None, description="New primary administrator password (alias for superuser_password)")
        url: Optional[str] = Field(None, description="External web access URL or hostname (BRAINSOS_URL)")
        tls_mode: Optional[str] = Field("internal", description="TLS mode: internal, acme, public_acme, or route53")
        acme_email: Optional[str] = Field(None, description="ACME contact email for Let's Encrypt / Route 53")
        mark_wizard_completed: bool = Field(True, description="Mark First-Boot Setup Wizard as completed")
        dismiss_only: bool = Field(False, description="Only dismiss the First-Boot Setup Wizard without reconfiguring")
        dry_run: bool = Field(False, description="Simulate configuration without modifying disk or restarting services")
        force: bool = Field(True, description="Proceed even if DNS pre-flight check warns")

    class HermesConfigRequest(BaseModel):
        keys: Optional[Dict[str, str]] = Field(default=None, description="Map of tool API keys (e.g. FIRECRAWL_API_KEY)")
        firecrawl_api_key: Optional[str] = Field(None, description="Firecrawl API key for web scraping")
        tavily_api_key: Optional[str] = Field(None, description="Tavily Search API key")
        exa_api_key: Optional[str] = Field(None, description="Exa Search API key")
        brave_search_api_key: Optional[str] = Field(None, description="Brave Search API key")
        brave_api_key: Optional[str] = Field(None, description="Alias for Brave Search API key")
        github_token: Optional[str] = Field(None, description="Optional GitHub token")
        extra_env: Optional[Dict[str, str]] = Field(default=None, description="Additional environment overrides")
        restart_runner: Optional[bool] = Field(True, description="Restart runner-hermes container after saving keys")

    class OsUpgradeRequest(BaseModel):
        dry_run: bool = Field(False, description="Simulate APT upgrade without modifying packages")

    class RebootRequest(BaseModel):
        dry_run: bool = Field(False, description="Simulate graceful stop and host reboot")
        confirm: bool = Field(True, description="Operator confirmation")

    class TerminalExecRequest(BaseModel):
        command: str = Field(..., description="Shell command to execute in host console")
        cwd: Optional[str] = Field(None, description="Working directory (defaults to REPO_ROOT)")

    @app.get("/health")
    @app.get("/api/v1/system/health")
    async def health():
        return {"status": "healthy", "service": "brainsos-telemetry-system"}

    @app.get("/api/v1/system/csrf", dependencies=[Depends(verify_internal_auth)])
    async def get_csrf():
        token = issue_csrf_token()
        response = JSONResponse(content={"csrf_token": token})
        response.set_cookie(
            key="brainsos_csrf_token",
            value=token,
            httponly=True,
            samesite="strict",
            secure=True,
        )
        return response

    @app.get("/api/v1/system/status", dependencies=[Depends(verify_internal_auth)])
    async def status():
        return JSONResponse(content=get_system_status())

    @app.get("/api/v1/system/identity", dependencies=[Depends(verify_internal_auth)])
    async def identity():
        return JSONResponse(content=get_appliance_identity(repo_root))

    @app.get("/api/v1/system/me", dependencies=[Depends(verify_internal_auth)])
    async def current_user_me(request: Request):
        ident = get_appliance_identity(repo_root)
        hdr_username = (
            request.headers.get("X-Authentik-Username")
            or request.headers.get("Remote-User")
            or ""
        ).strip()
        hdr_name = (request.headers.get("X-Authentik-Name") or "").strip()
        hdr_email = (request.headers.get("X-Authentik-Email") or "").strip()

        username = str(hdr_username or ident.get("superuser_username") or ident.get("admin_username") or "admin")
        if hdr_name:
            name = hdr_name
        elif username == ident.get("superuser_username") and ident.get("superuser_name"):
            name = str(ident.get("superuser_name"))
        elif username.lower() == "admin":
            name = str(ident.get("superuser_name") or "Appliance Administrator")
        else:
            name = str(ident.get("superuser_name") or username)

        local_dom = ident.get("local_domain") or "brainsos.ai"
        email = hdr_email or f"{username}@{local_dom}"
        return JSONResponse(
            content={
                "username": username,
                "name": name,
                "email": email,
                "is_superuser": True,
            }
        )

    @app.post("/api/v1/system/dns-check", dependencies=[Depends(verify_internal_auth)])
    async def dns_check(req: DnsCheckRequest):
        host = normalize_url_host(req.domain)
        fqdn_re = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
        valid_syntax = bool(fqdn_re.match(host))
        ident = get_appliance_identity(repo_root)
        pub_ip = ident.get("public_ipv4") or ""
        loc_ip = ident.get("local_ipv4") or ""

        if not valid_syntax:
            return JSONResponse(
                content={
                    "domain": host,
                    "valid_syntax": False,
                    "resolved_ip": None,
                    "public_ipv4": pub_ip,
                    "matches_appliance": False,
                    "message": f"Invalid fully qualified domain name: '{host}'",
                }
            )

        resolved_ip: Optional[str] = None
        try:
            resolved_ip = socket.gethostbyname(host)
        except Exception:
            resolved_ip = None

        if not resolved_ip:
            return JSONResponse(
                content={
                    "domain": host,
                    "valid_syntax": True,
                    "resolved_ip": None,
                    "public_ipv4": pub_ip,
                    "matches_appliance": False,
                    "message": f"Domain '{host}' does not resolve to an IPv4 address yet.",
                }
            )

        matches = bool((pub_ip and resolved_ip == pub_ip) or (loc_ip and resolved_ip == loc_ip))
        if matches:
            msg = f"DNS verified: {host} resolves to this appliance ({resolved_ip})."
        elif pub_ip:
            msg = f"{host} resolves to {resolved_ip} (appliance public IPv4 is {pub_ip})."
        else:
            msg = f"{host} resolves to {resolved_ip}."

        return JSONResponse(
            content={
                "domain": host,
                "valid_syntax": True,
                "resolved_ip": resolved_ip,
                "public_ipv4": pub_ip,
                "matches_appliance": matches,
                "message": msg,
            }
        )

    @app.post(
        "/api/v1/system/setup",
        dependencies=[Depends(verify_internal_auth), Depends(verify_setup_security)],
    )
    @app.post(
        "/api/v1/system/domain",
        dependencies=[Depends(verify_internal_auth), Depends(verify_setup_security)],
    )
    @app.post(
        "/api/v1/system/identity",
        dependencies=[Depends(verify_internal_auth), Depends(verify_setup_security)],
    )
    async def trigger_setup(req: SetupRequest, request: Request):
        ident = get_appliance_identity(repo_root)
        env = parse_env_file(repo_root)
        has_sso = bool(
            request.headers.get("X-Authentik-Username")
            or request.headers.get("X-Authentik-Email")
            or request.headers.get("Remote-User")
        )

        # In pre-login First-Boot Setup Wizard mode (or whenever bootstrap_token is provided),
        # verify the EC2 Instance ID / initial bootstrap password before allowing any changes.
        if not has_sso or (req.bootstrap_token is not None and req.bootstrap_token.strip() != ""):
            provided_token = (req.bootstrap_token or "").strip()
            expected_pw = env.get("BRAINSOS_ADMIN_PASSWORD", "").strip()
            raw_imds = _query_imds_metadata()
            expected_iid = (raw_imds.get("instance_id") or "").strip()
            matched = bool(
                provided_token
                and (
                    (expected_pw and secrets.compare_digest(provided_token, expected_pw))
                    or (expected_iid and secrets.compare_digest(provided_token, expected_iid))
                )
            )
            if not matched:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid EC2 Instance ID bootstrap token. Enter the exact Instance ID (i-...) of this EC2 appliance to authorize initial setup.",
                )

        if req.dismiss_only:
            wizard_flag = os.path.join(repo_root, ".brainsos-wizard-completed")
            try:
                with open(wizard_flag, "w", encoding="utf-8") as f:
                    f.write(datetime.now(timezone.utc).isoformat() + "\n")
                env_upsert = os.path.join(repo_root, "scripts/control/env-upsert.sh")
                env_file = os.path.join(repo_root, ".env")
                if os.path.isfile(env_upsert) and os.path.isfile(env_file):
                    subprocess.run([env_upsert, "--file", env_file, "BRAINSOS_WIZARD_COMPLETED=true"], check=False, timeout=5)
                if os.environ.get("BRAINSOS_STAGE") != "test":
                    subprocess.Popen(
                        ["docker", "compose", "up", "-d", "caddy"],
                        cwd=repo_root,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed writing wizard completion flag: {e}")
            return JSONResponse(content={"status": "dismissed", "firstboot_wizard_completed": True})

        fqdn_re = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
        ipv4_re = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")

        unit_name: Optional[str] = None
        if req.unit_name is not None and req.unit_name.strip():
            unit_name = req.unit_name.strip()
            if "\n" in unit_name or "\r" in unit_name or len(unit_name) > 128:
                raise HTTPException(status_code=400, detail="Invalid unit_name.")

        # Fast-path: When saving ONLY unit_name from the System & Identity card, update .env
        # directly without running set-domain.sh or restarting Caddy/Authentik containers.
        is_unit_name_only = bool(
            unit_name
            and not (req.url and req.url.strip())
            and not (req.local_domain and req.local_domain.strip())
            and not (req.superuser_name and req.superuser_name.strip())
            and not (req.superuser_username and req.superuser_username.strip())
            and not (req.superuser_password and req.superuser_password.strip())
            and not (req.admin_username and req.admin_username.strip())
            and not (req.admin_password and req.admin_password.strip())
            and not (req.acme_email and req.acme_email.strip())
        )
        if is_unit_name_only:
            env_upsert = os.path.join(repo_root, "scripts/control/env-upsert.sh")
            env_file = os.path.join(repo_root, ".env")
            try:
                if os.path.isfile(env_upsert) and os.path.isfile(env_file):
                    subprocess.run(
                        [env_upsert, "--file", env_file, f"BRAINSOS_UNIT_NAME={unit_name}"],
                        check=True,
                        timeout=5,
                    )
                else:
                    with open(env_file, "a", encoding="utf-8") as f:
                        f.write(f'\nBRAINSOS_UNIT_NAME="{unit_name}"\n')
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed updating BRAINSOS_UNIT_NAME: {e}")
            updated_ident = get_appliance_identity(repo_root)
            return JSONResponse(
                content={
                    "status": "updated",
                    "unit_name": unit_name,
                    "identity": updated_ident,
                }
            )

        superuser_name: Optional[str] = None
        if req.superuser_name is not None and req.superuser_name.strip():
            superuser_name = req.superuser_name.strip()
            if "\n" in superuser_name or "\r" in superuser_name or len(superuser_name) > 128:
                raise HTTPException(status_code=400, detail="Invalid superuser_name.")

        if req.superuser_username is not None and req.superuser_username.strip().lower() == "admin":
            raise HTTPException(
                status_code=400,
                detail="Superuser username cannot be 'admin' (the 'admin' account is permanently bound to the EC2 Instance ID).",
            )

        raw_username = req.superuser_username if (req.superuser_username and req.superuser_username.strip()) else req.admin_username
        admin_username: Optional[str] = None
        if raw_username is not None and raw_username.strip():
            admin_username = raw_username.strip()
            if not re.match(r"^[a-zA-Z0-9._-]{2,64}$", admin_username):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid username '{raw_username}'. Use 2-64 alphanumeric, dot, underscore, or hyphen characters.",
                )

        local_domain: Optional[str] = None
        if req.local_domain is not None and req.local_domain.strip():
            local_domain = _strip_mail_prefix(normalize_url_host(req.local_domain))
            if not fqdn_re.match(local_domain):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid local_domain '{req.local_domain}'. Must be a valid FQDN (e.g. jsm.aws.cloud.brainsos.ai).",
                )
        elif admin_username and admin_username.lower() != "admin":
            if ident.get("local_domain") in ("local.brainsos.ai", "admin.aws.cloud.brainsos.ai"):
                local_domain = f"{admin_username.lower()}.aws.cloud.brainsos.ai"

        raw_password = req.superuser_password if (req.superuser_password is not None and req.superuser_password != "") else req.admin_password
        if raw_password is not None and raw_password != "":
            raw_imds = _query_imds_metadata()
            inst_id = (raw_imds.get("instance_id") or env.get("BRAINSOS_INSTANCE_ID") or "").strip()
            pw_err = validate_password_complexity(raw_password, username=admin_username or "", instance_id=inst_id)
            if pw_err:
                raise HTTPException(status_code=400, detail=pw_err)

        ident = get_appliance_identity(repo_root)
        target_url = _strip_mail_prefix(normalize_url_host(req.url)) if (req.url and req.url.strip()) else ident["url"]
        if not (fqdn_re.match(target_url) or ipv4_re.match(target_url) or target_url == "localhost"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid external URL / hostname '{req.url}'.",
            )

        tls_mode = (req.tls_mode or "internal").strip().lower()
        if tls_mode == "public_acme":
            tls_mode = "acme"
        if tls_mode not in ("internal", "acme", "route53"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tls_mode '{req.tls_mode}'. Must be one of: internal, acme, public_acme, route53.",
            )

        acme_email = (req.acme_email or "").strip()
        if tls_mode in ("acme", "route53"):
            if not acme_email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", acme_email):
                raise HTTPException(
                    status_code=400,
                    detail="A valid ACME contact email address is required for public ACME or Route 53 TLS modes.",
                )

        set_domain_script = os.path.join(repo_root, "scripts/control/set-domain.sh")
        if not os.path.isfile(set_domain_script):
            raise HTTPException(status_code=500, detail="scripts/control/set-domain.sh not found")

        cmd = [set_domain_script, "--url", target_url]
        if unit_name:
            cmd.extend(["--unit-name", unit_name])
        if local_domain:
            cmd.extend(["--local-domain", local_domain])
        if superuser_name:
            cmd.extend(["--superuser-name", superuser_name])
        if admin_username:
            cmd.extend(["--admin-username", admin_username])
        if tls_mode == "internal":
            cmd.append("--internal")
        elif tls_mode == "route53":
            cmd.extend(["--dns", "route53", "--email", acme_email])
        else:
            cmd.extend(["--email", acme_email])

        if req.mark_wizard_completed:
            cmd.append("--mark-wizard-completed")
        if req.force:
            cmd.append("--force")
        if req.dry_run:
            cmd.append("--dry-run")

        extra_env: Dict[str, str] = {}
        if raw_password:
            extra_env["BRAINSOS_NEW_ADMIN_PASSWORD"] = raw_password
            extra_env["BRAINSOS_NEW_SUPERUSER_PASSWORD"] = raw_password
        if superuser_name:
            extra_env["BRAINSOS_SUPERUSER_NAME"] = superuser_name
        if unit_name:
            extra_env["BRAINSOS_UNIT_NAME"] = unit_name

        job = await job_manager.start_job("setup", cmd, extra_env=extra_env)
        if "error" in job and job["error"] == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A system job is already in progress",
                    "active_job_id": job["active_job_id"],
                    "type": job["type"],
                },
            )

        return StreamingResponse(
            stream_job_logs(job),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Job-ID": job["id"],
            },
        )

    @app.get("/api/v1/system/jobs/{job_id}", dependencies=[Depends(verify_internal_auth)])
    async def get_job_status(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        return JSONResponse(content=job)

    @app.get("/api/v1/system/jobs/{job_id}/stream", dependencies=[Depends(verify_internal_auth)])
    async def stream_job_reattach(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        job_record = {
            "id": job["id"],
            "log_file": os.path.join(job_manager.jobs_dir, f"{job_id}.log"),
            "cmd": job.get("cmd", []),
            "status": job.get("status", "running"),
            "exit_code": job.get("exit_code"),
            "task": None,
        }
        return StreamingResponse(
            stream_job_logs(job_record),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(
        "/api/v1/system/update",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def trigger_update(req: UpdateRequest):
        if req.service is not None and req.service.lower() not in ALLOWED_SERVICES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid service '{req.service}'. Must be one of declared compose services: {sorted(list(ALLOWED_SERVICES))}",
            )

        if req.version is not None:
            ver = req.version.strip()
            if not ver or ver.startswith("-") or not re.match(r"^[A-Za-z0-9._-]+$", ver):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid version tag '{req.version}'. Must be a valid alphanumeric version identifier.",
                )

        if req.branch is not None:
            br = req.branch.strip()
            if not br or br.startswith("-") or ".." in br or not re.match(r"^[A-Za-z0-9._/-]+$", br):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid branch name '{req.branch}'. Must be a valid git branch identifier.",
                )

        update_script = os.path.join(repo_root, "scripts/control/update.sh")
        if not os.path.isfile(update_script):
            raise HTTPException(status_code=500, detail="scripts/control/update.sh not found")

        cmd = [update_script, "--unattended"]
        if req.service:
            cmd.extend(["--service", req.service.lower()])
            if req.reset_version:
                cmd.append("--reset-version")
            elif req.version:
                cmd.extend(["--version", req.version.strip()])
        elif req.containers_only:
            cmd.append("--containers-only")
        elif req.full:
            cmd.append("--full")
            if req.branch:
                cmd.extend(["--branch", req.branch.strip()])

        job = await job_manager.start_job("update", cmd)
        if "error" in job and job["error"] == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A system job is already in progress",
                    "active_job_id": job["active_job_id"],
                    "type": job["type"],
                },
            )

        return StreamingResponse(
            stream_job_logs(job),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Job-ID": job["id"],
            },
        )

    @app.post(
        "/api/v1/system/prune-logs",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def trigger_prune(req: PruneRequest):
        prune_script = os.path.join(repo_root, "scripts/control/prune-logs.sh")
        if not os.path.isfile(prune_script):
            raise HTTPException(status_code=500, detail="scripts/control/prune-logs.sh not found")

        cmd = [prune_script]
        if req.check:
            cmd.append("--check")
        elif req.dry_run:
            cmd.append("--dry-run")
        if req.retention_days:
            cmd.extend(["--retention-days", str(req.retention_days)])

        job = await job_manager.start_job("prune", cmd)
        if "error" in job and job["error"] == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A system job is already in progress",
                    "active_job_id": job["active_job_id"],
                    "type": job["type"],
                },
            )

        return StreamingResponse(
            stream_job_logs(job),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Job-ID": job["id"],
            },
        )

    @app.get("/api/v1/system/runners", dependencies=[Depends(verify_internal_auth)])
    async def list_runners():
        return JSONResponse(content=get_runners_status(repo_root))

    @app.post(
        "/api/v1/system/runners/hermes/config",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def update_hermes_config(req: HermesConfigRequest):
        updates: Dict[str, str] = {}
        key_map = {
            "FIRECRAWL_API_KEY": req.firecrawl_api_key,
            "TAVILY_API_KEY": req.tavily_api_key,
            "EXA_API_KEY": req.exa_api_key,
            "BRAVE_SEARCH_API_KEY": req.brave_search_api_key if req.brave_search_api_key is not None else req.brave_api_key,
            "GITHUB_TOKEN": req.github_token,
        }
        for env_key, raw_val in key_map.items():
            if raw_val is not None:
                val = raw_val.strip()
                if "\n" in val or "\r" in val:
                    raise HTTPException(status_code=400, detail=f"Invalid value for {env_key}")
                updates[env_key] = val

        for dict_field in (req.keys, req.extra_env):
            if dict_field:
                for env_key, raw_val in dict_field.items():
                    if raw_val is None:
                        continue
                    k = env_key.strip()
                    if not re.match(r"^[A-Z0-9_]{2,64}$", k):
                        raise HTTPException(status_code=400, detail=f"Invalid key name '{env_key}'")
                    val = str(raw_val).strip()
                    if "\n" in val or "\r" in val:
                        raise HTTPException(status_code=400, detail=f"Invalid value for {k}")
                    updates[k] = val

        if not updates:
            raise HTTPException(status_code=400, detail="No runner tool keys provided to update")

        env_file = os.path.join(repo_root, ".env")
        _upsert_env_keys(repo_root, env_file, updates)

        file_env = parse_env_file_only(repo_root)
        data_dir = file_env.get("BRAINSOS_DATA_DIR") or os.path.join(repo_root, "data")
        if not os.path.isabs(data_dir):
            data_dir = os.path.join(repo_root, data_dir.lstrip("./"))
        hermes_env_path = os.path.join(data_dir, "runners", "hermes", ".env")
        _upsert_env_keys(repo_root, hermes_env_path, updates)

        if (req.restart_runner is not False) and os.environ.get("BRAINSOS_STAGE") != "test":
            try:
                subprocess.Popen(
                    ["docker", "compose", "up", "-d", "runner-hermes"],
                    cwd=repo_root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                logger.warning(f"Failed restarting runner-hermes: {e}")

        return JSONResponse(content={"status": "updated", "runners": get_runners_status(repo_root)})

    @app.post(
        "/api/v1/system/os-upgrade",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def trigger_os_upgrade(req: OsUpgradeRequest):
        update_script = os.path.join(repo_root, "scripts/control/update.sh")
        if not os.path.isfile(update_script):
            raise HTTPException(status_code=500, detail="scripts/control/update.sh not found")

        cmd = [update_script, "--os-only", "--unattended"]
        if req.dry_run:
            cmd.append("--dry-run")

        job = await job_manager.start_job("os-upgrade", cmd)
        if "error" in job and job["error"] == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A system job is already in progress",
                    "active_job_id": job["active_job_id"],
                    "type": job["type"],
                },
            )

        return StreamingResponse(
            stream_job_logs(job),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Job-ID": job["id"],
            },
        )

    @app.post(
        "/api/v1/system/reboot",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def trigger_reboot(req: RebootRequest):
        if not req.confirm:
            raise HTTPException(status_code=400, detail="Reboot confirmation required")

        reboot_script = os.path.join(repo_root, "scripts/control/reboot-appliance.sh")
        if not os.path.isfile(reboot_script):
            fallback_script = os.path.join(get_repo_root(), "scripts/control/reboot-appliance.sh")
            if os.path.isfile(fallback_script):
                reboot_script = fallback_script
            else:
                raise HTTPException(status_code=500, detail="scripts/control/reboot-appliance.sh not found")

        cmd = [reboot_script, "--unattended"]
        if req.dry_run or os.environ.get("BRAINSOS_STAGE") == "test":
            cmd.append("--dry-run")

        job = await job_manager.start_job("reboot", cmd)
        if "error" in job and job["error"] == "conflict":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "A system job is already in progress",
                    "active_job_id": job["active_job_id"],
                    "type": job["type"],
                },
            )

        return StreamingResponse(
            stream_job_logs(job),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Job-ID": job["id"],
            },
        )

    @app.post(
        "/api/v1/system/terminal/exec",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def terminal_exec(req: TerminalExecRequest):
        cmd_str = (req.command or "").strip()
        if not cmd_str:
            raise HTTPException(status_code=400, detail="Command cannot be empty")
        work_dir = repo_root
        if req.cwd and os.path.isdir(req.cwd):
            work_dir = os.path.abspath(req.cwd)

        env = {**os.environ, **parse_env_file_only(repo_root), "TERM": "xterm-256color"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                f"{cmd_str}\nprintf '\\n__BRAINSOS_CWD__=%s\\n' \"$(pwd)\"",
                cwd=work_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            stdout_txt = stdout_b.decode("utf-8", errors="replace")
            stderr_txt = stderr_b.decode("utf-8", errors="replace")
            new_cwd = work_dir
            if "__BRAINSOS_CWD__=" in stdout_txt:
                parts = stdout_txt.rsplit("__BRAINSOS_CWD__=", 1)
                stdout_txt = parts[0].rstrip("\n")
                detected = parts[1].strip()
                if detected and os.path.isdir(detected):
                    new_cwd = detected
            return JSONResponse(
                content={
                    "stdout": stdout_txt,
                    "stderr": stderr_txt,
                    "exit_code": proc.returncode or 0,
                    "cwd": new_cwd,
                }
            )
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=408,
                content={"stdout": "", "stderr": "Command timed out after 30 seconds.", "exit_code": 124, "cwd": work_dir},
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Terminal execution failed: {e}")

    @app.websocket("/api/v1/system/terminal/ws")
    async def terminal_ws(websocket: WebSocket):
        expected_token = os.environ.get("SYSTEM_API_TOKEN")
        provided_internal = websocket.headers.get("X-BrainsOS-Internal") or websocket.query_params.get("internal_token")
        if expected_token and os.environ.get("BRAINSOS_STAGE") != "test":
            valid_tokens = {expected_token}
            try:
                disk_token = parse_env_file_only(repo_root).get("SYSTEM_API_TOKEN", "").strip()
                if disk_token:
                    valid_tokens.add(disk_token)
            except Exception:
                pass
            if not provided_internal or not any(secrets.compare_digest(provided_internal, tok) for tok in valid_tokens if tok):
                await websocket.close(code=1008)
                return
        elif provided_internal and expected_token and not secrets.compare_digest(provided_internal, expected_token):
            await websocket.close(code=1008)
            return

        username = (
            websocket.headers.get("X-Authentik-Username")
            or websocket.headers.get("X-Authentik-Email")
            or websocket.headers.get("Remote-User")
        )
        if not username:
            if os.environ.get("BRAINSOS_STAGE") == "test" and not provided_internal:
                await websocket.close(code=1008)
                return
            username = os.environ.get("BRAINSOS_SUPERUSER_USERNAME") or "admin"

        await websocket.accept()
        ident = get_appliance_identity(repo_root)
        work_dir = repo_root if os.path.isdir(repo_root) else ("/opt/brainsos" if os.path.isdir("/opt/brainsos") else "/")
        data_dir = ident.get("data_dir") or os.path.join(work_dir, "data")
        console_user = ident.get("console_user") or username

        master_fd, slave_fd = pty.openpty()
        shell_bin = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
        env = {
            **os.environ,
            **parse_env_file_only(repo_root),
            "TERM": "xterm-256color",
            "PS1": r"\u@\h:\w\$ ",
            "BRAINSOS_HOME": str(work_dir),
            "BRAINSOS_DATA_DIR": str(data_dir),
            "PWD": str(work_dir),
        }

        target_pw = None
        if os.geteuid() == 0:
            for candidate in (ident.get("superuser_username") or "", "admin"):
                if not candidate:
                    continue
                try:
                    target_pw = pwd.getpwnam(candidate)
                    break
                except KeyError:
                    continue

        if target_pw is not None:
            env["HOME"] = target_pw.pw_dir
            env["USER"] = target_pw.pw_name
            env["LOGNAME"] = target_pw.pw_name
            console_user = target_pw.pw_name

            def _preexec():
                os.setsid()
                try:
                    os.initgroups(target_pw.pw_name, target_pw.pw_gid)
                    os.setgid(target_pw.pw_gid)
                    os.setuid(target_pw.pw_uid)
                except Exception:
                    pass
        else:
            def _preexec():
                os.setsid()

        spawn_cwd = work_dir
        if target_pw is not None and not os.access(work_dir, os.R_OK | os.X_OK):
            spawn_cwd = target_pw.pw_dir if os.path.isdir(target_pw.pw_dir) else "/"

        proc = subprocess.Popen(
            [shell_bin, "-i"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=spawn_cwd,
            env=env,
            preexec_fn=_preexec,
            close_fds=True,
        )
        os.close(slave_fd)

        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        stop_event = asyncio.Event()

        async def _pty_reader():
            while not stop_event.is_set():
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    await websocket.send_text(
                        json.dumps({"type": "output", "data": data.decode("utf-8", errors="replace")})
                    )
                except BlockingIOError:
                    if proc.poll() is not None:
                        break
                    await asyncio.sleep(0.03)
                except Exception:
                    break

        reader_task = asyncio.create_task(_pty_reader())
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "ready",
                        "cwd": work_dir,
                        "user": username,
                        "console_user": console_user,
                        "hostname": ident.get("local_domain") or socket.getfqdn(),
                    }
                )
            )
            banner = (
                f"\r\n\x1b[1;36mbrainsOS Appliance Host Console\x1b[0m"
                f" • Source: \x1b[1;32m{work_dir}\x1b[0m"
                f" • Data: \x1b[1;32m{data_dir}\x1b[0m\r\n"
            )
            await websocket.send_text(json.dumps({"type": "output", "data": banner}))
            while True:
                raw_msg = await websocket.receive_text()
                try:
                    msg = json.loads(raw_msg)
                except Exception:
                    msg = {"type": "input", "data": raw_msg}

                mtype = msg.get("type", "input")
                if mtype == "input":
                    inp = str(msg.get("data", ""))
                    if inp:
                        os.write(master_fd, inp.encode("utf-8"))
                elif mtype == "resize":
                    cols = max(20, min(500, int(msg.get("cols", 120))))
                    rows = max(5, min(200, int(msg.get("rows", 32))))
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                elif mtype == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            stop_event.set()
            reader_task.cancel()
            try:
                os.close(master_fd)
            except Exception:
                pass
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

    return app


def main():
    """Console entrypoint for brainsos-system-api."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="brainsOS System Management & Telemetry API")
    parser.add_argument("--host", default=None, help="Host to bind to (defaults to Docker bridge gateway)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: 8010)")
    args, _ = parser.parse_known_args()

    host = args.host or get_default_api_host()
    port = args.port or int(os.environ.get("BRAINSOS_SYSTEM_API_PORT", "8010"))
    logger.info(f"Starting brainsOS System API daemon on http://{host}:{port}")
    uvicorn.run("brainsos_telemetry.system:create_system_api_app", host=host, port=port, factory=True, log_level="info")


if __name__ == "__main__":
    main()
