"""Warm OpenAI SDK Runner Service & Dynamic Script Host."""

import importlib.util
import inspect
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from brainsos_runner import (
    AgentTurnRequest,
    AgentTurnResponse,
    ExecutionMetrics,
    ToolCallRecord,
    create_runner_app,
)
from openai import AsyncOpenAI

try:
    from brainsos_telemetry.tracing import OTelTraceDispatcher, mint_traceparent
except ImportError:  # pragma: no cover - defensive fallback if base image lacks brainsOS-telemetry
    OTelTraceDispatcher = None  # type: ignore[assignment,misc]

    def mint_traceparent(session_id: str, task_id: str = "", span_id: str | None = None) -> tuple[str, str, str]:
        import hashlib
        import secrets

        sid = (session_id or "").strip() or "sessionless"
        tid = (task_id or session_id or "").strip() or "sessionless"
        tid_hex = hashlib.sha256(f"{sid}::{tid}".encode("utf-8")).digest()[:16].hex()
        sp_hex = span_id or secrets.token_hex(8)
        return f"00-{tid_hex}-{sp_hex}-01", tid_hex, sp_hex


logger = logging.getLogger("brainsos.runners.openai")
logging.basicConfig(level=logging.INFO)

LITELLM_BASE_URL = os.getenv("OPENAI_BASE_URL", os.getenv("LITELLM_URL", "http://litellm:4000/v1")).rstrip("/")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_SDK_LITELLM_KEY", "")
SAFE_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _validate_agent_id(agent_id: str) -> str:
    clean = (agent_id or "").strip()
    if not SAFE_AGENT_ID_RE.match(clean):
        raise PermissionError(f"Access denied: invalid agent_id '{agent_id}'")
    return clean


def _load_dynamic_script(script_path_str: str, agent_id: str = "") -> Any:
    """Load a custom agent script strictly allowlisted to the calling agent's runner/agent directory."""
    clean_agent = _validate_agent_id(agent_id)
    script_real = os.path.realpath(script_path_str)
    allowed_roots = [
        os.path.realpath(f"/data/runners/openai-sdk/{clean_agent}"),
        os.path.realpath(f"/data/agents/{clean_agent}"),
    ]
    if os.getenv("BRAINSOS_AGENT_ID", "").strip() == clean_agent:
        allowed_roots.append(os.path.realpath("/workspace"))
    if not any(os.path.commonpath([root, script_real]) == root for root in allowed_roots):
        raise PermissionError(f"Access denied: Script path outside allowlisted agent roots ({script_real})")

    script_path = Path(script_real)
    if not script_path.is_file() or script_path.suffix != ".py":
        raise FileNotFoundError(f"Custom runner Python script not found: {script_path}")

    module_name = f"dynamic_agent_{clean_agent}_{script_path.stem}_{int(time.time())}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module specification from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_input_text(request: AgentTurnRequest) -> str:
    for msg in reversed(request.conversation):
        if msg.role == "user" and msg.content:
            return msg.content
    if request.conversation:
        return request.conversation[-1].content or ""
    return ""


