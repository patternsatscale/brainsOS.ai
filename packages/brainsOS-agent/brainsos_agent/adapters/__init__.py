"""Adapter implementations connecting brainsOS agents to execution runtimes."""

from __future__ import annotations

from brainsos_agent.runtime import AgentRuntime
from .autoresponder import AutoResponderAdapter
from .hermes import HermesMailAdapter, WorkspaceBoundaryViolation


def get_runtime_adapter(runtime: str | None = None) -> AgentRuntime:
    """Factory creating an AgentRuntime adapter matching the agent's declared runtime.

    Prepares brainsOS-agent for multi-runner execution ahead of Epic #185.
    """
    key = (runtime or "hermes").lower().strip()
    if key in ("autoresponder", "echo", "ping", "dummy"):
        return AutoResponderAdapter()
    elif key in ("hermes", "nous-hermes", "default"):
        return HermesMailAdapter()
    else:
        raise ValueError(f"Unsupported agent runtime adapter: '{runtime}'")


__all__ = [
    "AutoResponderAdapter",
    "HermesMailAdapter",
    "WorkspaceBoundaryViolation",
    "get_runtime_adapter",
]
