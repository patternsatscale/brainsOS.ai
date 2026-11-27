"""Vendor-Neutral OpenTelemetry GenAI Telemetry SPI (Ticket #382).

Provides deterministic W3C Trace Context helpers, runtime backend routing
(``BRAINSOS_TELEMETRY_BACKEND=dual|lens|langfuse|none``), pluggable ``TraceSink``
implementations (``LensOTLPSink`` and ``LangfuseOTLPSink``), and the unified
``OTelTraceDispatcher`` used across email workers and stateless agent runners.

Uses Python stdlib HTTP transport by default (with optional ``http_client``
injection for ``httpx.AsyncClient`` callers/tests) so ``brainsOS-telemetry``
requires zero additional third-party dependencies.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import socket
import time
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("brainsos_telemetry.tracing")

_MAX_TEXT = 8000
_DISABLED_VALUES = frozenset({"false", "0", "no", "off", "disabled"})
_NONE_BACKENDS = frozenset({"none", "off", "disabled", "false", "0"})
_DUAL_BACKENDS = frozenset({"", "dual", "both", "all"})
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

# OTLP enums (opentelemetry-proto): SpanKind INTERNAL = 1, CLIENT = 3; StatusCode UNSET = 0, ERROR = 2.
_SPAN_KIND_INTERNAL = 1
_SPAN_KIND_CLIENT = 3
_STATUS_UNSET = 0
_STATUS_ERROR = 2

_WORKFLOW_SCOPE_NAME = "brainsos-agent"
_WORKFLOW_SERVICE_NAME = "brainsos-agent-worker"
_RUNNER_SCOPE = {"name": "brainsos.telemetry.genai", "version": "0.1.0"}
_GATEWAY_SCOPE = {"name": "litellm.gateway.client", "version": "0.5.2"}
_RUNNER_SERVICE_NAME = "brainsos-runner"

_LENS_TRACES_PATH = "/v1/traces"
_LANGFUSE_TRACES_PATH = "/api/public/otel/v1/traces"
_LANGFUSE_INGESTION_HEADER = "x-langfuse-ingestion-version"


def _flag_enabled(raw: str | None, *, default: bool = True) -> bool:
    if raw is None:
        return default
    cleaned = raw.strip().lower()
    if not cleaned:
        return default
    return cleaned not in _DISABLED_VALUES


def resolve_active_backends(environ: Mapping[str, str] | None = None) -> tuple[bool, bool]:
    """Resolve ``(lens_active, langfuse_active)`` from environment configuration.

    Honors ``BRAINSOS_TELEMETRY_BACKEND`` (case-insensitive: ``dual``/unset, ``lens``,
    ``langfuse``, ``none``/``off``/``disabled``, or comma-separated ``lens,langfuse``)
    alongside ``LENS_ENABLED`` and ``LANGFUSE_ENABLED`` (both ``true`` by default).
    """
    env = os.environ if environ is None else environ
    lens_enabled = _flag_enabled(env.get("LENS_ENABLED"), default=True)
    langfuse_enabled = _flag_enabled(env.get("LANGFUSE_ENABLED"), default=True)

    backend_raw = (env.get("BRAINSOS_TELEMETRY_BACKEND") or "").strip().lower()
    if backend_raw in _NONE_BACKENDS:
        return False, False
    if backend_raw in _DUAL_BACKENDS:
        return lens_enabled, langfuse_enabled
    if "," in backend_raw:
        tokens = {tok.strip() for tok in backend_raw.split(",") if tok.strip()}
        if not tokens:
            return lens_enabled, langfuse_enabled
        if tokens <= _NONE_BACKENDS:
            return False, False
        want_lens = bool(tokens & {"lens", "dual", "both", "all"})
        want_langfuse = bool(tokens & {"langfuse", "dual", "both", "all"})
        return want_lens and lens_enabled, want_langfuse and langfuse_enabled
    if backend_raw == "lens":
        return lens_enabled, False
    if backend_raw == "langfuse":
        return False, langfuse_enabled
    return lens_enabled, langfuse_enabled


def deterministic_trace_id(session_id: str, task_id: str = "") -> str:
    """Derive a deterministic 32-hex W3C trace_id from ``session_id`` and ``task_id``."""
    sid = (session_id or "").strip() or "sessionless"
    tid = (task_id or session_id or "").strip() or "sessionless"
    seed = f"{sid}::{tid}"
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16].hex()


def mint_span_id() -> str:
    """Mint a random 16-hex W3C span_id (8 bytes)."""
    return secrets.token_hex(8)


def mint_traceparent(
    session_id: str,
    task_id: str = "",
    span_id: str | None = None,
) -> tuple[str, str, str]:
    """Mint ``(traceparent, trace_id, span_id)`` in W3C Trace Context v00 format."""
    trace_id = deterministic_trace_id(session_id, task_id)
    candidate = (span_id or "").strip().lower()
    sid = candidate if (_SPAN_ID_RE.match(candidate) and candidate != "0" * 16) else mint_span_id()
    return f"00-{trace_id}-{sid}-01", trace_id, sid


def parse_traceparent(value: str | None) -> tuple[str, str]:
    """Parse a W3C ``traceparent`` header into ``(trace_id, span_id)`` or ``("", "")``."""
    if not value or not isinstance(value, str):
        return "", ""
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if not match:
        return "", ""
    version, trace_id, span_id, _flags = match.groups()
    if version == "ff" or trace_id == "0" * 32 or span_id == "0" * 16:
        return "", ""
    return trace_id, span_id


def _truncate(value: str | None, max_chars: int = _MAX_TEXT) -> str | None:
    if value is None:
        return None
    return value if len(value) <= max_chars else value[:max_chars] + "…[truncated]"


def _to_unix_nano(ts: float | None) -> str:
    effective = ts if isinstance(ts, (int, float)) and ts > 0 else time.time()
    return str(int(effective * 1_000_000_000))


def _local_domain(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (
        (env.get("BRAINSOS_LOCAL_DOMAIN") or "").strip()
        or (env.get("BRAINSOS_MAIL_DOMAIN") or "").strip()
        or (env.get("BRAINSOS_DOMAIN") or "").strip()
        or "brainsos.local"
    )


def _attr(key: str, value: Any, *, encode_ints: bool = True) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if encode_ints and isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float) and encode_ints:
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, (list, tuple)):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    return {"key": key, "value": {"stringValue": value}}


def _tcp_probe(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolve_lens_endpoint(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    explicit = (env.get("LENS_OTLP_ENDPOINT") or env.get("BRAINSOS_LENS_URL") or "").strip()
    if explicit:
        return explicit if explicit.endswith(_LENS_TRACES_PATH) else f"{explicit.rstrip('/')}{_LENS_TRACES_PATH}"

    try:
        loopback_port = int(env.get("LENS_PORT", "4318"))
    except ValueError:
        loopback_port = 4318

    if _tcp_probe("127.0.0.1", loopback_port, timeout=0.2):
        return f"http://127.0.0.1:{loopback_port}{_LENS_TRACES_PATH}"

    try:
        from brainsos_agent.adapters.hermes import resolve_runner_endpoint

        resolved = resolve_runner_endpoint(
            None,
            "BRAINSOS_LENS_URL",
            loopback_port,
            ("brainsos-telemetry-lens", "brainsos-lens"),
            4318,
        )
        if resolved and "127.0.0.1" not in resolved:
            return f"{resolved.rstrip('/')}{_LENS_TRACES_PATH}"
    except Exception:
        pass

    for host in ("brainsos-telemetry-lens", "lens"):
        try:
            socket.getaddrinfo(host, 4318)
            return f"http://{host}:4318{_LENS_TRACES_PATH}"
        except OSError:
            continue
    return f"http://lens:4318{_LENS_TRACES_PATH}"


def _resolve_langfuse_base_url(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    explicit = (
        env.get("BRAINSOS_LANGFUSE_URL")
        or env.get("LANGFUSE_BASE_URL")
        or env.get("LANGFUSE_HOST")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    try:
        loopback_port = int(env.get("LANGFUSE_PORT", "3001"))
    except ValueError:
        loopback_port = 3001

    if _tcp_probe("127.0.0.1", loopback_port, timeout=0.2):
        return f"http://127.0.0.1:{loopback_port}"

    try:
        from brainsos_agent.adapters.hermes import resolve_runner_endpoint

        resolved = resolve_runner_endpoint(
            None,
            "BRAINSOS_LANGFUSE_URL",
            loopback_port,
            ("brainsos-telemetry-langfuse-web", "brainsos-langfuse-web"),
            3000,
        )
        if resolved and "127.0.0.1" not in resolved:
            return resolved.rstrip("/")
    except Exception:
        pass

    for host in ("brainsos-telemetry-langfuse-web", "langfuse-web"):
        try:
            socket.getaddrinfo(host, 3000)
            return f"http://{host}:3000"
        except OSError:
            continue
    return "http://langfuse-web:3000"


def _stdlib_post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 10.0) -> bool:
    try:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            return 200 <= status < 300
    except Exception as exc:
        logger.debug("OTLP stdlib export to %s failed: %s", url, exc)
        return False


async def _post_otlp_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    http_client: Any = None,
    timeout: float = 10.0,
) -> bool:
    if http_client is not None:
        try:
            resp = await http_client.post(url, json=payload, headers=headers, timeout=timeout)
            return 200 <= int(resp.status_code) < 300
        except Exception as exc:
            logger.debug("OTLP http_client export to %s failed: %s", url, exc)
            return False
    return await asyncio.to_thread(_stdlib_post_json, url, payload, headers, timeout)


def build_lens_workflow_otlp(
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
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build an OTLP/JSON ``ExportTraceServiceRequest`` with one GenAI ``invoke_workflow`` span for Lens."""
    failed = status != "completed"
    end_ts = ended_at if ended_at is not None else time.time()
    start_ts = started_at if started_at is not None else end_ts
    clean_subj = (subject or "").strip()
    span_name = f"email-run {agent_id}: {clean_subj[:80]}" if clean_subj else f"email-run {agent_id}"
    local_domain = _local_domain(environ)

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
        "traceId": deterministic_trace_id(session_id),
        "spanId": mint_span_id(),
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
                            _attr("service.name", _WORKFLOW_SERVICE_NAME),
                            _attr("gen_ai.agent.name", agent_id),
                            _attr("host.name", local_domain),
                        )
                        if a is not None
                    ]
                },
                "scopeSpans": [{"scope": {"name": _WORKFLOW_SCOPE_NAME, "version": "0.5.2"}, "spans": [span]}],
            }
        ]
    }


