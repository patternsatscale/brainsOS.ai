"""brainsOS - Clean Native Open Knowledge Format (OKF) Engine.

Manages human-auditable flat-file Markdown memories across:
- /memories/knowledge/
- /memories/rules/
- /memories/logs/

Enforces Inviolable Rule 1 (Memory Plane Purity):
- Strictly flat Markdown (.md) files only.
- Zero binary data, zero SQLite/embedded databases, zero cache directories.
- Safe path resolution blocking directory traversal outside the memory root.

Enforces Inviolable Rule 7 (Information Compartmentalization):
- Zero leakage of host infrastructure or database internals in prompts or contexts.
"""

from __future__ import annotations

import os
from typing import Any

from brainsos_memory.okf.models import OKFNote
from brainsos_memory.okf.purity import (
    FORBIDDEN_DIRECTORIES,
    resolve_safe_path,
)
from brainsos_memory.okf.purity import (
    validate_purity as run_purity_validation,
)
from brainsos_memory.vector.base import VectorStore
from brainsos_memory.vector.null import NullVectorStore


def get_memory_dir() -> str:
    """Return configured memory plane root directory."""
    return os.environ.get("MEMORY_DIR", "/memories")


def get_context_window() -> int:
    """Return model context budget from environment or fallback to 4096."""
    try:
        return int(os.environ.get("INFERENCE_NUM_CTX", 4096))
    except (ValueError, TypeError):
        return 4096


