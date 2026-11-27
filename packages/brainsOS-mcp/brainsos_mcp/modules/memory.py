"""brainsos_mcp.modules.memory — Open Knowledge Format memory capabilities."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_MAIL_SESSION_RE = re.compile(r"^mail-([a-z0-9_-]+)-")
_SAFE_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_OKF_CATEGORIES = frozenset({"knowledge", "logs", "rules", "research", "notes", "people", "threads"})


def get_memory_root() -> str:
    """Resolve active OKF memories directory."""
    data_dir = os.environ.get("BRAINSOS_DATA_DIR", "")
    agents_dir = os.environ.get("BRAINSOS_AGENTS_DIR", "")
    memories_dir = os.environ.get("BRAINSOS_MEMORIES_DIR", os.environ.get("BRAINSOS_AGENT_MEMORIES_DIR", ""))
    candidates = [
        os.environ.get("BRAINSOS_MEMORY_ROOT", ""),
        agents_dir,
        memories_dir,
        os.path.join(data_dir, "agents") if data_dir else "",
        os.path.join(data_dir, "agent_memories") if data_dir else "",
        "/data/agents",
        "/data/agent_memories",
        "/memories",
        os.path.abspath("./data/agents"),
        os.path.abspath("./data/agent_memories"),
        os.path.abspath("../data/agents"),
        os.path.abspath("../data/agent_memories"),
        os.path.abspath("../../data/agents"),
        os.path.abspath("../../data/agent_memories"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    if os.path.isdir("/data/agents"):
        return "/data/agents"
    if os.path.isdir("/data/agent_memories"):
        return "/data/agent_memories"
    if os.path.isdir("/memories"):
        return "/memories"
    return os.environ.get("BRAINSOS_MEMORY_ROOT") or "/data/agents"


def _get_known_agents(base_root: str) -> list[str]:
    """Discover registered tenant agent directories under base_root."""
    if not os.path.isdir(base_root):
        return []
    agents: list[str] = []
    for entry in os.listdir(base_root):
        if entry.startswith(".") or entry in _OKF_CATEGORIES:
            continue
        p = os.path.join(base_root, entry)
        if os.path.isdir(p) and (
            os.path.isfile(os.path.join(p, "SOUL.md"))
            or os.path.isdir(os.path.join(p, "memories"))
        ):
            agents.append(entry)
    return sorted(agents)


def _detect_active_hermes_agent(base_root: str, known_agents: list[str]) -> str:
    """Detect active tenant agent from Hermes state.db if running inside a shared runner."""
    hermes_home = os.environ.get("HERMES_HOME", "/opt/data")
    db_path = os.path.join(hermes_home, "state.db")
    if not os.path.isfile(db_path):
        return ""
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        cur = con.cursor()
        row = cur.execute(
            "SELECT id FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1"
        ).fetchone()
        con.close()
        if not row or not row[0]:
            return ""
        session_id = str(row[0]).strip().lower()
        if not _MAIL_SESSION_RE.match(session_id):
            return ""
        for agent in sorted(known_agents, key=len, reverse=True):
            clean_agent = agent.strip().lower()
            if clean_agent and session_id.startswith(f"mail-{clean_agent}-"):
                return agent
    except Exception:
        pass
    return ""


def resolve_tenant_memory_target(rel_path: str, agent_id: str = "") -> tuple[str, str]:
    """Resolve (effective_root_dir, effective_rel_path) for tenant-scoped memory operations.

    When BRAINSOS_AGENT_ID (or AGENT_ID / HERMES_AGENT_ID / TENANT_ID) is pinned in
    the environment, strictly rejects cross-tenant path prefixes or agent_id overrides.
    """
    base_root = get_memory_root()
    norm_path = rel_path.strip().replace("\\", "/").lstrip("/")

    # Strip leading 'agents/' and 'memories/' before cross-tenant prefix evaluation
    if norm_path.startswith("agents/"):
        norm_path = norm_path[len("agents/") :].lstrip("/")
    if norm_path.startswith("memories/"):
        norm_path = norm_path[len("memories/") :].lstrip("/")

    if ".." in [seg for seg in norm_path.split("/") if seg]:
        raise PermissionError(f"Path traversal denied in memory path '{rel_path}'.")

    pinned_agent = (
        os.environ.get("BRAINSOS_AGENT_ID")
        or os.environ.get("AGENT_ID")
        or os.environ.get("HERMES_AGENT_ID")
        or os.environ.get("TENANT_ID")
        or ""
    ).strip()

    known_agents = _get_known_agents(base_root)
    explicit_agent = (agent_id or "").strip()

    if pinned_agent and not _SAFE_TENANT_ID_RE.match(pinned_agent):
        raise PermissionError(f"Invalid tenant agent identifier: '{pinned_agent}'.")

    if explicit_agent and not _SAFE_TENANT_ID_RE.match(explicit_agent):
        raise PermissionError(f"Invalid tenant agent identifier: '{explicit_agent}'.")

    if pinned_agent:
        if explicit_agent and explicit_agent != pinned_agent:
            raise PermissionError(
                f"Cross-tenant memory access denied: agent '{pinned_agent}' cannot access '{explicit_agent}'."
            )
        if "/" in norm_path:
            first_seg, rest = norm_path.split("/", 1)
            if first_seg == pinned_agent:
                norm_path = rest.lstrip("/")
            elif first_seg in known_agents or (
                first_seg not in _OKF_CATEGORIES
                and os.path.isdir(os.path.join(base_root, first_seg))
            ):
                raise PermissionError(
                    f"Cross-tenant memory access denied: path '{rel_path}' targets '{first_seg}' instead of '{pinned_agent}'."
                )
        elif norm_path in known_agents and norm_path != pinned_agent:
            raise PermissionError(
                f"Cross-tenant memory access denied: path '{rel_path}' targets '{norm_path}' instead of '{pinned_agent}'."
            )
        target_agent = pinned_agent
    else:
        target_agent = explicit_agent

        # 1. Path-based resolution if path starts with known agent_id
        if not target_agent and "/" in norm_path:
            first_segment, rest = norm_path.split("/", 1)
            if first_segment in known_agents:
                target_agent = first_segment
                norm_path = rest.lstrip("/")
        elif not target_agent and norm_path in known_agents:
            target_agent = norm_path
            norm_path = ""

        # 2. Active Hermes runner session detection (when unpinned)
        if not target_agent and known_agents:
            target_agent = _detect_active_hermes_agent(base_root, known_agents)

        # 3. Single-agent fallback if only one agent is configured in fleet
        if not target_agent and len(known_agents) == 1:
            target_agent = known_agents[0]

        # 4. Default agent fallback from environment if defined
        if not target_agent:
            target_agent = os.environ.get("DEFAULT_AGENT_ID", "").strip()

    if target_agent and not _SAFE_TENANT_ID_RE.match(target_agent):
        raise PermissionError(f"Invalid tenant agent identifier: '{target_agent}'.")

    # Strip redundant 'memories/' prefix after agent prefix stripping (e.g. agents/<agent>/memories/...)
    if norm_path.startswith("memories/"):
        norm_path = norm_path[len("memories/") :].lstrip("/")

    # If target_agent is resolved:
    if target_agent:
        # Ephemeral single-tenant mount (e.g. /data/agents/<tenant>/memories:/memories:rw)
        if os.path.basename(os.path.normpath(base_root)) == "memories" and not known_agents:
            target_dir = os.path.realpath(base_root)
            os.makedirs(target_dir, exist_ok=True)
            return target_dir, norm_path

        real_base = os.path.realpath(base_root)
        raw_agent_dir = os.path.join(real_base, target_agent)
        if os.path.islink(raw_agent_dir):
            raise PermissionError(f"Symlinked tenant agent directory rejected: '{target_agent}'.")

        agent_dir = os.path.realpath(raw_agent_dir)
        if os.path.commonpath([real_base, agent_dir]) != real_base or agent_dir == real_base:
            raise PermissionError(f"Invalid tenant agent directory traversal: '{target_agent}'")

        raw_target_dir = os.path.join(agent_dir, "memories")
        if os.path.islink(raw_target_dir):
            raise PermissionError(f"Symlinked tenant memories directory rejected: '{target_agent}'.")

        target_dir = os.path.realpath(raw_target_dir)
        if os.path.commonpath([agent_dir, target_dir]) != agent_dir or target_dir == agent_dir:
            raise PermissionError(f"Invalid tenant memories directory traversal: '{target_agent}'")

        os.makedirs(target_dir, exist_ok=True)
        return target_dir, norm_path

    # Guard: If base_root is a multi-tenant root with known agents, reject unscoped operations
    if known_agents or os.path.basename(os.path.normpath(base_root)) == "agents":
        agent_list = ", ".join(known_agents) if known_agents else "none"
        raise ValueError(
            f"Cannot resolve target tenant agent for memory path '{rel_path}'. "
            f"Specify 'agent_id' or prefix path with an agent identifier (known agents: {agent_list})."
        )

    return base_root, norm_path


def register_memory_tools(mcp: FastMCP) -> list[str]:
    """Register memory plane tools onto the FastMCP server."""
    from brainsos_memory.okf.engine import OKFEngine

    @mcp.tool()
    def read_memory(rel_path: str) -> str:
        """Read OKF note from your agent memory partition (e.g. 'research/topic.md', 'rules/custom.md')."""
        try:
            root_dir, clean_path = resolve_tenant_memory_target(rel_path)
            engine = OKFEngine(root_dir=root_dir)
            note = engine.read_note(clean_path)
            return json.dumps(
                {
                    "success": True,
                    "rel_path": clean_path,
                    "title": note.title,
                    "body": note.body,
                    "metadata": note.metadata,
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def write_memory(rel_path: str, content: str, title: str = "") -> str:
        """Write OKF note to your agent memory partition (e.g. 'research/topic.md', 'rules/custom.md')."""
        try:
            root_dir, clean_path = resolve_tenant_memory_target(rel_path)
            engine = OKFEngine(root_dir=root_dir)
            note = engine.write_note(rel_path=clean_path, content=content, title=title)
            return json.dumps(
                {
                    "success": True,
                    "rel_path": clean_path,
                    "title": note.title,
                    "size_bytes": len(note.serialize()),
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return ["read_memory", "write_memory"]
