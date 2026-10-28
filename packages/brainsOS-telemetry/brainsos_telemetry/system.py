import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, Optional

logger = logging.getLogger("brainsos_telemetry.system")

# Locate REPO_ROOT dynamically
def get_repo_root() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current = script_dir
    while current != "/" and os.path.dirname(current) != current:
        if os.path.exists(os.path.join(current, "docker-compose.yml")) or os.path.isdir(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return os.path.abspath(os.path.join(script_dir, "../../../.."))


def get_system_status() -> Dict[str, Any]:
    """Query current platform status and available updates via scripts/control/update.sh."""
    repo_root = get_repo_root()
    update_script = os.path.join(repo_root, "scripts/control/update.sh")

    if os.path.isfile(update_script) and os.access(update_script, os.X_OK):
        import subprocess

        try:
            res = subprocess.run(
                [update_script, "--check", "--json"],
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=15,
            )
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout)
        except Exception as e:
            logger.warning(f"Error querying update.sh: {e}")

    # Fallback status representation if update.sh is unavailable
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
        "overall_update_available": False,
    }


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

    yield f"data: {json.dumps({'type': 'start', 'cmd': ' '.join(cmd), 'status': 'running'})}\n\n"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=repo_root,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        assert proc.stdout is not None
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode(errors="replace").rstrip("\r\n")
            if line:
                payload = json.dumps({"type": "log", "line": line, "status": "running"})
                yield f"data: {payload}\n\n"

        await proc.wait()
        exit_code = proc.returncode or 0

        status = "success" if exit_code == 0 else "failed"
        payload = json.dumps({"type": "complete", "exit_code": exit_code, "status": status})
        yield f"data: {payload}\n\n"

    except Exception as e:
        logger.error(f"Error streaming system update: {e}")
        payload = json.dumps({"type": "error", "line": str(e), "status": "failed"})
        yield f"data: {payload}\n\n"


def create_system_api_app():
    """Create a FastAPI application exposing system telemetry & update management endpoints."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field

    app = FastAPI(
        title="brainsOS System Management & Telemetry API",
        version="0.1.0",
        description="Universal status, version inspection, and live update management API for brainsOS appliances.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class UpdateRequest(BaseModel):
        service: Optional[str] = Field(None, description="Optional targeted service name (e.g. litellm, langfuse)")
        containers_only: bool = Field(False, description="Update upstream containers only without pulling git source")
        full: bool = Field(True, description="Full update including git source code and containers")

    @app.get("/health")
    @app.get("/api/v1/system/health")
    async def health():
        return {"status": "healthy", "service": "brainsos-telemetry-system"}

    @app.get("/api/v1/system/status")
    async def status():
        return JSONResponse(content=get_system_status())

    @app.post("/api/v1/system/update")
    async def trigger_update(req: UpdateRequest):
        return StreamingResponse(
            stream_system_update(
                service=req.service,
                containers_only=req.containers_only,
                full=req.full,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app