async def handle_openai_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    """Execute turn using OpenAI SDK against LiteLLM or hot-reloaded script."""
    start_time = time.perf_counter()
    started_wall = time.time()
    session_id = str(request.extra_params.get("session_id") or request.run_id)
    traceparent, trace_id, transport_span_id = mint_traceparent(session_id, request.run_id)
    input_text = _extract_input_text(request)

    async def _emit_trace(
        output_txt: str,
        *,
        p_tokens: int = 0,
        c_tokens: int = 0,
        tools: Optional[List[ToolCallRecord]] = None,
        err: Optional[str] = None,
    ) -> None:
        if OTelTraceDispatcher is None:
            return
        try:
            await OTelTraceDispatcher.from_env().record_runner_turn(
                agent_id=request.agent_id,
                session_id=session_id,
                run_id=request.run_id,
                model=request.model,
                input_text=input_text,
                output_text=output_txt,
                started_at=started_wall,
                ended_at=time.time(),
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                trace_id=trace_id,
                transport_span_id=transport_span_id,
                tool_calls=[tc.model_dump() for tc in (tools or [])],
                error=err,
            )
        except Exception:
            pass

    client = AsyncOpenAI(
        base_url=LITELLM_BASE_URL,
        api_key=LITELLM_API_KEY,
        timeout=float(request.timeout_sec),
        default_headers={
            "X-BrainsOS-Agent": request.agent_id,
            "X-BrainsOS-Run-ID": request.run_id,
            "traceparent": traceparent,
        },
    )

    # 1. Check for dynamic custom script execution (strictly allowlisted by agent_id)
    script_path = request.extra_params.get("script_path")
    if not script_path and request.agent_id:
        clean_agent = _validate_agent_id(request.agent_id)
        convention_path = Path(f"/data/runners/openai-sdk/{clean_agent}/agent.py")
        if convention_path.is_file():
            script_path = str(convention_path)

    if script_path:
        try:
            module = _load_dynamic_script(str(script_path), request.agent_id)
            if not hasattr(module, "handle_turn"):
                raise AttributeError(f"Script {script_path} does not export 'handle_turn' function")

            handler_func = getattr(module, "handle_turn")
            if inspect.iscoroutinefunction(handler_func):
                result = await handler_func(request=request, client=client)
            else:
                result = handler_func(request=request, client=client)

            if isinstance(result, AgentTurnResponse):
                await _emit_trace(
                    result.output_text,
                    p_tokens=result.metrics.prompt_tokens if result.metrics else 0,
                    c_tokens=result.metrics.completion_tokens if result.metrics else 0,
                    tools=list(result.tool_calls or []),
                    err=result.error_message,
                )
                return result
            elif isinstance(result, str):
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                await _emit_trace(result)
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="completed",
                    output_text=result,
                    metrics=ExecutionMetrics(duration_ms=duration_ms),
                )
            else:
                raise TypeError(f"Custom script returned unexpected type: {type(result)}")
        except Exception as exc:
            logger.exception("Error executing dynamic script %s: %s", script_path, exc)
            err_msg = f"Dynamic script execution error: {exc}"
            await _emit_trace("", err=err_msg)
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=err_msg,
            )

    # 2. Standard OpenAI Function Calling / Completion Loop
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": request.system_prompt},
    ]
    for msg in request.conversation:
        entry: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        messages.append(entry)

    tool_records: List[ToolCallRecord] = []
    output_text = ""
    prompt_tokens = 0
    completion_tokens = 0

    try:
        completion = await client.chat.completions.create(
            model=request.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=request.extra_params.get("temperature", 0.7),
        )

        choice = completion.choices[0]
        output_text = choice.message.content or ""

        if choice.message.tool_calls:
            for idx, tc in enumerate(choice.message.tool_calls):
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                tool_records.append(
                    ToolCallRecord(
                        id=tc.id or f"call_{idx}",
                        tool_name=fn.name,
                        arguments={"args": fn.arguments},
                        output=f"Invoked {fn.name}",
                        exit_code=0,
                    )
                )

        if completion.usage:
            prompt_tokens = completion.usage.prompt_tokens
            completion_tokens = completion.usage.completion_tokens

    except Exception as exc:
        logger.warning("OpenAI completion failed against %s: %s", LITELLM_BASE_URL, exc)
        if os.getenv("RUNNER_MOCK_FALLBACK", "false").lower() == "true":
            output_text = f"Mock OpenAI response for {request.model}"
        else:
            err_msg = f"OpenAI SDK execution failed: {exc}"
            await _emit_trace("", err=err_msg)
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=err_msg,
            )

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    await _emit_trace(
        output_text,
        p_tokens=prompt_tokens,
        c_tokens=completion_tokens,
        tools=tool_records,
    )

    return AgentTurnResponse(
        run_id=request.run_id,
        status="completed",
        output_text=output_text,
        tool_calls=tool_records,
        memory_deltas=[],
        metrics=ExecutionMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        ),
    )


app = create_runner_app(handle_openai_turn, title="brainsOS OpenAI Runner")


def _run_ephemeral_cli() -> int:
    import asyncio
    import sys

    req_file = os.getenv("BRAINSOS_REQUEST_FILE", "").strip()
    raw_json = Path(req_file).read_text(encoding="utf-8") if (req_file and Path(req_file).is_file()) else sys.stdin.read()
    turn_req = AgentTurnRequest.model_validate_json(raw_json)
    resp = asyncio.run(handle_openai_turn(turn_req))
    print(resp.model_dump_json())
    return 0 if resp.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(_run_ephemeral_cli())
