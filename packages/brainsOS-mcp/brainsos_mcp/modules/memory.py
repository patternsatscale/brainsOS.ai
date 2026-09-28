"""brainsos_mcp.modules.memory — Open Knowledge Format memory capabilities."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def get_memory_root() -> str:
    """Resolve active OKF memories directory."""
    candidates = [
        os.environ.get("BRAINSOS_MEMORY_ROOT", ""),
        "/memories",
        os.path.abspath("./data/agent_memories"),
        os.path.abspath("./data/agent_memories/default"),
        os.path.abspath("./memories"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return os.environ.get("BRAINSOS_MEMORY_ROOT") or "/memories"


def register_memory_tools(mcp: FastMCP) -> list[str]:
    """Register memory plane tools onto the FastMCP server."""
    from brainsos_memory.okf.engine import OKFEngine

    @mcp.tool()
    def read_memory(rel_path: str) -> str:
        """Read OKF note from /memories."""
        engine = OKFEngine(root_dir=get_memory_root())
        try:
            note = engine.read_note(rel_path)
            return json.dumps({
                "success": True,
                "rel_path": rel_path,
                "title": note.title,
                "body": note.body,
                "metadata": note.metadata,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def write_memory(rel_path: str, content: str, title: str = "") -> str:
        """Write OKF note to /memories."""
        engine = OKFEngine(root_dir=get_memory_root())
        try:
            note = engine.write_note(rel_path=rel_path, content=content, title=title)
            return json.dumps({
                "success": True,
                "rel_path": rel_path,
                "title": note.title,
                "size_bytes": len(note.serialize()),
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return ["read_memory", "write_memory"]
