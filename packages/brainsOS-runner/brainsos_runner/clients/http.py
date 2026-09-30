"""Warm HTTP Runner Client for resident cognitive containers."""

import asyncio
import logging
from typing import Optional

import httpx

from brainsos_runner.clients.base import RunnerClient
from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse

logger = logging.getLogger(__name__)


class WarmHttpRunnerClient(RunnerClient):
    """Client for dispatching cognitive turns to warm HTTP runner services."""

    def __init__(
        self,
        endpoint: str,
        default_timeout_sec: int = 120,
        max_retries: int = 3,
        backoff_factor: float = 0.1,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.default_timeout_sec = default_timeout_sec
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(self.default_timeout_sec),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client session."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "WarmHttpRunnerClient":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.aclose()

    async def check_health(self) -> bool:
        """Verify the healthz status of the target runner endpoint."""
        url = f"{self.endpoint}/healthz"
        try:
            client = await self._get_client()
            resp = await client.get(url, timeout=5.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Runner health check failed for %s: %s", url, exc)
            return False

    async def execute_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        """Dispatch an AgentTurnRequest to POST /v1/agent/run with retries and timeout enforcement."""
        url = f"{self.endpoint}/v1/agent/run"
        timeout_sec = request.timeout_sec or self.default_timeout_sec
        client = await self._get_client()
        payload = request.model_dump(mode="json")

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=httpx.Timeout(timeout_sec),
                )

                # Check for transient gateway/server errors eligible for retry
                if response.status_code in {502, 503, 504}:
                    if attempt < self.max_retries:
                        sleep_time = self.backoff_factor * (2**attempt)
                        logger.warning(
                            "Runner returned %d on %s (attempt %d/%d), retrying in %.2fs",
                            response.status_code,
                            url,
                            attempt + 1,
                            self.max_retries,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)
                        continue
                    else:
                        return AgentTurnResponse(
                            run_id=request.run_id,
                            status="failed",
                            output_text="",
                            error_message=f"Runner returned HTTP {response.status_code}: {response.text}",
                        )

                if response.status_code != 200:
                    return AgentTurnResponse(
                        run_id=request.run_id,
                        status="failed",
                        output_text="",
                        error_message=f"Runner returned HTTP {response.status_code}: {response.text}",
                    )

                data = response.json()
                return AgentTurnResponse.model_validate(data)

            except (httpx.TimeoutException, asyncio.TimeoutError):
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="timed_out",
                    output_text="",
                    error_message=f"Turn execution timed out after {timeout_sec}s",
                )
            except (httpx.ConnectError, httpx.RemoteProtocolError) as err:
                if attempt < self.max_retries:
                    sleep_time = self.backoff_factor * (2**attempt)
                    logger.warning(
                        "Connection error on %s (attempt %d/%d): %s. Retrying in %.2fs",
                        url,
                        attempt + 1,
                        self.max_retries,
                        err,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="failed",
                    output_text="",
                    error_message=f"Connection failed after {self.max_retries} retries: {err}",
                )
            except Exception as exc:
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="failed",
                    output_text="",
                    error_message=f"Unexpected error executing turn: {exc}",
                )

        return AgentTurnResponse(
            run_id=request.run_id,
            status="failed",
            output_text="",
            error_message="Exhausted maximum retry attempts",
        )
