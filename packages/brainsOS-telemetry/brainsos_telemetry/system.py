import asyncio
import json
import logging
import os
import platform
import secrets
import shutil
import subprocess
import time
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

    # Default appliance bridge gateway
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

    async def start_job(self, job_type: str, cmd: list[str]) -> Dict[str, Any]:
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
        meta_file = os.path.join(self.jobs_dir, f"{job_record['id']}.json")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.repo_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
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
    containers_only: bool = False,
    full: bool = False,
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
    elif containers_only:
        cmd.append("--containers-only")
    elif full:
        cmd.append("--full")

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


def get_system_status() -> Dict[str, Any]:
    """Query current platform status and available updates via scripts/control/update.sh."""
    repo_root = get_repo_root()
    update_script = os.path.join(repo_root, "scripts/control/update.sh")

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

    return {
        "platform": "brainsOS",
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
    }


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
        domain = os.environ.get("BRAINSOS_DOMAIN", "localhost")
        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            domain.lower(),
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
        containers_only: bool = Field(False, description="Update upstream containers only without pulling git source")
        full: bool = Field(True, description="Full update including git source code and containers")

    class PruneRequest(BaseModel):
        dry_run: bool = Field(False, description="Simulate actions without deleting")
        check: bool = Field(False, description="Audit disk and log usage only")
        retention_days: Optional[int] = Field(None, description="Retention days")

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

        update_script = os.path.join(repo_root, "scripts/control/update.sh")
        if not os.path.isfile(update_script):
            raise HTTPException(status_code=500, detail="scripts/control/update.sh not found")

        cmd = [update_script, "--unattended"]
        if req.service:
            cmd.extend(["--service", req.service.lower()])
        elif req.containers_only:
            cmd.append("--containers-only")
        elif req.full:
            cmd.append("--full")

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
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: 8000)")
    args, _ = parser.parse_known_args()

    host = args.host or get_default_api_host()
    port = args.port or int(os.environ.get("BRAINSOS_SYSTEM_API_PORT", "8000"))
    logger.info(f"Starting brainsOS System API daemon on http://{host}:{port}")
    uvicorn.run("brainsos_telemetry.system:create_system_api_app", host=host, port=port, factory=True, log_level="info")


if __name__ == "__main__":
    main()
