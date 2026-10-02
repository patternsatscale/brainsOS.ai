"""Open Knowledge Format (OKF) Note Data Models & Frontmatter Parser."""

from __future__ import annotations

import os
import re
from typing import Any


class OKFNote:
    """Represents a structured Open Knowledge Format Markdown note."""

    def __init__(
        self,
        rel_path: str,
        title: str = "",
        note_type: str = "knowledge",
        tags: list[str] | None = None,
        active: bool = True,
        priority: str = "normal",
        body: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        self.rel_path = rel_path
        self.title = title or os.path.splitext(os.path.basename(rel_path))[0]
        self.note_type = note_type
        self.tags = tags or []
        self.active = active
        self.priority = priority.lower() if priority else "normal"
        self.body = body.strip()
        self.metadata = metadata or {}

    @classmethod
    def parse(cls, rel_path: str, raw_content: str) -> OKFNote:
        """Parse raw markdown content and extract YAML frontmatter."""
        frontmatter: dict[str, Any] = {}
        body = raw_content

        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", raw_content, re.DOTALL)
        if match:
            fm_text = match.group(1)
            body = match.group(2).strip()

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
