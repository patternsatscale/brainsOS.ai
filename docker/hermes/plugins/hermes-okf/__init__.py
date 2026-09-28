"""hermes-okf plugin — brainsOS Open Knowledge Format memory integration.

Exposes native tools for the Hermes Agent to read, write, and synthesize
human-auditable flat Markdown notes in /memories with zero technical debt.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .okf import HermesOKF, OKFNote, get_memory_dir, get_context_window
from .tools import (
    READ_OKF_NOTE_SCHEMA,
    WRITE_OKF_NOTE_SCHEMA,
    SYNTHESIZE_ACTIVE_RULES_SCHEMA,
    handle_read_okf_note,
    handle_write_okf_note,
    handle_synthesize_active_rules,
)

logger = logging.getLogger(__name__)

__all__ = [
    "HermesOKF",
    "OKFNote",
    "READ_OKF_NOTE_SCHEMA",
    "WRITE_OKF_NOTE_SCHEMA",
    "SYNTHESIZE_ACTIVE_RULES_SCHEMA",
    "handle_read_okf_note",
    "handle_write_okf_note",
    "handle_synthesize_active_rules",
    "register",
]

_TOOLS = (
    (
        "read_okf_note",
        READ_OKF_NOTE_SCHEMA,
        handle_read_okf_note,
        "📖",
        "Read and parse an Open Knowledge Format (OKF) Markdown note from /memories",
    ),
    (
        "write_okf_note",
        WRITE_OKF_NOTE_SCHEMA,
        handle_write_okf_note,
        "✍️",
        "Create or update an Open Knowledge Format (OKF) Markdown note in /memories",
    ),
    (
        "synthesize_active_rules",
        SYNTHESIZE_ACTIVE_RULES_SCHEMA,
        handle_synthesize_active_rules,
        "📋",
        "Synthesize active operator directives and rules from /memories/rules into context",
    ),
)


def _telemetry_llm_request_middleware(request: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Ensure LLM request carries agent identity, session ID, and trace metadata into LiteLLM/Langfuse."""
    import os
    agent_id = os.environ.get("HERMES_AGENT_ID") or os.environ.get("AGENT_ID") or "hermes"
    context_id = kwargs.get("context_id") or "default"
    session_id = f"brainsos-{agent_id}-{context_id}"

    # 1. Attribute to Agent in Langfuse (userId)
    if not request.get("user"):
        request["user"] = agent_id

    # 2. Attach x-litellm-session-id header for LiteLLM Langfuse tracking (sessionId)
    extra_headers = request.setdefault("extra_headers", {})
    if "x-litellm-session-id" not in extra_headers:
        extra_headers["x-litellm-session-id"] = session_id

    # 3. Attach metadata
    metadata = request.setdefault("metadata", {})
    metadata.setdefault("session_id", session_id)
    metadata.setdefault("agent_id", agent_id)
    metadata.setdefault("project", "brainsos")
    metadata.setdefault("plane", "agent")

    # 4. Attach multi-dimensional tags
    tags = metadata.setdefault("tags", [])
    if isinstance(tags, list):
        if agent_id not in tags:
            tags.append(agent_id)
        if "brainsos" not in tags:
            tags.append("brainsos")

    return request


def register(ctx: Any) -> None:
    """Register tools with Hermes Agent plugin loader."""
    logger.info("Registering hermes-okf plugin tools...")
    for name, schema, handler, emoji, desc in _TOOLS:
        try:
            ctx.register_tool(
                name=name,
                toolset="hermes-okf",
                schema=schema,
                handler=handler,
                description=desc,
                emoji=emoji,
            )
        except Exception as e:
            logger.warning("Failed to register tool %s: %s", name, e)

    # Register LLM request middleware for Langfuse session and agent tracking
    if hasattr(ctx, "register_middleware"):
        try:
            ctx.register_middleware("llm_request", _telemetry_llm_request_middleware)
            logger.info("Registered hermes-okf llm_request telemetry middleware with ctx.")
        except Exception as e:
            logger.warning("Failed to register llm_request middleware with ctx: %s", e)

    try:
        import hermes_cli.middleware as hermes_mw
        if hasattr(hermes_mw, "LLM_REQUEST_MIDDLEWARE"):
            if _telemetry_llm_request_middleware not in hermes_mw.LLM_REQUEST_MIDDLEWARE:
                hermes_mw.LLM_REQUEST_MIDDLEWARE.append(_telemetry_llm_request_middleware)
                logger.info("Hooked _telemetry_llm_request_middleware into hermes_cli.middleware.LLM_REQUEST_MIDDLEWARE.")
    except Exception:
        pass


# Pluggable MemoryProvider implementation for upstream plugins.memory discovery
try:
    from agent.memory_provider import MemoryProvider

    class HermesOKFMemoryProvider(MemoryProvider):
        """Pluggable Hermes MemoryProvider implementation for brainsOS OKF."""

        @property
        def name(self) -> str:
            return "hermes-okf"

        def is_available(self) -> bool:
            return True

        def initialize(self, session_id: str, **kwargs) -> None:
            self.okf = HermesOKF()

        def system_prompt_block(self) -> str:
            return self.okf.get_active_rules_context()

        def prefetch(self, query: str, *, session_id: str = "") -> str:
            return ""

        def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
            pass

        def sync_turn(
            self, user_content: str, assistant_content: str, *,
            session_id: str = "", messages: Optional[List[Dict[str, Any]]] = None,
        ) -> None:
            pass

        def get_tool_schemas(self) -> List[Dict[str, Any]]:
            return [READ_OKF_NOTE_SCHEMA, WRITE_OKF_NOTE_SCHEMA, SYNTHESIZE_ACTIVE_RULES_SCHEMA]

        def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
            if tool_name == "read_okf_note":
                return handle_read_okf_note(args)
            elif tool_name == "write_okf_note":
                return handle_write_okf_note(args)
            elif tool_name == "synthesize_active_rules":
                return handle_synthesize_active_rules(args)
            raise NotImplementedError(f"Tool {tool_name} not supported by hermes-okf")

        def shutdown(self) -> None:
            pass

except ImportError:
    pass
