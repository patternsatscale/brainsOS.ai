"""Agent-facing tools for the hermes-okf plugin.

Tools:
  - read_okf_note: Parse metadata frontmatter and Markdown body from /memories.
  - write_okf_note: Create and update compliant OKF notes adhering to memory purity.
  - synthesize_active_rules: Synthesize active system and operator directives into context.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .okf import HermesOKF


READ_OKF_NOTE_SCHEMA: Dict[str, Any] = {
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

WRITE_OKF_NOTE_SCHEMA: Dict[str, Any] = {
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

SYNTHESIZE_ACTIVE_RULES_SCHEMA: Dict[str, Any] = {
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
                    "Maximum character budget for the synthesized context block. "
                    "If omitted, automatically scales based on the active model context window."
                ),
            },
        },
        "additionalProperties": False,
    },
}


def handle_read_okf_note(args: Dict[str, Any], **_kw) -> str:
    """Handle read_okf_note function call."""
    rel_path = args.get("rel_path") or args.get("path")
    if not rel_path:
        return json.dumps(
            {"success": False, "error": "Missing required parameter 'rel_path'"},
            ensure_ascii=False,
        )

    try:
        okf = HermesOKF()
        note = okf.read_note(rel_path)
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
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"success": False, "error": str(e)},
            ensure_ascii=False,
        )


def handle_write_okf_note(args: Dict[str, Any], **_kw) -> str:
    """Handle write_okf_note function call."""
    rel_path = args.get("rel_path") or args.get("path")
    content = args.get("content") or args.get("body")

    if not rel_path:
        return json.dumps(
            {"success": False, "error": "Missing required parameter 'rel_path'"},
            ensure_ascii=False,
        )
    if content is None:
        return json.dumps(
            {"success": False, "error": "Missing required parameter 'content'"},
            ensure_ascii=False,
        )

    title = args.get("title", "")
    note_type = args.get("note_type") or args.get("type")
    tags = args.get("tags")
    active = args.get("active", True)
    priority = args.get("priority", "normal")

    try:
        okf = HermesOKF()
        saved = okf.write_note(
            rel_path=rel_path,
            content=content,
            title=title,
            note_type=note_type,
            tags=tags,
            active=active,
            priority=priority,
        )
        return json.dumps(
            {
                "success": True,
                "path": saved.rel_path,
                "title": saved.title,
                "type": saved.note_type,
                "tags": saved.tags,
                "active": saved.active,
                "priority": saved.priority,
                "message": f"Successfully written OKF note to {saved.rel_path}",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"success": False, "error": str(e)},
            ensure_ascii=False,
        )


def handle_synthesize_active_rules(args: Dict[str, Any], **_kw) -> str:
    """Handle synthesize_active_rules function call."""
    max_chars = args.get("max_chars")
    if max_chars is not None:
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = None

    try:
        okf = HermesOKF()
        ctx = okf.get_active_rules_context(max_chars=max_chars)
        return json.dumps(
            {
                "success": True,
                "rules_context": ctx,
                "length": len(ctx),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"success": False, "error": str(e)},
            ensure_ascii=False,
        )