def build_langfuse_workflow_otlp(
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
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build an OTLP/JSON ``ExportTraceServiceRequest`` with one ``email-run`` span for Langfuse v4."""
    failed = status != "completed"
    end_ts = ended_at if ended_at is not None else time.time()
    start_ts = started_at if started_at is not None else end_ts
    clean_subj = (subject or "").strip()
    trace_name = f"brainsos: email: {clean_subj[:120]}" if clean_subj else f"brainsos: email: {agent_id}"
    local_domain = _local_domain(environ)

    candidates = [
        _attr("langfuse.trace.name", trace_name, encode_ints=False),
        _attr("session.id", session_id, encode_ints=False),
        _attr("user.id", sender, encode_ints=False),
        _attr("langfuse.trace.tags", ["brainsos-mail", f"agent:{agent_id}", f"status:{status}"], encode_ints=False),
        _attr("langfuse.trace.metadata.agent_id", agent_id, encode_ints=False),
        _attr("langfuse.trace.metadata.agent_name", agent_name, encode_ints=False),
        _attr("langfuse.trace.metadata.local_domain", local_domain, encode_ints=False),
        _attr("langfuse.observation.type", "span", encode_ints=False),
        _attr("langfuse.observation.level", "ERROR" if failed else "DEFAULT", encode_ints=False),
        _attr("langfuse.observation.status_message", _truncate(error) if failed else None, encode_ints=False),
        _attr("langfuse.observation.input", _truncate(input_text), encode_ints=False),
        _attr("langfuse.observation.output", _truncate(output_text), encode_ints=False),
        _attr("langfuse.observation.metadata.run_id", run_id, encode_ints=False),
        _attr("langfuse.observation.metadata.status", status, encode_ints=False),
        _attr("langfuse.observation.metadata.subject", subject, encode_ints=False),
        _attr("langfuse.observation.metadata.sender", sender, encode_ints=False),
        _attr("langfuse.observation.metadata.local_domain", local_domain, encode_ints=False),
        _attr("langfuse.observation.metadata.usage", usage or {}, encode_ints=False),
    ]
    span = {
        "traceId": deterministic_trace_id(session_id),
        "spanId": mint_span_id(),
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
                "resource": {
                    "attributes": [
                        a
                        for a in (
                            _attr("service.name", _WORKFLOW_SERVICE_NAME, encode_ints=False),
                            _attr("host.name", local_domain, encode_ints=False),
                        )
                        if a is not None
                    ]
                },
                "scopeSpans": [{"scope": {"name": _WORKFLOW_SCOPE_NAME}, "spans": [span]}],
            }
        ]
    }


def _normalize_tool_call(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        data = dict(raw)
    elif hasattr(raw, "model_dump") and callable(raw.model_dump):
        data = dict(raw.model_dump())
    else:
        data = {
            "id": getattr(raw, "id", f"call_{index}"),
            "tool_name": getattr(raw, "tool_name", None) or getattr(raw, "name", "tool"),
            "arguments": getattr(raw, "arguments", {}),
            "output": getattr(raw, "output", ""),
            "exit_code": getattr(raw, "exit_code", 0),
        }
    return {
        "id": str(data.get("id") or f"call_{index}"),
        "tool_name": str(data.get("tool_name") or data.get("name") or "tool"),
        "arguments": data.get("arguments") if data.get("arguments") is not None else {},
        "output": data.get("output") if data.get("output") is not None else data.get("result", ""),
        "exit_code": data.get("exit_code", 0),
        "error": data.get("error"),
    }


def build_runner_turn_otlp(
    *,
    agent_id: str,
    session_id: str,
    run_id: str,
    model: str,
    input_text: str,
    output_text: str,
    started_at: float,
    ended_at: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    trace_id: str = "",
    transport_span_id: str = "",
    tool_calls: Sequence[Mapping[str, Any] | Any] = (),
    error: str | None = None,
    include_langfuse_attrs: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build an OpenTelemetry GenAI ``invoke_agent`` + ``chat`` + ``gateway.request`` + ``execute_tool`` batch."""
    eff_agent = (agent_id or "agent").strip() or "agent"
    eff_session = (session_id or run_id or "sessionless").strip() or "sessionless"
    eff_model = (model or "unknown").strip() or "unknown"
    clean_trace = (trace_id or "").strip().lower()
    eff_trace_id = (
        clean_trace
        if (_TRACE_ID_RE.match(clean_trace) and clean_trace != "0" * 32)
        else deterministic_trace_id(eff_session, run_id)
    )
    clean_tp = (transport_span_id or "").strip().lower()
    eff_tp_span_id = (
        clean_tp if (_SPAN_ID_RE.match(clean_tp) and clean_tp != "0" * 16) else mint_span_id()
    )

    end_ts = ended_at if isinstance(ended_at, (int, float)) and ended_at > 0 else time.time()
    start_ts = (
        min(float(started_at), float(end_ts))
        if isinstance(started_at, (int, float)) and started_at > 0
        else end_ts
    )
    local_domain = _local_domain(environ)
    failed = bool(error)

    root_span_id = mint_span_id()
    chat_span_id = mint_span_id()

    in_msgs = [{"role": "user", "content": _truncate(input_text) or ""}] if input_text else []
    normalized_tools = [_normalize_tool_call(tc, idx) for idx, tc in enumerate(tool_calls or ())]

    assistant_msg: dict[str, Any] = {"role": "assistant"}
    if output_text:
        assistant_msg["content"] = _truncate(output_text) or ""
    if normalized_tools:
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["tool_name"],
                    "arguments": (
                        tc["arguments"]
                        if isinstance(tc["arguments"], str)
                        else json.dumps(tc["arguments"], default=str)
                    ),
                },
            }
            for tc in normalized_tools
        ]
    out_msgs = [assistant_msg] if len(assistant_msg) > 1 else []

    status_obj = (
        {"code": _STATUS_ERROR, "message": (_truncate(error) or "error")[:500]}
        if failed
        else {"code": _STATUS_UNSET}
    )

    root_attrs = [
        _attr("gen_ai.operation.name", "invoke_agent"),
        _attr("gen_ai.agent.name", eff_agent),
        _attr("gen_ai.conversation.id", eff_session),
        _attr("session.id", eff_session),
        _attr("brainsos.run_id", run_id or None),
        _attr("gen_ai.input.messages", json.dumps(in_msgs) if in_msgs else None),
        _attr("gen_ai.output.messages", json.dumps(out_msgs) if out_msgs else None),
    ]
    if include_langfuse_attrs:
        root_attrs.extend(
            [
                _attr("langfuse.trace.name", f"brainsos: runner: {eff_agent}"),
                _attr("langfuse.trace.tags", ["brainsos-runner", f"agent:{eff_agent}"]),
                _attr("langfuse.observation.type", "agent"),
                _attr("langfuse.observation.input", _truncate(input_text)),
                _attr("langfuse.observation.output", _truncate(output_text)),
            ]
        )

    root_span = {
        "traceId": eff_trace_id,
        "spanId": root_span_id,
        "name": f"invoke_agent {eff_agent}",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in root_attrs if a is not None],
        "status": status_obj,
    }

    chat_attrs = [
        _attr("gen_ai.operation.name", "chat"),
        _attr("gen_ai.agent.name", eff_agent),
        _attr("gen_ai.conversation.id", eff_session),
        _attr("session.id", eff_session),
        _attr("gen_ai.request.model", eff_model),
        _attr("gen_ai.response.model", eff_model),
        _attr("gen_ai.usage.input_tokens", int(prompt_tokens or 0)),
        _attr("gen_ai.usage.output_tokens", int(completion_tokens or 0)),
        _attr("gen_ai.input.messages", json.dumps(in_msgs) if in_msgs else None),
        _attr("gen_ai.output.messages", json.dumps(out_msgs) if out_msgs else None),
    ]
    if include_langfuse_attrs:
        chat_attrs.extend(
            [
                _attr("langfuse.observation.type", "generation"),
                _attr("langfuse.observation.input", _truncate(input_text)),
                _attr("langfuse.observation.output", _truncate(output_text)),
            ]
        )

    chat_span = {
        "traceId": eff_trace_id,
        "spanId": chat_span_id,
        "parentSpanId": root_span_id,
        "name": f"chat {eff_model}",
        "kind": _SPAN_KIND_CLIENT,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in chat_attrs if a is not None],
        "status": status_obj,
    }

    genai_spans: list[dict[str, Any]] = [root_span, chat_span]
    for tc in normalized_tools:
        tc_err = tc.get("error") or (f"exit_code={tc['exit_code']}" if tc.get("exit_code") not in (None, 0) else None)
        args_str = (
            tc["arguments"]
            if isinstance(tc["arguments"], str)
            else json.dumps(tc["arguments"], default=str)
        )
        res_str = tc["output"] if isinstance(tc["output"], str) else json.dumps(tc["output"], default=str)
        tool_attrs = [
            _attr("gen_ai.operation.name", "execute_tool"),
            _attr("gen_ai.agent.name", eff_agent),
            _attr("gen_ai.conversation.id", eff_session),
            _attr("session.id", eff_session),
            _attr("gen_ai.tool.name", tc["tool_name"]),
            _attr("gen_ai.tool.call.id", tc["id"]),
            _attr("gen_ai.tool.call.arguments", _truncate(args_str) or "{}"),
            _attr("gen_ai.tool.call.result", _truncate(res_str) or ""),
        ]
        if include_langfuse_attrs:
            tool_attrs.append(_attr("langfuse.observation.type", "tool"))
        genai_spans.append(
            {
                "traceId": eff_trace_id,
                "spanId": mint_span_id(),
                "parentSpanId": root_span_id,
                "name": f"execute_tool {tc['tool_name']}",
                "kind": _SPAN_KIND_INTERNAL,
                "startTimeUnixNano": _to_unix_nano(start_ts),
                "endTimeUnixNano": _to_unix_nano(end_ts),
                "attributes": [a for a in tool_attrs if a is not None],
                "status": (
                    {"code": _STATUS_ERROR, "message": str(tc_err)[:300]}
                    if tc_err
                    else {"code": _STATUS_UNSET}
                ),
            }
        )

    gateway_span = {
        "traceId": eff_trace_id,
        "spanId": eff_tp_span_id,
        "parentSpanId": chat_span_id,
        "name": "gateway.request",
        "kind": _SPAN_KIND_CLIENT,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [
            a
            for a in (
                _attr("litellm.gateway.attempt", "true"),
                _attr("http.request.method", "POST"),
            )
            if a is not None
        ],
        "status": status_obj,
    }

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        a
                        for a in (
                            _attr("service.name", _RUNNER_SERVICE_NAME),
                            _attr("gen_ai.agent.name", eff_agent),
                            _attr("host.name", local_domain),
                        )
                        if a is not None
                    ]
                },
                "scopeSpans": [
                    {"scope": _RUNNER_SCOPE, "spans": genai_spans},
                    {"scope": _GATEWAY_SCOPE, "spans": [gateway_span]},
                ],
            }
        ]
    }


