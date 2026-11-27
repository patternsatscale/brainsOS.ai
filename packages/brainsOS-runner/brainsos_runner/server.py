"""Server Base SDK for building cognitive runner containers."""

import logging
import os
import secrets
from typing import Awaitable, Callable, Dict, Optional

from fastapi import FastAPI, Header, HTTPException

from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse

logger = logging.getLogger(__name__)

TurnHandler = Callable[[AgentTurnRequest], Awaitable[AgentTurnResponse]]


def create_runner_app(
    handler: TurnHandler,
    title: str = "brainsOS Runner API",
    auth_token: Optional[str] = None,
) -> FastAPI:
    """Create a standardized FastAPI runner application.

    Exposes POST /v1/agent/run (enforcing X-Runner-Token when configured) and GET /healthz.
    """
    app = FastAPI(title=title)

    @app.get("/healthz")
    async def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> Dict[str, str]:
        return {"service": title, "status": "running"}

    @app.post("/v1/agent/run", response_model=AgentTurnResponse)
    async def run_turn(
        request: AgentTurnRequest,
        x_runner_token: Optional[str] = Header(default=None, alias="X-Runner-Token"),
    ) -> AgentTurnResponse:
        expected_token = (auth_token if auth_token is not None else os.getenv("RUNNER_AUTH_TOKEN", "")).strip()
        if not expected_token:
            raise HTTPException(
                status_code=503,
                detail="Service Unavailable: RUNNER_AUTH_TOKEN is not configured",
            )
        provided = (x_runner_token or "").strip()
        if not provided or not secrets.compare_digest(provided, expected_token):
            raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing X-Runner-Token")

        try:
            response = await handler(request)
            return response
        except Exception as exc:
            logger.exception("Error executing turn for run_id %s: %s", request.run_id, exc)
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Internal runner error: {exc}",
            )

    return app
