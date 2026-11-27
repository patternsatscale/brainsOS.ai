import os

from brainsos_runner import EphemeralDockerRunnerClient

from brainsos_agent.runtime import AgentRuntime

from .autoresponder import AutoResponderAdapter
from .hermes import HermesMailAdapter, WorkspaceBoundaryViolation, resolve_runner_endpoint
from .runner import RunnerMailAdapter


def _ephemeral_enabled() -> bool:
    return os.getenv("BRAINSOS_EPHEMERAL_RUNNERS", "").strip().lower() in ("1", "true", "yes")


def get_runtime_adapter(runtime: str | None = None) -> AgentRuntime:
    """Factory creating an AgentRuntime adapter matching the agent's declared runtime.

    Routes multi-runner execution across Hermes, OpenAI SDK, and Claude SDK substrates.
    """
    key = (runtime or "hermes").lower().strip()
    if key in ("autoresponder", "echo", "ping", "dummy"):
        return AutoResponderAdapter()
    elif key == "hermes-ephemeral":
        return HermesMailAdapter(ephemeral=True)
    elif key in ("hermes", "nous-hermes", "default", "runner-hermes", "hermes-warm"):
        return HermesMailAdapter(
            runner_url=os.getenv("HERMES_RUNNER_URL"),
            ephemeral=_ephemeral_enabled() if key in ("hermes", "default") else False,
        )
    elif key == "openai-ephemeral":
        return RunnerMailAdapter(runner_id="openai-ephemeral", ephemeral=True)
    elif key in ("openai", "openai-sdk", "openai-warm", "gpt"):
        return RunnerMailAdapter(
            runner_id="openai-ephemeral" if (_ephemeral_enabled() and key != "openai-warm") else "openai-warm",
            ephemeral=_ephemeral_enabled() if key != "openai-warm" else False,
            endpoint=resolve_runner_endpoint(
                None,
                "OPENAI_RUNNER_URL",
                int(os.getenv("OPENAI_RUNNER_PORT", "8002")),
                ("brainsos-agent-runner-openai", "brainsos-runner-openai"),
                8002,
            ),
        )
    elif key == "claude-ephemeral":
        return RunnerMailAdapter(runner_id="claude-ephemeral", ephemeral=True)
    elif key in ("claude", "claude-sdk", "claude-warm", "anthropic"):
        return RunnerMailAdapter(
            runner_id="claude-ephemeral" if (_ephemeral_enabled() and key != "claude-warm") else "claude-warm",
            ephemeral=_ephemeral_enabled() if key != "claude-warm" else False,
            endpoint=resolve_runner_endpoint(
                None,
                "CLAUDE_RUNNER_URL",
                int(os.getenv("CLAUDE_RUNNER_PORT", "8001")),
                ("brainsos-agent-runner-claude", "brainsos-runner-claude"),
                8001,
            ),
        )
    elif key.startswith("runner:"):
        runner_id = key.split(":", 1)[1]
        return RunnerMailAdapter(runner_id=runner_id)
    else:
        raise ValueError(f"Unsupported agent runtime adapter: '{runtime}'")


__all__ = [
    "AutoResponderAdapter",
    "EphemeralDockerRunnerClient",
    "HermesMailAdapter",
    "RunnerMailAdapter",
    "WorkspaceBoundaryViolation",
    "get_runtime_adapter",
]
