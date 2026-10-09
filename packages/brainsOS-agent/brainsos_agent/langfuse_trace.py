"""Worker-side Langfuse trace for each email run (Ticket #295).

Hermes' Langfuse plugin emits ``Hermes turn`` traces (LLM calls, tool calls) and LiteLLM emits
generation traces; both carry the canonical session id. Neither knows *who sent the email* or
*which agent persona* handled it, and a run that fails before any LLM call leaves no trace at all.

This module posts one ``email-run`` trace per inbound email into the same Langfuse session with:
``user_id`` = sender, agent identity tags, run status, and an ERROR-level observation when the run
did not complete. It uses the public ingestion API over HTTP (no SDK dependency) and never raises.
"""

from __future__ import annotations

import datetime
import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger("brainsos_agent.langfuse")

_MAX_TEXT = 8000


def _iso(ts: float | None) -> str:
    ts = ts if ts is not None else datetime.datetime.now(datetime.timezone.utc).timestamp()
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…[truncated]"


def langfuse_settings() -> tuple[str, str, str] | None:
    """Returns (base_url, public_key, secret_key) or None when Langfuse is not configured."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key or os.getenv("BRAINSOS_MAIL_TRACE_ENABLED", "true").lower() == "false":
        return None
    base_url = (
        os.getenv("BRAINSOS_LANGFUSE_URL") or f"http://127.0.0.1:{os.getenv('LANGFUSE_PORT', '3001')}"
    ).rstrip("/")
    return base_url, public_key, secret_key


def build_mail_run_batch(
    *,
    session_id: str,
    agent_id: str,
    agent_name: str,
    sender: str,
    subject: str,
    run_id: str | None,
    status: str,
    input_text: str | None,
    output_text: str | None,
    error: str | None,
    usage: dict[str, Any] | None,
    started_at: float | None,
    ended_at: float | None,
) -> list[dict[str, Any]]:
    """Builds the Langfuse ingestion batch (trace-create + span-create) for one email run."""
    trace_id = uuid.uuid4().hex
    failed = status != "completed"
    tags = ["brainsos-mail", f"agent:{agent_id}", f"status:{status}"]
    metadata = {"agent_id": agent_id, "agent_name": agent_name, "run_id": run_id, "subject": subject}
    now = _iso(ended_at)
    return [
        {
            "id": uuid.uuid4().hex,
            "type": "trace-create",
            "timestamp": now,
            "body": {
                "id": trace_id,
                "timestamp": _iso(started_at),
                "name": f"email-run {agent_name}",
                "sessionId": session_id,
                "userId": sender,
                "input": _truncate(input_text),
                "output": _truncate(output_text),
                "tags": tags,
                "metadata": metadata,
            },
        },
        {
            "id": uuid.uuid4().hex,
            "type": "span-create",
            "timestamp": now,
            "body": {
                "id": uuid.uuid4().hex,
                "traceId": trace_id,
                "name": "hermes-run",
                "startTime": _iso(started_at),
                "endTime": now,
                "level": "ERROR" if failed else "DEFAULT",
                "statusMessage": _truncate(error) if failed else None,
                "input": _truncate(input_text),
                "output": _truncate(output_text),
                "metadata": {"run_id": run_id, "status": status, "usage": usage or {}},
            },
        },
    ]


try:
    import importlib.metadata
    _SDK_VERSION = importlib.metadata.version("langfuse")
except Exception:
    _SDK_VERSION = "4.17.0"


async def record_mail_run_trace(http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> bool:
    """Best-effort POST of the email-run trace. Returns True on 2xx/207, never raises."""
    settings = langfuse_settings()
    if settings is None:
        return False
    base_url, public_key, secret_key = settings
    try:
        batch = build_mail_run_batch(**kwargs)
        headers = {
            "X-Langfuse-Sdk-Name": "python",
            "X-Langfuse-Sdk-Version": _SDK_VERSION,
            "X-Langfuse-Public-Key": public_key,
        }
        client = http_client or httpx.AsyncClient()
        try:
            resp = await client.post(
                f"{base_url}/api/public/ingestion",
                json={"batch": batch},
                headers=headers,
                auth=(public_key, secret_key),
                timeout=10.0,
            )
        finally:
            if http_client is None:
                await client.aclose()
        if resp.status_code in (200, 201, 207):
            return True
        logger.warning("Langfuse ingestion returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Failed to record email-run trace in Langfuse: %s", e)
    return False
