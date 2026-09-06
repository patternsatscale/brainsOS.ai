#!/usr/bin/env python3
"""
Project Titan - Hermes Open Knowledge Format (OKF) Memory Plugin
Manages human-auditable flat-file Markdown memories across:
- /memories/knowledge/
- /memories/rules/
- /memories/logs/

Features:
- YAML frontmatter parsing and serialization (zero external dependencies)
- Active rule synthesis and context injection respecting INFERENCE_NUM_CTX budgets
- Working memory scratchpad integration
- On-demand full-text search across knowledge and logs
- Strict memory plane purity enforcement (blocks sqlite, binary files, caches)
- Dual mode: importable Python module and CLI skill runner
"""

import os
import re
import sys
import json
from typing import Dict, List, Optional, Tuple, Any


def get_memory_dir() -> str:
    return os.environ.get("MEMORY_DIR", "/memories")


def get_context_window() -> int:
    try:
        return int(os.environ.get("INFERENCE_NUM_CTX", 4096))
    except (ValueError, TypeError):
        return 4096


# Forbidden extensions and patterns inside the memory plane
FORBIDDEN_EXTENSIONS = {
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".so", ".bin",
    ".tar", ".gz", ".zip", ".lock", ".log", ".tmp", ".bak"
}

FORBIDDEN_DIRECTORIES = {
    "__pycache__", "node_modules", ".cache", ".venv", "venv", ".git"
}


