import os

from brainsos_agent.runtime import AgentRuntime

from .autoresponder import AutoResponderAdapter
from .hermes import HermesMailAdapter, WorkspaceBoundaryViolation
from .runner import RunnerMailAdapter


def get_runtime_adapter(runtime: str | None = None) -> AgentRuntime:
    """Factory creating an AgentRuntime adapter matching the agent's declared runtime.

    Routes multi-runner execution across Hermes, OpenAI SDK, and Claude SDK substrates.
    """
    key = (runtime or "hermes").lower().strip()
    if key in ("autoresponder", "echo", "ping", "dummy"):
        return AutoResponderAdapter()
    elif key in ("hermes", "nous-hermes", "default"):
        return HermesMailAdapter()
    elif key in ("openai", "openai-sdk", "openai-warm", "gpt"):
        return RunnerMailAdapter(
            runner_id="openai-warm",
            endpoint=os.getenv("OPENAI_RUNNER_URL", "http://127.0.0.1:8002"),
        )
    elif key in ("claude", "claude-sdk", "claude-warm", "anthropic"):
        return RunnerMailAdapter(
            runner_id="claude-warm",
            endpoint=os.getenv("CLAUDE_RUNNER_URL", "http://127.0.0.1:8001"),
        )
    elif key in ("runner-hermes", "hermes-warm"):
        return RunnerMailAdapter(
            runner_id="hermes-warm",
            endpoint=os.getenv("HERMES_RUNNER_URL", "http://127.0.0.1:8642"),
        )
    elif key.startswith("runner:"):
        runner_id = key.split(":", 1)[1]
        return RunnerMailAdapter(runner_id=runner_id)
    else:
        raise ValueError(f"Unsupported agent runtime adapter: '{runtime}'")


__all__ = [
    "AutoResponderAdapter",
    "HermesMailAdapter",
    "RunnerMailAdapter",
    "WorkspaceBoundaryViolation",
    "get_runtime_adapter",
]
