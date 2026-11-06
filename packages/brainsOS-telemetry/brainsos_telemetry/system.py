import asyncio
import json
import logging
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
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
    while True:
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_data = f.read()
                last_pos = f.tell()

            if new_data:
                for line in new_data.splitlines():
                    if line:
                        yield f"data: {json.dumps({'type': 'log', 'job_id': job_id, 'line': line, 'status': 'running'})}\n\n"

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


def get_appliance_identity(repo_root: str) -> Dict[str, Any]:
    """Assemble live Appliance Identity, Custom Domain, TLS & First-Boot Wizard state (#332/#333)."""
    file_env = parse_env_file_only(repo_root)
    env = parse_env_file(repo_root)
    imds = _query_imds_metadata()

    local_domain = (
        file_env.get("BRAINSOS_LOCAL_DOMAIN")
        or env.get("BRAINSOS_LOCAL_DOMAIN")
        or file_env.get("BRAINSOS_MAIL_DOMAIN")
        or file_env.get("BRAINSOS_DOMAIN")
        or env.get("BRAINSOS_DOMAIN")
        or "local.brainsos.ai"
    )
    url = normalize_url_host(
        file_env.get("BRAINSOS_URL")
        or env.get("BRAINSOS_URL")
        or file_env.get("BRAINSOS_DOMAIN")
        or env.get("BRAINSOS_DOMAIN")
        or imds.get("public_hostname")
        or imds.get("public_ipv4")
        or "local.brainsos.ai"
    )
    admin_username = file_env.get("BRAINSOS_ADMIN_USERNAME") or env.get("BRAINSOS_ADMIN_USERNAME") or "admin"
    if "BRAINSOS_ADMIN_EMAIL" in file_env and file_env["BRAINSOS_ADMIN_EMAIL"]:
        admin_email = file_env["BRAINSOS_ADMIN_EMAIL"]
    elif "BRAINSOS_LOCAL_DOMAIN" in file_env or "BRAINSOS_ADMIN_USERNAME" in file_env:
        admin_email = f"{admin_username}@{local_domain}"
    else:
        admin_email = env.get("BRAINSOS_ADMIN_EMAIL") or f"{admin_username}@{local_domain}"
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

    if os.path.isfile(wizard_flag):
        firstboot_wizard_completed = True
    elif force_wizard or os.path.isfile(init_flag):
        firstboot_wizard_completed = False
    else:
        firstboot_wizard_completed = True

    try:
        os_hostname = socket.getfqdn() or socket.gethostname()
    except Exception:
        os_hostname = local_domain

    return {
        "firstboot_wizard_completed": firstboot_wizard_completed,
        "url": url,
        "local_domain": local_domain,
        "admin_username": admin_username,
        "admin_email": admin_email,
        "tls_mode": tls_mode,
        "acme_email": acme_email,
        "hostname": os_hostname,
        "preserve_hostname": preserve_hostname,
        "public_ipv4": imds.get("public_ipv4", ""),
        "local_ipv4": imds.get("local_ipv4", ""),
        "instance_id": imds.get("instance_id", ""),
    }


def get_system_status() -> Dict[str, Any]:
    """Query current platform status and available updates via scripts/control/update.sh."""
    repo_root = get_repo_root()
    update_script = os.path.join(repo_root, "scripts/control/update.sh")
    identity = get_appliance_identity(repo_root)

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
    if not provided or not secrets.compare_digest(provided, expected_token):
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
        local_domain: Optional[str] = Field(None, description="Coherent unit FQDN & local mail domain (BRAINSOS_LOCAL_DOMAIN)")
        admin_username: Optional[str] = Field(None, description="Primary administrator username (BRAINSOS_ADMIN_USERNAME)")
        admin_password: Optional[str] = Field(None, description="New primary administrator password (never logged)")
        url: Optional[str] = Field(None, description="External web access URL or hostname (BRAINSOS_URL)")
        tls_mode: Optional[str] = Field("internal", description="TLS mode: internal, acme, public_acme, or route53")
        acme_email: Optional[str] = Field(None, description="ACME contact email for Let's Encrypt / Route 53")
        mark_wizard_completed: bool = Field(True, description="Mark First-Boot Setup Wizard as completed")
        dismiss_only: bool = Field(False, description="Only dismiss the First-Boot Setup Wizard without reconfiguring")
        dry_run: bool = Field(False, description="Simulate configuration without modifying disk or restarting services")
        force: bool = Field(True, description="Proceed even if DNS pre-flight check warns")

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
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    @app.post(
        "/api/v1/system/domain",
        dependencies=[Depends(verify_internal_auth), Depends(verify_state_change_security)],
    )
    async def trigger_setup(req: SetupRequest):
        if req.dismiss_only:
            wizard_flag = os.path.join(repo_root, ".brainsos-wizard-completed")
            try:
                with open(wizard_flag, "w", encoding="utf-8") as f:
                    f.write(datetime.now(timezone.utc).isoformat() + "\n")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed writing wizard completion flag: {e}")
            return JSONResponse(content={"status": "dismissed", "firstboot_wizard_completed": True})

        fqdn_re = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
        ipv4_re = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")

        local_domain: Optional[str] = None
        if req.local_domain is not None and req.local_domain.strip():
            local_domain = normalize_url_host(req.local_domain)
            if not fqdn_re.match(local_domain):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid local_domain '{req.local_domain}'. Must be a valid FQDN (e.g. jsm.cloud.aws.brainsos.ai).",
                )

        admin_username: Optional[str] = None
        if req.admin_username is not None and req.admin_username.strip():
            admin_username = req.admin_username.strip()
            if not re.match(r"^[a-zA-Z0-9._-]{2,64}$", admin_username):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid admin_username '{req.admin_username}'. Use 2-64 alphanumeric, dot, underscore, or hyphen characters.",
                )

        if req.admin_password is not None and req.admin_password != "":
            if len(req.admin_password) < 8 or "\n" in req.admin_password or "\r" in req.admin_password:
                raise HTTPException(
                    status_code=400,
                    detail="Administrator password must be at least 8 characters long.",
                )

        ident = get_appliance_identity(repo_root)
        target_url = normalize_url_host(req.url) if (req.url and req.url.strip()) else ident["url"]
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
        if local_domain:
            cmd.extend(["--local-domain", local_domain])
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
        if req.admin_password:
            extra_env["BRAINSOS_NEW_ADMIN_PASSWORD"] = req.admin_password

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
