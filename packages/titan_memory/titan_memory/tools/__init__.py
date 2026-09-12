"""Tool registry and adapters for titan-memory."""

from titan_memory.tools.registry import (
    READ_OKF_NOTE_SCHEMA,
    WRITE_OKF_NOTE_SCHEMA,
    SYNTHESIZE_ACTIVE_RULES_SCHEMA,
    handle_read_okf_note,
    handle_write_okf_note,
    handle_synthesize_active_rules,
)
from titan_memory.tools.hermes_adapter import register_hermes_tools

__all__ = [
    "READ_OKF_NOTE_SCHEMA",
    "WRITE_OKF_NOTE_SCHEMA",
    "SYNTHESIZE_ACTIVE_RULES_SCHEMA",
    "handle_read_okf_note",
    "handle_write_okf_note",
    "handle_synthesize_active_rules",
    "register_hermes_tools",
]
