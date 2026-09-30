"""Warm Hermes Runner Service implementing universal IPC /v1/agent/run."""

import logging
import os
import time
from typing import Any, Dict, List

import httpx

from brainsos_runner import (
    AgentTurnRequest,
    AgentTurnResponse,
    ExecutionMetrics,
    ToolCallRecord,
    create_runner_app,
)

logger = logging.getLogger("brainsos.runners.hermes")
logging.basicConfig(level=logging.INFO)

LITELLM_BASE_URL = os.getenv("OPENAI_BASE_URL", os.getenv("LITELLM_URL", "http://litellm:4000/v1")).rstrip("/")
LITELLM_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("LITELLM_MASTER_KEY", "sk-brainsos-master-key"))


async def handle_hermes_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    """Execute a cognitive turn against LiteLLM via OpenAI-compatible Hermes format."""
    start_time = time.perf_counter()

    # Rule 2: All completions route strictly through LiteLLM
    headers = {
        "Authorization": f"Bearer {LITELLM_API_KEY}",
        "Content-Type": "application/json",
        "X-BrainsOS-Agent": request.agent_id,
        "X-BrainsOS-Run-ID": request.run_id,
    }

    # Assemble conversation
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": request.system_prompt},
    ]
    for msg in request.conversation:
        entry: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        messages.append(entry)

    payload = {
        "model": request.model,
        "messages": messages,
        "temperature": request.extra_params.get("temperature", 0.7),
        "stream": False,
    }

    tool_records: List[ToolCallRecord] = []
    output_text = ""
    prompt_tokens = 0
    completion_tokens = 0

    endpoint = f"{LITELLM_BASE_URL}/chat/completions"

    async with httpx.AsyncClient(timeout=float(request.timeout_sec)) as client:
        try:
            resp = await client.post(endpoint, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                output_text = str(message.get("content") or "").strip()

                raw_tool_calls = message.get("tool_calls", [])
                for idx, tc in enumerate(raw_tool_calls):
                    func = tc.get("function", {})
                    call_id = tc.get("id", f"call_{idx}")
                    tool_name = func.get("name", "unknown")
                    tool_records.append(
                        ToolCallRecord(
                            id=call_id,
                            tool_name=tool_name,
                            arguments=func.get("arguments", {}),
                            output=f"Executed {tool_name}",
                            exit_code=0,
                        )
                    )

                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
            else:
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="failed",
                    output_text="",
                    error_message=f"LiteLLM error HTTP {resp.status_code}: {resp.text}",
                )
        except httpx.ConnectError as err:
            logger.warning("LiteLLM endpoint %s unreachable: %s", endpoint, err)
            # In offline/mock test environments, provide a graceful mock reply if enabled
            if os.getenv("RUNNER_MOCK_FALLBACK", "false").lower() == "true":
                output_text = f"Mock Hermes completion for {request.model}"
            else:
                return AgentTurnResponse(
                    run_id=request.run_id,
                    status="failed",
                    output_text="",
                    error_message=f"Inference gateway unreachable at {endpoint}: {err}",
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


app = create_runner_app(handle_hermes_turn, title="brainsOS Hermes Runner")
