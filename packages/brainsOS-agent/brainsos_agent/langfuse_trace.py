"""Worker-side Langfuse observation for each email run (Tickets #295, #299).

Hermes' ``observability/langfuse`` plugin owns the agent timeline: it records one ``Hermes turn``
per run (LLM calls, tool calls) on a trace whose id is derived deterministically from the session
(``create_trace_id(seed=f"{session_id}::{task_id}")``; the ``/v1/runs`` API sets
``task_id = session_id``). Every email in a thread therefore lands on the same **thread trace**.

Hermes does not know *who sent the email*, *which persona* handled it, or whether the worker had to
send a failure reply, and a run that fails before any LLM call leaves no trace at all. This module
adds exactly one ``email-run`` span per inbound email to that same thread trace so the Langfuse
timeline shows the full email -> run -> reply sequence in one place, with:

* ``user.id`` = sender, ``session.id`` = canonical thread session, agent/status tags,
* the email body / reply recorded once (on the span, not repeated at trace level),
* ``ERROR`` level + status message when the run did not complete.

Spans are exported as OTLP/HTTP JSON to ``/api/public/otel/v1/traces`` with
``x-langfuse-ingestion-version: 4`` (Langfuse v4 native ingestion). The legacy
``/api/public/ingestion`` batch API is intentionally not used. No SDK dependency; never raises.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Any

import httpx

logger = logging.getLogger("brainsos_agent.langfuse")

_MAX_TEXT = 8000
_SCOPE_NAME = "brainsos-agent"
_SERVICE_NAME = "brainsos-agent-worker"
_OTLP_TRACES_PATH = "/api/public/otel/v1/traces"
_INGESTION_VERSION_HEADER = "x-langfuse-ingestion-version"

# OTLP enums (opentelemetry-proto): SpanKind INTERNAL = 1; StatusCode UNSET = 0, ERROR = 2.
_SPAN_KIND_INTERNAL = 1
_STATUS_UNSET = 0
_STATUS_ERROR = 2


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…[truncated]"


def _to_unix_nano(ts: float | None) -> str:
    ts = ts if ts is not None else time.time()
    return str(int(ts * 1_000_000_000))


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


def thread_trace_id(session_id: str) -> str:
    """The Langfuse trace id Hermes uses for a ``/v1/runs`` session (one trace per email thread).

    Mirrors ``Langfuse.create_trace_id(seed=...)`` (sha256 of the seed, first 16 bytes, hex) with the
    Hermes plugin seed ``f"{session_id}::{task_id}"`` where ``task_id == session_id`` for runs.
    """
    seed = f"{session_id or 'sessionless'}::{session_id or 'sessionless'}"
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16].hex()


def _attr(key: str, value: Any) -> dict[str, Any] | None:
    """One OTLP KeyValue; ``None`` values are dropped, lists become string arrays."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, (list, tuple)):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    return {"key": key, "value": {"stringValue": value}}


def build_email_run_otlp(
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
) -> dict[str, Any]:
    """Builds the OTLP/JSON ``ExportTraceServiceRequest`` with one ``email-run`` span on the thread trace."""
    failed = status != "completed"
    end_ts = ended_at if ended_at is not None else time.time()
    start_ts = started_at if started_at is not None else end_ts
    clean_subj = (subject or "").strip()
    trace_name = f"brainsos: email: {clean_subj[:120]}" if clean_subj else f"brainsos: email: {agent_id}"
    candidates = [
        # Trace-level attributes (names the root trace after the brainsOS event).
        _attr("langfuse.trace.name", trace_name),
        _attr("session.id", session_id),
        _attr("user.id", sender),
        _attr("langfuse.trace.tags", ["brainsos-mail", f"agent:{agent_id}", f"status:{status}"]),
        _attr("langfuse.trace.metadata.agent_id", agent_id),
        _attr("langfuse.trace.metadata.agent_name", agent_name),
        # Observation-level attributes (this email only).
        _attr("langfuse.observation.type", "span"),
        _attr("langfuse.observation.level", "ERROR" if failed else "DEFAULT"),
        _attr("langfuse.observation.status_message", _truncate(error) if failed else None),
        _attr("langfuse.observation.input", _truncate(input_text)),
        _attr("langfuse.observation.output", _truncate(output_text)),
        _attr("langfuse.observation.metadata.run_id", run_id),
        _attr("langfuse.observation.metadata.status", status),
        _attr("langfuse.observation.metadata.subject", subject),
        _attr("langfuse.observation.metadata.sender", sender),
        _attr("langfuse.observation.metadata.usage", usage or {}),
    ]
    span = {
        "traceId": thread_trace_id(session_id),
        "spanId": secrets.token_hex(8),
        "name": f"email-run {agent_id}",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in candidates if a is not None],
        "status": (
            {"code": _STATUS_ERROR, "message": _truncate(error) or status} if failed else {"code": _STATUS_UNSET}
        ),
    }
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", _SERVICE_NAME)]},
                "scopeSpans": [{"scope": {"name": _SCOPE_NAME}, "spans": [span]}],
            }
        ]
    }


async def record_mail_run_trace(http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> bool:
    """Best-effort export of the ``email-run`` span to Langfuse via native OTel v4. Returns True on 2xx, never raises."""
    settings = langfuse_settings()
    if settings is None:
        return False
    base_url, public_key, secret_key = settings
    try:
        payload = build_email_run_otlp(**kwargs)
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
        headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            _INGESTION_VERSION_HEADER: "4",
        }
        client = http_client or httpx.AsyncClient()
        try:
            resp = await client.post(f"{base_url}{_OTLP_TRACES_PATH}", json=payload, headers=headers, timeout=10.0)
        finally:
            if http_client is None:
                await client.aclose()
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("Langfuse OTLP export returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Failed to record email-run span in Langfuse: %s", e)
    return False


__all__ = ["build_email_run_otlp", "langfuse_settings", "record_mail_run_trace", "thread_trace_id"]