class OKFEngine:
    """Core Open Knowledge Format (OKF) memory manager."""

    def __init__(
        self,
        root_dir: str | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.root_dir = os.path.abspath(root_dir or get_memory_dir())
        self.knowledge_dir = os.path.join(self.root_dir, "knowledge")
        self.rules_dir = os.path.join(self.root_dir, "rules")
        self.logs_dir = os.path.join(self.root_dir, "logs")
        self.vector_store = vector_store or NullVectorStore()

        for d in (self.knowledge_dir, self.rules_dir, self.logs_dir):
            os.makedirs(d, exist_ok=True)

    def _resolve_safe_path(self, rel_path: str) -> str:
        """Resolve target path ensuring it remains within root_dir."""
        return resolve_safe_path(self.root_dir, rel_path)

    def list_notes(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all valid OKF notes with metadata."""
        results: list[dict[str, Any]] = []
        target_dir = self.root_dir
        if category and category in ("knowledge", "rules", "logs"):
            target_dir = os.path.join(self.root_dir, category)

        if not os.path.exists(target_dir):
            return results

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIRECTORIES and not d.startswith(".")]

            for fname in sorted(files):
                if fname.endswith(".md") and not fname.startswith("."):
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, self.root_dir)
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        note = OKFNote.parse(rel_path, content)
                        results.append({
                            "path": rel_path,
                            "title": note.title,
                            "type": note.note_type,
                            "tags": note.tags,
                            "active": note.active,
                            "priority": note.priority,
                            "size": os.path.getsize(full_path),
                            "modified": os.path.getmtime(full_path),
                        })
                    except Exception as e:
                        results.append({
                            "path": rel_path,
                            "title": fname,
                            "error": str(e),
                        })
        return results

    def read_note(self, rel_path: str) -> OKFNote:
        """Read and parse an OKF note by relative path."""
        target = self._resolve_safe_path(rel_path)
        if not os.path.isfile(target):
            raise FileNotFoundError(f"Note not found: {rel_path}")

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        clean_rel = os.path.relpath(target, self.root_dir)
        return OKFNote.parse(clean_rel, content)

    def write_note(
        self,
        rel_path: str,
        content: str,
        title: str = "",
        note_type: str | None = None,
        tags: list[str] | None = None,
        active: bool = True,
        priority: str = "normal",
    ) -> OKFNote:
        """Atomically write an OKF note, strictly enforcing Rule 1 purity."""
        if not rel_path.endswith(".md"):
            raise ValueError(f"Memory purity violation: '{rel_path}' must end with .md extension.")

        if "\0" in content:
            raise ValueError("Memory purity violation: binary data cannot be written to memory plane.")

        target = self._resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)

        if not note_type:
            first_part = rel_path.replace("\\", "/").split("/")[0]
            note_type = first_part if first_part in ("knowledge", "rules", "logs") else "knowledge"

        if content.startswith("---"):
            note = OKFNote.parse(rel_path, content)
            if title:
                note.title = title
            if tags:
                note.tags = tags
            note.active = active
            note.priority = priority
            serialized = note.serialize()
        else:
            note = OKFNote(
                rel_path=rel_path,
                title=title,
                note_type=note_type,
                tags=tags or [],
                active=active,
                priority=priority,
                body=content,
            )
            serialized = note.serialize()

        temp_target = target + ".tmp"
        with open(temp_target, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(temp_target, target)

        try:
            os.chmod(target, 0o664)
        except OSError:
            pass

        # Update vector store hook (no-op if NullVectorStore)
        try:
            self.vector_store.upsert_note(note)
        except Exception:
            pass

        return note

    def search(self, query: str, category: str | None = None) -> list[dict[str, Any]]:
        """Full-text case-insensitive keyword search across OKF notes."""
        q = query.lower().strip()
        if not q:
            return []

        results = []
        all_notes = self.list_notes(category)
        for item in all_notes:
            rel_path = item.get("path")
            if not rel_path:
                continue
            try:
                note = self.read_note(rel_path)
                match_in_title = q in note.title.lower()
                match_in_tags = any(q in t.lower() for t in note.tags)
                match_in_body = q in note.body.lower()

                if match_in_title or match_in_tags or match_in_body:
                    if match_in_body:
                        idx = note.body.lower().find(q)
                        start = max(0, idx - 60)
                        end = min(len(note.body), idx + 100)
                        snippet = ("..." if start > 0 else "") + note.body[start:end].strip() + "..."
                    else:
                        snippet = note.body[:120].strip() + ("..." if len(note.body) > 120 else "")

                    results.append({
                        "path": rel_path,
                        "title": note.title,
                        "type": note.note_type,
                        "tags": note.tags,
                        "snippet": snippet,
                    })
            except Exception:
                continue

        return results

    def get_active_rules_context(self, max_chars: int | None = None) -> str:
        """
        Synthesizes active operator rules from /memories/rules/*.md
        into a prioritized, budgeted prompt section.
        """
        ctx_tokens = get_context_window()
        if max_chars is None:
            max_chars = 8000 if ctx_tokens >= 16384 else 2000

        rules = []
        if not os.path.exists(self.rules_dir):
            return ""

        for fname in sorted(os.listdir(self.rules_dir)):
            if fname.endswith(".md") and not fname.startswith(".") and fname not in ("README.md", "template.md"):
                rel_path = os.path.join("rules", fname)
                try:
                    note = self.read_note(rel_path)
                    if note.active:
                        rules.append(note)
                except Exception:
                    continue

        if not rules:
            return ""

        priority_order = {"high": 0, "normal": 1, "low": 2}
        rules.sort(key=lambda r: priority_order.get(r.priority, 1))

        output_lines = ["\n[OPERATOR RULES & GUARDRAILS - /memories/rules]"]
        total_len = len(output_lines[0])

        for r in rules:
            rule_entry = f"\n- Rule '{r.title}': {r.body}"
            if total_len + len(rule_entry) > max_chars:
                output_lines.append("\n- [Additional rules truncated to preserve token budget]")
                break
            output_lines.append(rule_entry)
            total_len += len(rule_entry)

        return "".join(output_lines)

    def get_working_memory_context(self, max_chars: int | None = None) -> str:
        """Loads the active working memory note if available."""
        ctx_tokens = get_context_window()
        if max_chars is None:
            max_chars = 4000 if ctx_tokens >= 16384 else 1200

        target = os.path.join(self.knowledge_dir, "working_memory.md")
        if not os.path.isfile(target):
            return ""

        try:
            note = self.read_note("knowledge/working_memory.md")
            body = note.body[:max_chars].strip()
            return f"\n[WORKING MEMORY & SCRATCHPAD - knowledge/working_memory.md]\n{body}\n"
        except Exception:
            return ""

    def validate_purity(self) -> tuple[bool, list[str]]:
        """Scans root_dir to enforce absolute memory plane purity (Rule 1)."""
        return run_purity_validation(self.root_dir)


# Backward compatibility alias
HermesOKF = OKFEngine
