"""Worker-side LiteLLM Lens OTLP observation for each email run (Ticket #375).

Runs in parallel with ``langfuse_trace.py`` (and remains active when ``LANGFUSE_ENABLED=false``),
exporting an OpenTelemetry GenAI ``invoke_workflow`` (``email-run``) span to LiteLLM Lens
(``POST /v1/traces`` authenticated with ``Authorization: Bearer ${LITELLM_TRACING_KEY}``) on the
same deterministic ``thread_trace_id(session_id)`` used by Hermes' Lens OTLP plugin.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

import httpx
from brainsos_telemetry.tracing import deterministic_trace_id, resolve_active_backends

thread_trace_id = deterministic_trace_id

logger = logging.getLogger("brainsos_agent.lens")

_MAX_TEXT = 8000
_SCOPE_NAME = "brainsos-agent"
_SERVICE_NAME = "brainsos-agent-worker"
_OTLP_TRACES_PATH = "/v1/traces"

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


def is_lens_enabled() -> bool:
    """Returns True when LiteLLM Lens is active via ``BRAINSOS_TELEMETRY_BACKEND`` and ``LENS_ENABLED``."""
    lens_active, _ = resolve_active_backends()
    return lens_active


def lens_settings() -> tuple[str, str] | None:
    """Returns ``(traces_endpoint_url, tracing_key)`` or ``None`` when Lens is disabled or unconfigured."""
    if not is_lens_enabled() or os.getenv("BRAINSOS_MAIL_TRACE_ENABLED", "true").strip().lower() == "false":
        return None
    tracing_key = os.getenv("LITELLM_TRACING_KEY", "").strip()
    if not tracing_key:
        return None

    explicit_endpoint = os.getenv("LENS_OTLP_ENDPOINT", "").strip()
    if explicit_endpoint:
        endpoint = (
            explicit_endpoint
            if explicit_endpoint.endswith(_OTLP_TRACES_PATH)
            else f"{explicit_endpoint.rstrip('/')}{_OTLP_TRACES_PATH}"
        )
        return endpoint, tracing_key

    from brainsos_agent.adapters.hermes import resolve_runner_endpoint

    base_url = resolve_runner_endpoint(
        None,
        "BRAINSOS_LENS_URL",
        int(os.getenv("LENS_PORT", "4318")),
        ("brainsos-telemetry-lens", "brainsos-lens"),
        4318,
    )
    return f"{base_url.rstrip('/')}{_OTLP_TRACES_PATH}", tracing_key


def _attr(key: str, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, (list, tuple)):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    return {"key": key, "value": {"stringValue": value}}


def build_lens_email_run_otlp(
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
    """Builds an OTLP/JSON ``ExportTraceServiceRequest`` with one GenAI ``invoke_workflow`` span for Lens."""
    failed = status != "completed"
    end_ts = ended_at if ended_at is not None else time.time()
    start_ts = started_at if started_at is not None else end_ts
    clean_subj = (subject or "").strip()
    span_name = f"email-run {agent_id}: {clean_subj[:80]}" if clean_subj else f"email-run {agent_id}"
    local_domain = (
        os.getenv("BRAINSOS_LOCAL_DOMAIN")
        or os.getenv("BRAINSOS_MAIL_DOMAIN")
        or os.getenv("BRAINSOS_DOMAIN")
        or "brainsos.local"
    ).strip()

    in_messages = [{"role": "user", "content": _truncate(input_text) or ""}] if input_text else None
    out_messages = [{"role": "assistant", "content": _truncate(output_text) or ""}] if output_text else None

    candidates = [
        _attr("gen_ai.operation.name", "invoke_workflow"),
        _attr("gen_ai.agent.name", agent_id),
        _attr("gen_ai.conversation.id", session_id),
        _attr("session.id", session_id),
        _attr("user.id", sender),
        _attr("gen_ai.input.messages", json.dumps(in_messages) if in_messages else None),
        _attr("gen_ai.output.messages", json.dumps(out_messages) if out_messages else None),
        _attr("brainsos.agent_name", agent_name),
        _attr("brainsos.run_id", run_id),
        _attr("brainsos.status", status),
        _attr("brainsos.subject", clean_subj or None),
        _attr("brainsos.sender", sender),
        _attr("brainsos.local_domain", local_domain),
        _attr("brainsos.error", _truncate(error) if failed else None),
        _attr("brainsos.usage", usage if usage else None),
    ]
    span = {
        "traceId": thread_trace_id(session_id),
        "spanId": secrets.token_hex(8),
        "name": span_name,
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
                "resource": {
                    "attributes": [
                        a
                        for a in (
                            _attr("service.name", _SERVICE_NAME),
                            _attr("gen_ai.agent.name", agent_id),
                            _attr("host.name", local_domain),
                        )
                        if a is not None
                    ]
                },
                "scopeSpans": [{"scope": {"name": _SCOPE_NAME, "version": "0.5.2"}, "spans": [span]}],
            }
        ]
    }


async def record_lens_mail_run_trace(http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> bool:
    """Best-effort export of the ``email-run`` span to LiteLLM Lens (``POST /v1/traces``). Never raises."""
    settings = lens_settings()
    if settings is None:
        return False
    endpoint_url, tracing_key = settings
    try:
        payload = build_lens_email_run_otlp(**kwargs)
        headers = {
            "Authorization": f"Bearer {tracing_key}",
            "Content-Type": "application/json",
        }
        client = http_client or httpx.AsyncClient(trust_env=False)
        try:
            resp = await client.post(endpoint_url, json=payload, headers=headers, timeout=10.0)
        finally:
            if http_client is None:
                await client.aclose()
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("LiteLLM Lens OTLP export returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Failed to record email-run span in LiteLLM Lens: %s", e)
    return False


build_lens_mail_run_otlp_payload = build_lens_email_run_otlp

__all__ = [
    "build_lens_email_run_otlp",
    "build_lens_mail_run_otlp_payload",
    "is_lens_enabled",
    "lens_settings",
    "record_lens_mail_run_trace",
    "thread_trace_id",
]
