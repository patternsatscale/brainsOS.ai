"""Tool registry and adapters for brainsOS-memory."""

from brainsos_memory.tools.hermes_adapter import register_hermes_tools
from brainsos_memory.tools.registry import (
    READ_OKF_NOTE_SCHEMA,
    SYNTHESIZE_ACTIVE_RULES_SCHEMA,
    WRITE_OKF_NOTE_SCHEMA,
    handle_read_okf_note,
    handle_synthesize_active_rules,
    handle_write_okf_note,
)

__all__ = [
    "READ_OKF_NOTE_SCHEMA",
    "SYNTHESIZE_ACTIVE_RULES_SCHEMA",
    "WRITE_OKF_NOTE_SCHEMA",
    "handle_read_okf_note",
    "handle_synthesize_active_rules",
    "handle_write_okf_note",
    "register_hermes_tools",
]
