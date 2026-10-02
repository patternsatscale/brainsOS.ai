"""Unit tests for WarmHttpRunnerClient and server SDK."""

from typing import List

import httpx
import pytest
from brainsos_runner.clients.http import WarmHttpRunnerClient
from brainsos_runner.models import (
    AgentTurnRequest,
    AgentTurnResponse,
    ChatMessage,
    ExecutionMetrics,
    ToolCallRecord,
)
from brainsos_runner.server import create_runner_app


@pytest.fixture
def sample_request() -> AgentTurnRequest:
    return AgentTurnRequest(
        run_id="run-test-01",
        agent_id="marvin",
        model="hermes-3-llama-3.1-8b",
        system_prompt="You are Marvin.",
        conversation=[
            ChatMessage(role="user", content="Calculate 2 + 2"),
        ],
        workspace_dir="/tmp/test_workspace",
        timeout_sec=5,
    )


@pytest.mark.asyncio
async def test_successful_turn(sample_request: AgentTurnRequest):
    async def sample_handler(req: AgentTurnRequest) -> AgentTurnResponse:
        return AgentTurnResponse(
            run_id=req.run_id,
            status="completed",
            output_text="The answer is 4.",
            tool_calls=[
                ToolCallRecord(
                    id="call-01",
                    tool_name="calculator",
                    arguments={"expr": "2 + 2"},
                    output="4",
                )
            ],
            metrics=ExecutionMetrics(prompt_tokens=15, completion_tokens=8, duration_ms=120),
        )

    app = create_runner_app(sample_handler, title="Test Runner")
    transport = httpx.ASGITransport(app=app)

    async with WarmHttpRunnerClient(
        endpoint="http://runner-test",
        transport=transport,
    ) as client:
        # Check healthz
        assert await client.check_health() is True

        # Execute turn
        response = await client.execute_turn(sample_request)
        assert response.run_id == sample_request.run_id
        assert response.status == "completed"
        assert response.output_text == "The answer is 4."
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].tool_name == "calculator"
        assert response.metrics.prompt_tokens == 15


@pytest.mark.asyncio
async def test_server_unhandled_exception(sample_request: AgentTurnRequest):
    async def failing_handler(req: AgentTurnRequest) -> AgentTurnResponse:
        raise RuntimeError("Unexpected engine crash")

    app = create_runner_app(failing_handler)
    transport = httpx.ASGITransport(app=app)

    async with WarmHttpRunnerClient(
        endpoint="http://runner-test",
        transport=transport,
    ) as client:
        response = await client.execute_turn(sample_request)
        assert response.run_id == sample_request.run_id
        assert response.status == "failed"
        assert "Unexpected engine crash" in (response.error_message or "")


@pytest.mark.asyncio
async def test_client_timeout_enforcement(sample_request: AgentTurnRequest):
    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Server timed out")

    client_timeout = WarmHttpRunnerClient(
        endpoint="http://runner-test",
        transport=TimeoutTransport(),
    )
    resp = await client_timeout.execute_turn(sample_request)
    assert resp.status == "timed_out"
    assert "timed out" in (resp.error_message or "").lower()


@pytest.mark.asyncio
async def test_retry_transient_502_503(sample_request: AgentTurnRequest):
    attempts: List[int] = []

    class FlakyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                return httpx.Response(status_code=503, text="Service Unavailable", request=request)
            # 3rd attempt succeeds
            return httpx.Response(
                status_code=200,
                json=AgentTurnResponse(
                    run_id=sample_request.run_id,
                    status="completed",
                    output_text="Recovered from 503",
                ).model_dump(mode="json"),
                request=request,
            )

    client = WarmHttpRunnerClient(
        endpoint="http://runner-flaky",
        max_retries=3,
        backoff_factor=0.01,
        transport=FlakyTransport(),
    )
    resp = await client.execute_turn(sample_request)
    assert resp.status == "completed"
    assert resp.output_text == "Recovered from 503"
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_retries_exhausted(sample_request: AgentTurnRequest):
    class Always502Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=502, text="Bad Gateway", request=request)

    client = WarmHttpRunnerClient(
        endpoint="http://runner-dead",
        max_retries=2,
        backoff_factor=0.01,
        transport=Always502Transport(),
    )
    resp = await client.execute_turn(sample_request)
    assert resp.status == "failed"
    assert "502" in (resp.error_message or "")


@pytest.mark.asyncio
async def test_health_check_failure():
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

    client = WarmHttpRunnerClient(
        endpoint="http://unreachable",
        transport=FailingTransport(),
    )
    assert await client.check_health() is False
