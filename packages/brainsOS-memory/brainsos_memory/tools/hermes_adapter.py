"""Adapter for registering OKF memory tools with the Hermes agent runtime."""

from __future__ import annotations

import logging
from typing import Any

from brainsos_memory.tools.registry import (
    READ_OKF_NOTE_SCHEMA,
    SYNTHESIZE_ACTIVE_RULES_SCHEMA,
    WRITE_OKF_NOTE_SCHEMA,
    handle_read_okf_note,
    handle_synthesize_active_rules,
    handle_write_okf_note,
)

logger = logging.getLogger(__name__)

HERMES_TOOLS = (
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


def register_hermes_tools(ctx: Any) -> None:
    """Register native OKF tools with Hermes Agent plugin loader."""
    logger.info("Registering brainsOS-memory tools with Hermes...")
    for name, schema, handler, emoji, desc in HERMES_TOOLS:
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
