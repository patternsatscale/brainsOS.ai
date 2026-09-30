"""Warm OpenAI SDK Runner Service & Dynamic Script Host."""

import importlib.util
import inspect
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from brainsos_runner import (
    AgentTurnRequest,
    AgentTurnResponse,
    ExecutionMetrics,
    ToolCallRecord,
    create_runner_app,
)

logger = logging.getLogger("brainsos.runners.openai")
logging.basicConfig(level=logging.INFO)

LITELLM_BASE_URL = os.getenv("OPENAI_BASE_URL", os.getenv("LITELLM_URL", "http://litellm:4000/v1")).rstrip("/")
LITELLM_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("LITELLM_MASTER_KEY", "sk-brainsos-master-key"))


def _load_dynamic_script(script_path_str: str) -> Any:
    """Load a custom agent script via importlib with security path verification."""
    script_path = Path(script_path_str).resolve()
    path_str = str(script_path).lower()

    if "docker.sock" in path_str or "memories" in path_str:
        raise PermissionError(f"Access denied: Script path violates isolation guardrails ({script_path})")

    if not script_path.is_file():
        raise FileNotFoundError(f"Custom runner script not found: {script_path}")

    module_name = f"dynamic_agent_{script_path.stem}_{int(time.time())}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module specification from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def handle_openai_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    """Execute turn using OpenAI SDK against LiteLLM or hot-reloaded script."""
    start_time = time.perf_counter()

    client = AsyncOpenAI(
        base_url=LITELLM_BASE_URL,
        api_key=LITELLM_API_KEY,
        timeout=float(request.timeout_sec),
        default_headers={
            "X-BrainsOS-Agent": request.agent_id,
            "X-BrainsOS-Run-ID": request.run_id,
        },
    )

    # 1. Check for dynamic custom script execution
    script_path = request.extra_params.get("script_path")
    if not script_path and request.agent_id:
        convention_path = Path(f"/data/runners/openai-sdk/{request.agent_id}/agent.py")
        if convention_path.is_file():
            script_path = str(convention_path)

    if script_path:
        try:
            module = _load_dynamic_script(str(script_path))
            if not hasattr(module, "handle_turn"):
                raise AttributeError(f"Script {script_path} does not export 'handle_turn' function")

            handler_func = getattr(module, "handle_turn")
            if inspect.iscoroutinefunction(handler_func):
                result = await handler_func(request=request, client=client)
            else:
                result = handler_func(request=request, client=client)

            if isinstance(result, AgentTurnResponse):
                return result
            elif isinstance(result, str):
                duration_ms = int((time.perf_counter() - start_time) * 1000)
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
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Dynamic script execution error: {exc}",
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
                tool_records.append(
                    ToolCallRecord(
                        id=tc.id or f"call_{idx}",
                        tool_name=tc.function.name,
                        arguments={"args": tc.function.arguments},
                        output=f"Invoked {tc.function.name}",
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
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"OpenAI SDK execution failed: {exc}",
            )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

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
