"""Server Base SDK for building cognitive runner containers."""

import logging
from typing import Awaitable, Callable, Dict

from fastapi import FastAPI

from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse

logger = logging.getLogger(__name__)

TurnHandler = Callable[[AgentTurnRequest], Awaitable[AgentTurnResponse]]


def create_runner_app(handler: TurnHandler, title: str = "brainsOS Runner API") -> FastAPI:
    """Create a standardized FastAPI runner application.

    Exposes POST /v1/agent/run and GET /healthz.
    """
    app = FastAPI(title=title)

    @app.get("/healthz")
    async def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> Dict[str, str]:
        return {"service": title, "status": "running"}

    @app.post("/v1/agent/run", response_model=AgentTurnResponse)
    async def run_turn(request: AgentTurnRequest) -> AgentTurnResponse:
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
