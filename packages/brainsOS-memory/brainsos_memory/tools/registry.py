"""Universal agent-facing tools for Open Knowledge Format (OKF) memory."""

from __future__ import annotations

import json
from typing import Any

from brainsos_memory.okf.engine import OKFEngine

READ_OKF_NOTE_SCHEMA: dict[str, Any] = {
    "name": "read_okf_note",
    "description": (
        "Read and parse an Open Knowledge Format (OKF) Markdown note from /memories. "
        "Parses YAML frontmatter metadata and extracts the markdown note body."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "rel_path": {
                "type": "string",
                "description": (
                    "Relative path to the note inside /memories (e.g. 'knowledge/system_design.md', "
                    "'rules/operator_guidelines.md', 'logs/event_summary.md')."
                ),
            },
        },
        "required": ["rel_path"],
        "additionalProperties": False,
    },
}

WRITE_OKF_NOTE_SCHEMA: dict[str, Any] = {
    "name": "write_okf_note",
    "description": (
        "Create or update an Open Knowledge Format (OKF) Markdown note in /memories. "
        "Strictly enforces memory plane purity (only .md files, zero SQLite or binary artifacts) "
        "and atomic file persistence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "rel_path": {
                "type": "string",
                "description": (
                    "Relative path inside /memories where the note must be saved. Must end with '.md' "
                    "(e.g. 'knowledge/topic.md', 'rules/rule_name.md', 'logs/session.md')."
                ),
            },
            "content": {
                "type": "string",
                "description": "Markdown body content or complete note content to persist.",
            },
            "title": {
                "type": "string",
                "description": "Title of the note. Inferred from the first markdown header or filename if omitted.",
            },
            "note_type": {
                "type": "string",
                "enum": ["knowledge", "rules", "logs"],
                "description": "Category or note type. Defaults to the top-level directory name or 'knowledge'.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metadata tags associated with the note.",
            },
            "active": {
                "type": "boolean",
                "description": "Whether the note is active. Relevant for rules and directives. Default is true.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "description": "Priority level of the note. Rules with high priority are synthesized first. Default is 'normal'.",
            },
        },
        "required": ["rel_path", "content"],
        "additionalProperties": False,
    },
}

SYNTHESIZE_ACTIVE_RULES_SCHEMA: dict[str, Any] = {
    "name": "synthesize_active_rules",
    "description": (
        "Synthesize active operator directives and rules from /memories/rules/*.md "
        "into a prioritized, token-budgeted context block for prompt injection."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "max_chars": {
                "type": "integer",
                "description": (
                    "Maximum character length of the synthesized rules block to enforce token budgeting. "
                    "Defaults to dynamic sizing based on INFERENCE_NUM_CTX."
                ),
            },
        },
        "additionalProperties": False,
    },
}


def handle_read_okf_note(args: dict[str, Any], engine: OKFEngine | None = None, **kwargs: Any) -> str:
    """Tool handler for reading an OKF note."""
    engine = engine or OKFEngine()
    rel_path = args.get("rel_path", "")
    if not rel_path:
        return json.dumps({"success": False, "error": "Missing required 'rel_path' parameter."})

    try:
        note = engine.read_note(rel_path)
        return json.dumps(
            {
                "success": True,
                "path": note.rel_path,
                "title": note.title,
                "type": note.note_type,
                "tags": note.tags,
                "active": note.active,
                "priority": note.priority,
                "body": note.body,
                "metadata": note.metadata,
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def handle_write_okf_note(args: dict[str, Any], engine: OKFEngine | None = None, **kwargs: Any) -> str:
    """Tool handler for creating or updating an OKF note."""
    engine = engine or OKFEngine()
    rel_path = args.get("rel_path", "")
    content = args.get("content", "")

    if not rel_path or content is None:
        return json.dumps({"success": False, "error": "Parameters 'rel_path' and 'content' are required."})

    try:
        note = engine.write_note(
            rel_path=rel_path,
            content=content,
            title=args.get("title", ""),
            note_type=args.get("note_type"),
            tags=args.get("tags"),
            active=args.get("active", True),
            priority=args.get("priority", "normal"),
        )
        return json.dumps(
            {
                "success": True,
                "path": note.rel_path,
                "title": note.title,
                "type": note.note_type,
                "tags": note.tags,
                "active": note.active,
                "priority": note.priority,
                "size": len(note.serialize()),
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def handle_synthesize_active_rules(args: dict[str, Any], engine: OKFEngine | None = None, **kwargs: Any) -> str:
    """Tool handler for synthesizing active rules."""
    engine = engine or OKFEngine()
    max_chars = args.get("max_chars")
    try:
        rules_text = engine.get_active_rules_context(max_chars=max_chars)
        return json.dumps(
            {
                "success": True,
                "rules_context": rules_text,
                "character_count": len(rules_text),
            }
        )
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