class OKFNote:
    """Represents a structured Open Knowledge Format Markdown note."""

    def __init__(
        self,
        rel_path: str,
        title: str = "",
        note_type: str = "knowledge",
        tags: Optional[List[str]] = None,
        active: bool = True,
        priority: str = "normal",
        body: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.rel_path = rel_path
        self.title = title or os.path.splitext(os.path.basename(rel_path))[0]
        self.note_type = note_type
        self.tags = tags or []
        self.active = active
        self.priority = priority
        self.body = body.strip()
        self.metadata = metadata or {}

    @classmethod
    def parse(cls, rel_path: str, raw_content: str) -> "OKFNote":
        """Parse raw markdown content and extract YAML frontmatter."""
        frontmatter = {}
        body = raw_content

        # Match frontmatter delimited by ---
        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", raw_content, re.DOTALL)
        if match:
            fm_text = match.group(1)
            body = match.group(2).strip()

            # Lightweight YAML parser for flat/simple lists
            current_list_key = None
            for line in fm_text.splitlines():
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue

                if line_str.startswith("- ") and current_list_key:
                    item = line_str[2:].strip().strip("\"'")
                    frontmatter[current_list_key].append(item)
                    continue

                current_list_key = None
                if ":" in line_str:
                    key, val = line_str.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")

                    if val == "":
                        frontmatter[key] = []
                        current_list_key = key
                    elif val.lower() == "true":
                        frontmatter[key] = True
                    elif val.lower() == "false":
                        frontmatter[key] = False
                    else:
                        frontmatter[key] = val

        title = frontmatter.get("title", "")
        if not title:
            # Try to infer title from first # Header
            header_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            if header_match:
                title = header_match.group(1).strip()
            else:
                title = os.path.splitext(os.path.basename(rel_path))[0]

        note_type = frontmatter.get("type", "knowledge")
        tags = frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        active = frontmatter.get("active", True)
        if isinstance(active, str):
            active = active.lower() != "false"

        priority = str(frontmatter.get("priority", "normal")).lower()

        return cls(
            rel_path=rel_path,
            title=title,
            note_type=note_type,
            tags=tags,
            active=active,
            priority=priority,
            body=body,
            metadata=frontmatter,
        )

    def serialize(self) -> str:
        """Serialize note into pure Markdown with standard YAML frontmatter."""
        fm_lines = [
            "---",
            f"title: {self.title}",
            f"type: {self.note_type}",
            f"active: {'true' if self.active else 'false'}",
            f"priority: {self.priority}",
        ]
        if self.tags:
            fm_lines.append("tags:")
            for t in self.tags:
                fm_lines.append(f"  - {t}")

        for k, v in self.metadata.items():
            if k not in ("title", "type", "active", "priority", "tags"):
                if isinstance(v, list):
                    fm_lines.append(f"{k}:")
                    for item in v:
                        fm_lines.append(f"  - {item}")
                else:
                    fm_lines.append(f"{k}: {v}")

        fm_lines.append("---")
        fm_lines.append("")
        fm_lines.append(self.body)
        fm_lines.append("")
        return "\n".join(fm_lines)


class HermesOKF:
    """Core Open Knowledge Format (OKF) memory manager for Hermes."""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = os.path.abspath(root_dir or get_memory_dir())
        self.knowledge_dir = os.path.join(self.root_dir, "knowledge")
        self.rules_dir = os.path.join(self.root_dir, "rules")
        self.logs_dir = os.path.join(self.root_dir, "logs")

        # Ensure directory scaffolding exists
        for d in (self.knowledge_dir, self.rules_dir, self.logs_dir):
            os.makedirs(d, exist_ok=True)

    def _resolve_safe_path(self, rel_path: str) -> str:
        """Resolve and validate that the target path remains within root_dir."""
        clean_rel = os.path.normpath(rel_path.strip().lstrip("/"))
        abs_path = os.path.abspath(os.path.join(self.root_dir, clean_rel))
        if not abs_path.startswith(self.root_dir):
            raise ValueError(f"Access denied: path '{rel_path}' traverses outside memory root.")
        return abs_path

    def list_notes(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all valid OKF notes with metadata."""
        results = []
        target_dir = self.root_dir
        if category and category in ("knowledge", "rules", "logs"):
            target_dir = os.path.join(self.root_dir, category)

        if not os.path.exists(target_dir):
            return results

        for root, dirs, files in os.walk(target_dir):
            # Exclude forbidden directories
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
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        active: bool = True,
        priority: str = "normal",
    ) -> OKFNote:
        """Atomically write an OKF note, strictly enforcing purity."""
        if not rel_path.endswith(".md"):
            raise ValueError(f"Memory purity violation: '{rel_path}' must end with .md extension.")

        # Check for binary content
        if "\0" in content:
            raise ValueError("Memory purity violation: binary data cannot be written to memory plane.")

        target = self._resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)

        # Infer category/type from path if not provided
        if not note_type:
            first_part = rel_path.split(os.sep)[0]
            note_type = first_part if first_part in ("knowledge", "rules", "logs") else "knowledge"

        # If content already has YAML frontmatter, preserve and merge
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

        # Atomic file write
        temp_target = target + ".tmp"
        with open(temp_target, "w", encoding="utf-8") as f:
            f.write(serialized)
        os.replace(temp_target, target)

        # Uniform permissions (readable/writable by 1000:1000)
        try:
            os.chmod(target, 0o664)
        except OSError:
            pass

        return note

    def search(self, query: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
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
                    # Extract snippet
                    snippet = ""
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

    def get_active_rules_context(self, max_chars: Optional[int] = None) -> str:
        """
        Synthesizes active operator rules from /memories/rules/*.md
        into a concise, budgeted prompt section.
        Adapts budget based on active INFERENCE_NUM_CTX.
        """
        ctx_tokens = get_context_window()
        if max_chars is None:
            # Scale budget: ~1,500 chars for 4k context, ~8,000 chars for 32k GX10
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

        # Sort priority: high -> normal -> low
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

    def get_working_memory_context(self, max_chars: Optional[int] = None) -> str:
        """
        Loads the active working memory note (/memories/knowledge/working_memory.md)
        if available and context budget permits.
        """
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

    def validate_purity(self) -> Tuple[bool, List[str]]:
        """
        Scans /memories to enforce absolute memory plane purity.
        Returns (is_pure, violations).
        """
        violations = []
        for root, dirs, files in os.walk(self.root_dir):
            rel_dir = os.path.relpath(root, self.root_dir)

            for d in dirs:
                if d in FORBIDDEN_DIRECTORIES:
                    violations.append(f"Forbidden directory '{d}' inside {rel_dir}")

            for f in files:
                if f.startswith(".gitkeep"):
                    continue
                _, ext = os.path.splitext(f)
                ext_lower = ext.lower()

                if ext_lower in FORBIDDEN_EXTENSIONS:
                    violations.append(f"Forbidden file type '{f}' ({ext_lower}) in {rel_dir}")
                elif ext_lower != ".md" and not f.startswith("."):
                    violations.append(f"Non-markdown file '{f}' in {rel_dir}")

        return (len(violations) == 0, violations)


def main():
    """CLI runner for testing and execution in Hermes sandbox terminal."""
    if len(sys.argv) < 2:
        print("Usage: hermes_okf.py <list|read|write|search|rules|working-memory|purity> [args...]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    okf = HermesOKF()

    if cmd == "list":
        category = sys.argv[2] if len(sys.argv) > 2 else None
        notes = okf.list_notes(category)
        print(json.dumps(notes, indent=2))

    elif cmd == "read":
        if len(sys.argv) < 3:
            print("Error: Specify relative note path (e.g. knowledge/architecture.md)")
            sys.exit(1)
        try:
            note = okf.read_note(sys.argv[2])
            print(f"Title: {note.title}")
            print(f"Type: {note.note_type} | Priority: {note.priority} | Active: {note.active}")
            print(f"Tags: {', '.join(note.tags)}")
            print("-" * 60)
            print(note.body)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif cmd == "write":
        if len(sys.argv) < 4:
            print("Error: Usage: hermes_okf.py write <rel_path> <content> [title]")
            sys.exit(1)
        rel_path = sys.argv[2]
        content = sys.argv[3]
        title = sys.argv[4] if len(sys.argv) > 4 else ""
        try:
            saved = okf.write_note(rel_path, content, title=title)
            print(f"Success: Note saved to {saved.rel_path} (Title: {saved.title})")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Error: Usage: hermes_okf.py search <query> [category]")
            sys.exit(1)
        query = sys.argv[2]
        cat = sys.argv[3] if len(sys.argv) > 3 else None
        results = okf.search(query, cat)
        print(json.dumps(results, indent=2))

    elif cmd == "rules":
        ctx = okf.get_active_rules_context()
        print(ctx if ctx else "(No active rules)")

    elif cmd == "working-memory":
        wm = okf.get_working_memory_context()
        print(wm if wm else "(Working memory empty or absent)")

    elif cmd == "purity":
        is_pure, violations = okf.validate_purity()
        if is_pure:
            print("OK: Memory plane is 100% pure (flat-file Markdown only).")
        else:
            print("VIOLATIONS DETECTED:")
            for v in violations:
                print(f" - {v}")
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
