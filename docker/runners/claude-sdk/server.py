"""Warm Anthropic Claude SDK Runner Service supporting direct API and AWS Bedrock."""

import importlib.util
import inspect
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from brainsos_runner import (
    AgentTurnRequest,
    AgentTurnResponse,
    ExecutionMetrics,
    ToolCallRecord,
    create_runner_app,
)

logger = logging.getLogger("brainsos.runners.claude")
logging.basicConfig(level=logging.INFO)


def _load_dynamic_script(script_path_str: str) -> Any:
    """Load a custom agent script via importlib with security path verification."""
    script_path = Path(script_path_str).resolve()
    path_str = str(script_path).lower()

    if "docker.sock" in path_str or "memories" in path_str:
        raise PermissionError(f"Access denied: Script path violates isolation guardrails ({script_path})")

    if not script_path.is_file():
        raise FileNotFoundError(f"Custom runner script not found: {script_path}")

    module_name = f"dynamic_claude_agent_{script_path.stem}_{int(time.time())}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module specification from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_anthropic_client(timeout_sec: float) -> Any:
    """Instantiate AsyncAnthropic client for Direct API, Amazon Bedrock, or LiteLLM gateway."""
    use_bedrock = os.getenv("CLAUDE_USE_BEDROCK", "false").lower() in ("true", "1")

    if use_bedrock:
        try:
            from anthropic import AsyncAnthropicBedrock

            logger.info("Initializing Anthropic Bedrock client")
            return AsyncAnthropicBedrock(
                aws_region=os.getenv("AWS_REGION", "us-east-1"),
                timeout=timeout_sec,
            )
        except Exception as exc:
            logger.warning("Could not initialize Bedrock client, falling back to standard API: %s", exc)

    from anthropic import AsyncAnthropic

    base_url = os.getenv("ANTHROPIC_BASE_URL", os.getenv("LITELLM_URL", "http://litellm:4000")).rstrip("/")
    api_key = os.getenv("ANTHROPIC_API_KEY", os.getenv("LITELLM_MASTER_KEY", "sk-brainsos-master-key"))
    return AsyncAnthropic(base_url=base_url, api_key=api_key, timeout=timeout_sec)


async def handle_claude_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    """Execute a cognitive turn using the Anthropic Claude SDK or custom dynamic script."""
    start_time = time.perf_counter()
    timeout_sec = float(request.timeout_sec)

    try:
        client = _get_anthropic_client(timeout_sec)
    except Exception as exc:
        client = None
        logger.warning("Could not instantiate Anthropic client: %s", exc)

    # 1. Check for dynamic custom script execution
    script_path = request.extra_params.get("script_path")
    if not script_path and request.agent_id:
        convention_path = Path(f"/data/runners/claude-sdk/{request.agent_id}/agent.py")
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

    # Convert conversation turns to Anthropic schema (system prompt is separate)
    messages: List[Dict[str, Any]] = []
    for msg in request.conversation:
        role = "assistant" if msg.role == "assistant" else "user"
        messages.append({"role": role, "content": msg.content})

    # Ensure conversation is not empty
    if not messages:
        messages = [{"role": "user", "content": "Hello"}]

    output_text = ""
    tool_records: List[ToolCallRecord] = []
    prompt_tokens = 0
    completion_tokens = 0

    try:
        # Determine model identifier
        model = request.model or os.getenv("CLAUDE_DEFAULT_MODEL", "claude-3-7-sonnet-20250219")

        response = await client.messages.create(
            model=model,
            max_tokens=request.extra_params.get("max_tokens", 4096),
            system=request.system_prompt,
            messages=messages,
        )

        for block in response.content:
            if getattr(block, "type", "") == "text":
                output_text += block.text
            elif getattr(block, "type", "") == "tool_use":
                tool_records.append(
                    ToolCallRecord(
                        id=block.id,
                        tool_name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                        output=f"Tool {block.name} called",
                        exit_code=0,
                    )
                )

        if response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens

    except Exception as exc:
        logger.warning("Anthropic API call failed: %s", exc)
        if os.getenv("RUNNER_MOCK_FALLBACK", "false").lower() == "true":
            output_text = f"Mock Claude reply for {request.model}"
        else:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Anthropic SDK execution failed: {exc}",
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


app = create_runner_app(handle_claude_turn, title="brainsOS Claude Runner")
