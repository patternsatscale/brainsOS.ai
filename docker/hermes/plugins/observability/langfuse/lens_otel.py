"""LiteLLM Lens OpenTelemetry GenAI exporter for Hermes Agent (Ticket #375).

Runs alongside the Langfuse plugin hooks (and remains active when ``LANGFUSE_ENABLED=false``),
exporting OpenTelemetry GenAI spans (``invoke_agent``, ``chat``, ``execute_tool``, plus child
``litellm.gateway.client`` ``gateway.request`` transport spans carrying the W3C ``traceparent``
span id) directly to LiteLLM Lens ``POST /v1/traces`` using ``Bearer ${LITELLM_TRACING_KEY}``.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_HERMES_SCOPE = {"name": "hermes-otel-plugin", "version": "0.5.2"}
_GATEWAY_SCOPE = {"name": "litellm.gateway.client", "version": "0.5.2"}
_SERVICE_NAME = "hermes-agent"
_SPAN_KIND_INTERNAL = 1
_SPAN_KIND_CLIENT = 3
_STATUS_UNSET = 0
_STATUS_ERROR = 2
_MAX_LENS_STATE = 256
_KNOWN_AGENTS = frozenset({"bawtford", "terrastella", "marvin", "cindypawford", "ping", "claude", "gpt"})
_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")

_LENS_LOCK = threading.Lock()
_LENS_STATE: dict[str, "_LensTurnState"] = {}
_EXECUTOR_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_CUSTOM_TRANSPORT: Callable[[str, str, dict[str, Any]], bool] | None = None


@dataclass
class _LensTurnState:
    trace_id: str
    root_span_id: str
    agent_name: str
    session_id: str
    local_domain: str
    started_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    input_messages: list[dict[str, Any]] = field(default_factory=list)
    last_output_messages: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_tools_by_name: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    subagents: dict[str, dict[str, Any]] = field(default_factory=dict)


def _resolve_telemetry_backends() -> tuple[bool, bool]:
    try:
        from brainsos_telemetry.tracing import resolve_active_backends

        return resolve_active_backends()
    except Exception:
        disabled = {"false", "0", "no", "off", "disabled"}
        lens_flag = os.environ.get("LENS_ENABLED", "true").strip().lower() not in disabled
        lf_flag = os.environ.get("LANGFUSE_ENABLED", "true").strip().lower() not in disabled
        backend = os.environ.get("BRAINSOS_TELEMETRY_BACKEND", "").strip().lower()
        if backend in {"none", "off", "disabled", "false", "0"}:
            return False, False
        if backend == "lens":
            return lens_flag, False
        if backend == "langfuse":
            return False, lf_flag
        if "," in backend:
            toks = {t.strip() for t in backend.split(",") if t.strip()}
            if toks <= {"none", "off", "disabled"}:
                return False, False
            return (("lens" in toks or "dual" in toks) and lens_flag), (
                ("langfuse" in toks or "dual" in toks) and lf_flag
            )
        return lens_flag, lf_flag


def is_langfuse_enabled() -> bool:
    _, langfuse_active = _resolve_telemetry_backends()
    return langfuse_active


def is_lens_enabled() -> bool:
    lens_active, _ = _resolve_telemetry_backends()
    if not lens_active:
        return False
    return bool(_lens_tracing_key())


def _lens_tracing_key() -> str:
    return os.environ.get("LITELLM_TRACING_KEY", "").strip()


def _lens_endpoint() -> str:
    explicit = os.environ.get("LENS_OTLP_ENDPOINT", "").strip()
    if not explicit:
        return "http://lens:4318/v1/traces"
    return explicit if explicit.endswith("/v1/traces") else f"{explicit.rstrip('/')}/v1/traces"


def _local_domain() -> str:
    return (
        os.environ.get("BRAINSOS_LOCAL_DOMAIN", "").strip()
        or os.environ.get("BRAINSOS_MAIL_DOMAIN", "").strip()
        or os.environ.get("BRAINSOS_DOMAIN", "").strip()
        or "brainsos.local"
    )


def _resolve_agent_name(session_id: str) -> str:
    sid = (session_id or "").strip().lower()
    if sid.startswith("mail-"):
        parts = sid.split("-", 2)
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    if sid in _KNOWN_AGENTS:
        return sid
    if "-" in sid:
        prefix = sid.split("-", 1)[0]
        if prefix in _KNOWN_AGENTS:
            return prefix
    for agent in _KNOWN_AGENTS:
        if f"-{agent}-" in sid:
            return agent
    return os.environ.get("HERMES_AGENT_NAME", "").strip() or _SERVICE_NAME


def _parse_traceparent_from_request(request: Any) -> tuple[str, str]:
    if not isinstance(request, dict):
        return "", ""
    body = request.get("body")
    if not isinstance(body, dict):
        return "", ""
    headers = body.get("extra_headers")
    if not isinstance(headers, dict):
        return "", ""
    for k, v in headers.items():
        if str(k).lower() == "traceparent" and isinstance(v, str):
            m = _TRACEPARENT_RE.match(v.strip().lower())
            if m and m.group(1) != "0" * 32 and m.group(2) != "0" * 16:
                return m.group(1), m.group(2)
    return "", ""


def deterministic_trace_id(session_id: str, task_id: str = "", task_key: str = "") -> str:
    sid = (session_id or "").strip() or "sessionless"
    tid = (task_id or session_id or task_key or "").strip() or "sessionless"
    seed = f"{sid}::{tid}"
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16].hex()


def _to_unix_nano(ts: float | None) -> str:
    val = ts if isinstance(ts, (int, float)) and ts > 0 else time.time()
    return str(int(val * 1_000_000_000))


def _attr(key: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, (list, tuple)):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": str(v)} for v in value]}}}
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return {"key": key, "value": {"stringValue": value}}


def _json_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _format_assistant_output_message(output: Any) -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return [{"role": "assistant", "content": str(output)}] if output is not None else []
    msg: dict[str, Any] = {"role": "assistant"}
    if output.get("content") is not None:
        msg["content"] = output["content"]
    if output.get("reasoning") is not None:
        msg["reasoning_content"] = output["reasoning"]
    raw_tcs = output.get("tool_calls")
    if isinstance(raw_tcs, list) and raw_tcs:
        formatted_tcs = []
        for tc in raw_tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = tc.get("name") or fn.get("name") or ""
            args = tc.get("arguments") if tc.get("arguments") is not None else fn.get("arguments")
            args_str = args if isinstance(args, str) else (_json_str(args) or "{}")
            formatted_tcs.append(
                {
                    "id": str(tc.get("id") or ""),
                    "type": "function",
                    "function": {"name": str(name), "arguments": args_str},
                }
            )
        if formatted_tcs:
            msg["tool_calls"] = formatted_tcs
    return [msg] if len(msg) > 1 else []


def _build_export_payload(
    *,
    agent_name: str,
    local_domain: str,
    hermes_spans: list[dict[str, Any]] | None = None,
    gateway_spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scope_spans: list[dict[str, Any]] = []
    if hermes_spans:
        scope_spans.append({"scope": _HERMES_SCOPE, "spans": hermes_spans})
    if gateway_spans:
        scope_spans.append({"scope": _GATEWAY_SCOPE, "spans": gateway_spans})
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        a
                        for a in (
                            _attr("service.name", _SERVICE_NAME),
                            _attr("gen_ai.agent.name", agent_name),
                            _attr("host.name", local_domain),
                        )
                        if a is not None
                    ]
                },
                "scopeSpans": scope_spans,
            }
        ]
    }


def _http_post_otlp(endpoint: str, token: str, payload: dict[str, Any]) -> bool:
    if _CUSTOM_TRANSPORT is not None:
        return _CUSTOM_TRANSPORT(endpoint, token, payload)
    try:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5.0) as resp:
            status = getattr(resp, "status", 200)
            return 200 <= int(status) < 300
    except Exception as exc:
        logger.debug("Lens OTLP export failed: %s", exc)
        return False


def _submit_export(payload: dict[str, Any]) -> None:
    if not is_lens_enabled():
        return
    endpoint = _lens_endpoint()
    token = _lens_tracing_key()
    if not token:
        return
    if _CUSTOM_TRANSPORT is not None:
        _http_post_otlp(endpoint, token, payload)
        return
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hermes-lens-otlp")
        executor = _EXECUTOR
    try:
        executor.submit(_http_post_otlp, endpoint, token, payload)
    except Exception:
        pass


def set_custom_transport(transport: Callable[[str, str, dict[str, Any]], bool] | None) -> None:
    """Test hook allowing deterministic in-memory capture of OTLP exports."""
    global _CUSTOM_TRANSPORT
    _CUSTOM_TRANSPORT = transport


def flush_lens_exports(*, shutdown: bool = False) -> None:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        executor = _EXECUTOR
        if shutdown:
            _EXECUTOR = None
    if executor is not None and shutdown:
        try:
            executor.shutdown(wait=True, cancel_futures=False)
        except Exception:
            pass


def _get_or_create_turn_locked(
    task_key: str,
    *,
    session_id: str,
    task_id: str,
    input_messages: list[dict[str, Any]],
    traceparent_trace_id: str = "",
) -> _LensTurnState:
    state = _LENS_STATE.get(task_key)
    if state is None:
        trace_id = traceparent_trace_id or deterministic_trace_id(session_id, task_id, task_key)
        user_msgs = [m for m in input_messages if isinstance(m, dict) and m.get("role") == "user"]
        initial_in = [user_msgs[-1]] if user_msgs else list(input_messages[-2:])
        state = _LensTurnState(
            trace_id=trace_id,
            root_span_id=secrets.token_hex(8),
            agent_name=_resolve_agent_name(session_id),
            session_id=session_id or task_key,
            local_domain=_local_domain(),
            input_messages=initial_in,
        )
        over = len(_LENS_STATE) - (_MAX_LENS_STATE - 1)
        for stale_key, stale_state in sorted(_LENS_STATE.items(), key=lambda kv: kv[1].last_updated_at)[: max(over, 0)]:
            _LENS_STATE.pop(stale_key, None)
            _emit_root_span(stale_state)
        _LENS_STATE[task_key] = state
    else:
        if traceparent_trace_id and state.trace_id != traceparent_trace_id:
            state.trace_id = traceparent_trace_id
        if not state.input_messages and input_messages:
            user_msgs = [m for m in input_messages if isinstance(m, dict) and m.get("role") == "user"]
            state.input_messages = [user_msgs[-1]] if user_msgs else list(input_messages[-2:])
    state.last_updated_at = time.time()
    return state


def _emit_root_span(state: _LensTurnState, *, error_message: str | None = None) -> None:
    end_ts = time.time()
    start_ts = min(state.started_at, end_ts)
    attrs = [
        _attr("gen_ai.operation.name", "invoke_agent"),
        _attr("gen_ai.agent.name", state.agent_name),
        _attr("gen_ai.conversation.id", state.session_id),
        _attr("session.id", state.session_id),
        _attr("gen_ai.input.messages", _json_str(state.input_messages) if state.input_messages else None),
        _attr("gen_ai.output.messages", _json_str(state.last_output_messages) if state.last_output_messages else None),
    ]
    root_span = {
        "traceId": state.trace_id,
        "spanId": state.root_span_id,
        "name": f"invoke_agent {state.agent_name}",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in attrs if a is not None],
        "status": (
            {"code": _STATUS_ERROR, "message": error_message[:500]}
            if error_message
            else {"code": _STATUS_UNSET}
        ),
    }
    _submit_export(
        _build_export_payload(
            agent_name=state.agent_name,
            local_domain=state.local_domain,
            hermes_spans=[root_span],
        )
    )


def lens_on_pre_llm_call(
    *,
    task_key: str,
    task_id: str = "",
    session_id: str = "",
    serialized_messages: list[dict[str, Any]] | None = None,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    with _LENS_LOCK:
        _get_or_create_turn_locked(
            task_key,
            session_id=session_id,
            task_id=task_id,
            input_messages=serialized_messages or [],
        )


def lens_on_pre_llm_request(
    *,
    task_key: str,
    task_id: str = "",
    session_id: str = "",
    req_key: str = "0",
    model: str = "",
    base_url: str = "",
    input_messages: list[dict[str, Any]] | None = None,
    request: Any = None,
    started_at: float | None = None,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    tp_trace_id, tp_span_id = _parse_traceparent_from_request(request)
    with _LENS_LOCK:
        state = _get_or_create_turn_locked(
            task_key,
            session_id=session_id,
            task_id=task_id,
            input_messages=input_messages or [],
            traceparent_trace_id=tp_trace_id,
        )
        state.llm_calls[req_key] = {
            "span_id": secrets.token_hex(8),
            "transport_span_id": tp_span_id,
            "model": model,
            "base_url": base_url,
            "input_messages": list(input_messages or []),
            "started_at": started_at if isinstance(started_at, (int, float)) and started_at > 0 else time.time(),
        }


def lens_on_post_llm_call(
    *,
    task_key: str,
    req_key: str = "0",
    model: str = "",
    response_model: str | None = None,
    response_id: str | None = None,
    finish_reason: str = "",
    output: dict[str, Any] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    started_at: float | None = None,
    ended_at: float | None = None,
    finish_turn: bool = False,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    with _LENS_LOCK:
        state = _LENS_STATE.get(task_key)
        call = state.llm_calls.pop(req_key, None) if state is not None else None
        if state is None or call is None:
            return
        out_msgs = _format_assistant_output_message(output)
        if out_msgs:
            state.last_output_messages = out_msgs
        state.last_updated_at = time.time()
        popped_state = _LENS_STATE.pop(task_key, None) if finish_turn else None

    end_ts = ended_at if isinstance(ended_at, (int, float)) and ended_at > 0 else time.time()
    start_ts = (
        started_at
        if isinstance(started_at, (int, float)) and started_at > 0
        else min(float(call.get("started_at") or end_ts), end_ts)
    )
    req_model = str(call.get("model") or model or "unknown")
    eff_resp_model = str(response_model or model or req_model)

    chat_attrs = [
        _attr("gen_ai.operation.name", "chat"),
        _attr("gen_ai.agent.name", state.agent_name),
        _attr("gen_ai.conversation.id", state.session_id),
        _attr("session.id", state.session_id),
        _attr("gen_ai.request.model", req_model),
        _attr("gen_ai.response.model", eff_resp_model),
        _attr("gen_ai.response.id", response_id),
        _attr("gen_ai.response.finish_reasons", [finish_reason] if finish_reason else None),
        _attr("gen_ai.usage.input_tokens", int(input_tokens) if input_tokens else 0),
        _attr("gen_ai.usage.output_tokens", int(output_tokens) if output_tokens else 0),
        _attr("gen_ai.input.messages", _json_str(call.get("input_messages")) if call.get("input_messages") else None),
        _attr("gen_ai.output.messages", _json_str(out_msgs) if out_msgs else None),
    ]
    chat_span = {
        "traceId": state.trace_id,
        "spanId": call["span_id"],
        "parentSpanId": state.root_span_id,
        "name": f"chat {eff_resp_model}",
        "kind": _SPAN_KIND_CLIENT,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in chat_attrs if a is not None],
        "status": {"code": _STATUS_UNSET},
    }

    gateway_spans: list[dict[str, Any]] = []
    tp_span_id = call.get("transport_span_id")
    if isinstance(tp_span_id, str) and len(tp_span_id) == 16:
        gw_attrs = [
            _attr("litellm.gateway.attempt", "true"),
            _attr("http.request.method", "POST"),
            _attr("url.full", str(call.get("base_url") or "")),
        ]
        gateway_spans.append(
            {
                "traceId": state.trace_id,
                "spanId": tp_span_id,
                "parentSpanId": call["span_id"],
                "name": "gateway.request",
                "kind": _SPAN_KIND_CLIENT,
                "startTimeUnixNano": _to_unix_nano(start_ts),
                "endTimeUnixNano": _to_unix_nano(end_ts),
                "attributes": [a for a in gw_attrs if a is not None],
                "status": {"code": _STATUS_UNSET},
            }
        )

    _submit_export(
        _build_export_payload(
            agent_name=state.agent_name,
            local_domain=state.local_domain,
            hermes_spans=[chat_span],
            gateway_spans=gateway_spans,
        )
    )
    if popped_state is not None:
        _emit_root_span(popped_state)


def lens_on_pre_tool_call(
    *,
    task_key: str,
    tool_name: str = "",
    tool_call_id: str = "",
    safe_args: Any = None,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    with _LENS_LOCK:
        state = _LENS_STATE.get(task_key)
        if state is None:
            return
        entry = {
            "span_id": secrets.token_hex(8),
            "tool_name": tool_name or "tool",
            "tool_call_id": tool_call_id,
            "args": safe_args,
            "started_at": time.time(),
        }
        if tool_call_id:
            state.tools[tool_call_id] = entry
        else:
            state.pending_tools_by_name.setdefault(tool_name, []).append(entry)
        state.last_updated_at = time.time()


def lens_on_post_tool_call(
    *,
    task_key: str,
    tool_name: str = "",
    tool_call_id: str = "",
    safe_args: Any = None,
    safe_result: Any = None,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    with _LENS_LOCK:
        state = _LENS_STATE.get(task_key)
        if state is None:
            return
        entry = state.tools.pop(tool_call_id, None) if tool_call_id else None
        if entry is None:
            queue = state.pending_tools_by_name.get(tool_name)
            if queue:
                entry = queue.pop(0)
                if not queue:
                    state.pending_tools_by_name.pop(tool_name, None)
        if entry is None:
            return
        state.last_updated_at = time.time()

    end_ts = time.time()
    start_ts = min(float(entry.get("started_at") or end_ts), end_ts)
    eff_name = str(tool_name or entry.get("tool_name") or "tool")
    eff_args = safe_args if safe_args is not None else entry.get("args")
    is_err = isinstance(safe_result, dict) and bool(safe_result.get("error"))

    tool_attrs = [
        _attr("gen_ai.operation.name", "execute_tool"),
        _attr("gen_ai.agent.name", state.agent_name),
        _attr("gen_ai.conversation.id", state.session_id),
        _attr("session.id", state.session_id),
        _attr("gen_ai.tool.name", eff_name),
        _attr("gen_ai.tool.call.id", tool_call_id or entry.get("tool_call_id") or None),
        _attr("gen_ai.tool.call.arguments", _json_str(eff_args) if eff_args is not None else "{}"),
        _attr("gen_ai.tool.call.result", _json_str(safe_result) if safe_result is not None else ""),
    ]
    tool_span = {
        "traceId": state.trace_id,
        "spanId": entry["span_id"],
        "parentSpanId": state.root_span_id,
        "name": f"execute_tool {eff_name}",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [a for a in tool_attrs if a is not None],
        "status": (
            {"code": _STATUS_ERROR, "message": str(safe_result.get("error"))[:300]}
            if is_err and isinstance(safe_result, dict)
            else {"code": _STATUS_UNSET}
        ),
    }
    _submit_export(
        _build_export_payload(
            agent_name=state.agent_name,
            local_domain=state.local_domain,
            hermes_spans=[tool_span],
        )
    )


def lens_on_api_request_error(
    *,
    task_key: str,
    req_key: str = "0",
    error_type: str = "",
    error_message: str = "",
    terminal: bool = False,
) -> None:
    if not is_lens_enabled() or not task_key:
        return
    with _LENS_LOCK:
        state = _LENS_STATE.get(task_key)
        call = state.llm_calls.pop(req_key, None) if state is not None else None
        if state is None:
            return
        popped_state = _LENS_STATE.pop(task_key, None) if terminal else None
        state.last_updated_at = time.time()

    msg = f"{error_type}: {error_message}".strip(": ") or "api_request_error"
    if call is not None:
        end_ts = time.time()
        start_ts = min(float(call.get("started_at") or end_ts), end_ts)
        req_model = str(call.get("model") or "unknown")
        err_span = {
            "traceId": state.trace_id,
            "spanId": call["span_id"],
            "parentSpanId": state.root_span_id,
            "name": f"chat {req_model}",
            "kind": _SPAN_KIND_CLIENT,
            "startTimeUnixNano": _to_unix_nano(start_ts),
            "endTimeUnixNano": _to_unix_nano(end_ts),
            "attributes": [
                a
                for a in (
                    _attr("gen_ai.operation.name", "chat"),
                    _attr("gen_ai.agent.name", state.agent_name),
                    _attr("gen_ai.request.model", req_model),
                    _attr("error.type", error_type or "api_request_error"),
                )
                if a is not None
            ],
            "status": {"code": _STATUS_ERROR, "message": msg[:500]},
        }
        _submit_export(
            _build_export_payload(
                agent_name=state.agent_name,
                local_domain=state.local_domain,
                hermes_spans=[err_span],
            )
        )
    if popped_state is not None:
        _emit_root_span(popped_state, error_message=msg)


def lens_on_subagent_start(
    *,
    parent_turn_id: str,
    child_session_id: str,
    child_role: str = "",
    safe_goal: Any = None,
) -> None:
    if not is_lens_enabled() or not parent_turn_id or not child_session_id:
        return
    suffix = f":turn:{parent_turn_id}"
    with _LENS_LOCK:
        state = next((s for k, s in _LENS_STATE.items() if k.endswith(suffix)), None)
        if state is None:
            return
        state.subagents[str(child_session_id)] = {
            "span_id": secrets.token_hex(8),
            "role": child_role or "subagent",
            "goal": safe_goal,
            "started_at": time.time(),
        }


def lens_on_subagent_stop(
    *,
    parent_turn_id: str,
    child_session_id: str,
    child_role: str = "",
    safe_summary: Any = None,
    child_status: Any = None,
) -> None:
    if not is_lens_enabled() or not parent_turn_id or not child_session_id:
        return
    suffix = f":turn:{parent_turn_id}"
    with _LENS_LOCK:
        state = next((s for k, s in _LENS_STATE.items() if k.endswith(suffix)), None)
        entry = state.subagents.pop(str(child_session_id), None) if state is not None else None
    if state is None or entry is None:
        return
    end_ts = time.time()
    start_ts = min(float(entry.get("started_at") or end_ts), end_ts)
    role = child_role or entry.get("role") or "subagent"
    sub_span = {
        "traceId": state.trace_id,
        "spanId": entry["span_id"],
        "parentSpanId": state.root_span_id,
        "name": f"invoke_agent {role}",
        "kind": _SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _to_unix_nano(start_ts),
        "endTimeUnixNano": _to_unix_nano(end_ts),
        "attributes": [
            a
            for a in (
                _attr("gen_ai.operation.name", "invoke_agent"),
                _attr("gen_ai.agent.name", str(role)),
                _attr("gen_ai.conversation.id", str(child_session_id)),
                _attr("gen_ai.prompt", _json_str(entry.get("goal"))),
                _attr("gen_ai.completion", _json_str(safe_summary)),
            )
            if a is not None
        ],
        "status": (
            {"code": _STATUS_ERROR, "message": str(child_status)}
            if str(child_status or "").lower() in {"failed", "error"}
            else {"code": _STATUS_UNSET}
        ),
    }
    _submit_export(
        _build_export_payload(
            agent_name=state.agent_name,
            local_domain=state.local_domain,
            hermes_spans=[sub_span],
        )
    )


def lens_on_session_finalize(*, session_id: str = "", reason: str = "") -> None:
    fragments = (f"session:{session_id}", f"task:{session_id}")
    with _LENS_LOCK:
        keys = [k for k in _LENS_STATE if not session_id or k == session_id or any(f in k for f in fragments)]
        popped = [st for k in keys if (st := _LENS_STATE.pop(k, None)) is not None]
    for st in popped:
        _emit_root_span(st)
    if reason == "shutdown":
        flush_lens_exports(shutdown=True)


def _atexit_finalize_lens() -> None:
    with _LENS_LOCK:
        states = list(_LENS_STATE.values())
        _LENS_STATE.clear()
    for st in states:
        _emit_root_span(st)
    flush_lens_exports(shutdown=True)


atexit.register(_atexit_finalize_lens)
