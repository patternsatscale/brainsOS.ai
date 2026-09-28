"""Hermes Plugin Integration for brainsos_memory tools.

Re-exports schemas and handlers from brainsos_memory.tools.
"""

from __future__ import annotations

from brainsos_memory.tools import (
    READ_OKF_NOTE_SCHEMA,
    WRITE_OKF_NOTE_SCHEMA,
    SYNTHESIZE_ACTIVE_RULES_SCHEMA,
    handle_read_okf_note,
    handle_write_okf_note,
    handle_synthesize_active_rules,
)

__all__ = [
    "READ_OKF_NOTE_SCHEMA",
    "WRITE_OKF_NOTE_SCHEMA",
    "SYNTHESIZE_ACTIVE_RULES_SCHEMA",
    "handle_read_okf_note",
    "handle_write_okf_note",
    "handle_synthesize_active_rules",
]
