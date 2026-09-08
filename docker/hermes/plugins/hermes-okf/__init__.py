"""hermes-okf plugin — Project Titan Open Knowledge Format memory integration.

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


# Pluggable MemoryProvider implementation for upstream plugins.memory discovery
try:
    from agent.memory_provider import MemoryProvider

    class HermesOKFMemoryProvider(MemoryProvider):
        """Pluggable Hermes MemoryProvider implementation for Titan OKF."""

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