@runtime_checkable
class TraceSink(Protocol):
    """Pluggable OpenTelemetry GenAI trace export sink SPI."""

    name: str

    async def export_workflow_run(self, **kwargs: Any) -> bool:
        """Export an email/workflow outer span. Returns True on HTTP 2xx, never raises."""
        ...

    async def export_runner_turn(self, **kwargs: Any) -> bool:
        """Export a runner cognitive turn span batch. Returns True on HTTP 2xx, never raises."""
        ...


class LensOTLPSink:
    """Exports OpenTelemetry GenAI spans to LiteLLM Lens ``POST /v1/traces``."""

    name: str = "lens"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        tracing_key: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._explicit_endpoint = endpoint
        self._explicit_key = tracing_key
        self._environ = environ

    def _env(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def _credentials(self) -> tuple[str, str] | None:
        env = self._env()
        key = (self._explicit_key if self._explicit_key is not None else env.get("LITELLM_TRACING_KEY", "")).strip()
        if not key:
            return None
        if self._explicit_endpoint:
            ep = (
                self._explicit_endpoint
                if self._explicit_endpoint.endswith(_LENS_TRACES_PATH)
                else f"{self._explicit_endpoint.rstrip('/')}{_LENS_TRACES_PATH}"
            )
        else:
            ep = _resolve_lens_endpoint(env)
        return ep, key

    async def export_workflow_run(self, **kwargs: Any) -> bool:
        env = self._env()
        if (env.get("BRAINSOS_MAIL_TRACE_ENABLED") or "true").strip().lower() == "false":
            return False
        creds = self._credentials()
        if creds is None:
            return False
        endpoint_url, tracing_key = creds
        http_client = kwargs.pop("http_client", None)
        try:
            payload = build_lens_workflow_otlp(**kwargs, environ=env)
            headers = {
                "Authorization": f"Bearer {tracing_key}",
                "Content-Type": "application/json",
            }
            return await _post_otlp_json(endpoint_url, payload, headers, http_client=http_client)
        except Exception as exc:
            logger.warning("LensOTLPSink.export_workflow_run failed: %s", exc)
            return False

    async def export_runner_turn(self, **kwargs: Any) -> bool:
        env = self._env()
        creds = self._credentials()
        if creds is None:
            return False
        endpoint_url, tracing_key = creds
        http_client = kwargs.pop("http_client", None)
        try:
            payload = build_runner_turn_otlp(**kwargs, include_langfuse_attrs=False, environ=env)
            headers = {
                "Authorization": f"Bearer {tracing_key}",
                "Content-Type": "application/json",
            }
            return await _post_otlp_json(endpoint_url, payload, headers, http_client=http_client)
        except Exception as exc:
            logger.warning("LensOTLPSink.export_runner_turn failed: %s", exc)
            return False


class LangfuseOTLPSink:
    """Exports OpenTelemetry spans to Langfuse v4 ``POST /api/public/otel/v1/traces``."""

    name: str = "langfuse"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        public_key: str | None = None,
        secret_key: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._explicit_base_url = base_url
        self._explicit_public_key = public_key
        self._explicit_secret_key = secret_key
        self._environ = environ

    def _env(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def _credentials(self) -> tuple[str, str, str] | None:
        env = self._env()
        pub = (
            self._explicit_public_key
            if self._explicit_public_key is not None
            else (env.get("LANGFUSE_PUBLIC_KEY") or env.get("HERMES_LANGFUSE_PUBLIC_KEY") or "")
        ).strip()
        sec = (
            self._explicit_secret_key
            if self._explicit_secret_key is not None
            else (env.get("LANGFUSE_SECRET_KEY") or env.get("HERMES_LANGFUSE_SECRET_KEY") or "")
        ).strip()
        if not pub or not sec:
            return None
        base = (self._explicit_base_url or "").strip().rstrip("/") or _resolve_langfuse_base_url(env)
        return f"{base}{_LANGFUSE_TRACES_PATH}", pub, sec

    async def export_workflow_run(self, **kwargs: Any) -> bool:
        env = self._env()
        if (env.get("BRAINSOS_MAIL_TRACE_ENABLED") or "true").strip().lower() == "false":
            return False
        creds = self._credentials()
        if creds is None:
            return False
        endpoint_url, pub, sec = creds
        http_client = kwargs.pop("http_client", None)
        try:
            payload = build_langfuse_workflow_otlp(**kwargs, environ=env)
            basic = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("ascii")
            headers = {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                _LANGFUSE_INGESTION_HEADER: "4",
            }
            return await _post_otlp_json(endpoint_url, payload, headers, http_client=http_client)
        except Exception as exc:
            logger.warning("LangfuseOTLPSink.export_workflow_run failed: %s", exc)
            return False

    async def export_runner_turn(self, **kwargs: Any) -> bool:
        env = self._env()
        creds = self._credentials()
        if creds is None:
            return False
        endpoint_url, pub, sec = creds
        http_client = kwargs.pop("http_client", None)
        try:
            payload = build_runner_turn_otlp(**kwargs, include_langfuse_attrs=True, environ=env)
            basic = base64.b64encode(f"{pub}:{sec}".encode("utf-8")).decode("ascii")
            headers = {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                _LANGFUSE_INGESTION_HEADER: "4",
            }
            return await _post_otlp_json(endpoint_url, payload, headers, http_client=http_client)
        except Exception as exc:
            logger.warning("LangfuseOTLPSink.export_runner_turn failed: %s", exc)
            return False


class OTelTraceDispatcher:
    """Dispatches OpenTelemetry GenAI workflow and runner spans across active ``TraceSink`` backends."""

    def __init__(self, sinks: Sequence[TraceSink] = ()) -> None:
        self.sinks: tuple[TraceSink, ...] = tuple(sinks)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OTelTraceDispatcher:
        lens_active, langfuse_active = resolve_active_backends(environ)
        active_sinks: list[TraceSink] = []
        if lens_active:
            active_sinks.append(LensOTLPSink(environ=environ))
        if langfuse_active:
            active_sinks.append(LangfuseOTLPSink(environ=environ))
        return cls(sinks=active_sinks)

    async def record_workflow_run(self, **kwargs: Any) -> dict[str, bool]:
        """Dispatch workflow/email outer span in parallel to all active sinks."""
        outcomes: dict[str, bool] = {"lens": False, "langfuse": False}
        if not self.sinks:
            return outcomes
        results = await asyncio.gather(
            *(sink.export_workflow_run(**dict(kwargs)) for sink in self.sinks),
            return_exceptions=True,
        )
        for sink, res in zip(self.sinks, results):
            outcomes[sink.name] = bool(res) if not isinstance(res, BaseException) else False
        return outcomes

    async def record_runner_turn(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        model: str,
        input_text: str,
        output_text: str,
        started_at: float,
        ended_at: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        trace_id: str = "",
        transport_span_id: str = "",
        tool_calls: Sequence[Mapping[str, Any]] = (),
        error: str | None = None,
        http_client: Any = None,
    ) -> dict[str, bool]:
        """Build & export an OpenTelemetry GenAI runner turn span batch to all active sinks."""
        outcomes: dict[str, bool] = {"lens": False, "langfuse": False}
        if not self.sinks:
            return outcomes
        turn_kwargs: dict[str, Any] = {
            "agent_id": agent_id,
            "session_id": session_id,
            "run_id": run_id,
            "model": model,
            "input_text": input_text,
            "output_text": output_text,
            "started_at": started_at,
            "ended_at": ended_at,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "trace_id": trace_id,
            "transport_span_id": transport_span_id,
            "tool_calls": tool_calls,
            "error": error,
            "http_client": http_client,
        }
        results = await asyncio.gather(
            *(sink.export_runner_turn(**dict(turn_kwargs)) for sink in self.sinks),
            return_exceptions=True,
        )
        for sink, res in zip(self.sinks, results):
            outcomes[sink.name] = bool(res) if not isinstance(res, BaseException) else False
        return outcomes


__all__ = [
    "LangfuseOTLPSink",
    "LensOTLPSink",
    "OTelTraceDispatcher",
    "TraceSink",
    "build_langfuse_workflow_otlp",
    "build_lens_workflow_otlp",
    "build_runner_turn_otlp",
    "deterministic_trace_id",
    "mint_span_id",
    "mint_traceparent",
    "parse_traceparent",
    "resolve_active_backends",
]
