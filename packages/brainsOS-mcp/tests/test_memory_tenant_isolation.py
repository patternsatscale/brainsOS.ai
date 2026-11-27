"""Unit tests for tenant memory isolation and anchored Hermes session detection (M3 F14)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from brainsos_mcp.modules.memory import _detect_active_hermes_agent, resolve_tenant_memory_target


def _seed_session_db(db_path: Path, session_id: str) -> None:
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT, started_at INTEGER, last_activity_at INTEGER)")
    con.execute("DELETE FROM sessions")
    con.execute("INSERT INTO sessions VALUES (?, 100, 100)", (session_id,))
    con.commit()
    con.close()


def test_detect_active_hermes_agent_anchored_to_mail_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    db_path = tmp_path / "state.db"

    _seed_session_db(db_path, "chat-other-alice-thread-1")
    assert _detect_active_hermes_agent(str(tmp_path), ["alice"]) == ""

    _seed_session_db(db_path, "mail-bob-ping-thread-1")
    assert _detect_active_hermes_agent(str(tmp_path), ["ping", "bob"]) == "bob"

    _seed_session_db(db_path, "mail-alice-bot-thread-1")
    assert _detect_active_hermes_agent(str(tmp_path), ["alice", "alice-bot"]) == "alice-bot"

    _seed_session_db(db_path, "mail-unknown-alice-1")
    assert _detect_active_hermes_agent(str(tmp_path), ["alice"]) == ""


def test_resolve_tenant_memory_target_blocks_memories_prefix_and_avoids_doubling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = tmp_path / "agents"
    (agents / "alice" / "memories").mkdir(parents=True)
    (agents / "bob" / "memories").mkdir(parents=True)
    monkeypatch.setenv("BRAINSOS_MEMORY_ROOT", str(agents))
    monkeypatch.setenv("BRAINSOS_AGENT_ID", "alice")

    with pytest.raises(PermissionError):
        resolve_tenant_memory_target("memories/bob/secret.md")

    with pytest.raises(PermissionError):
        resolve_tenant_memory_target("agents/bob/memories/secret.md")

    with pytest.raises(PermissionError):
        resolve_tenant_memory_target("research/../../bob/secret.md")

    root_dir, rel = resolve_tenant_memory_target("memories/research/ok.md")
    assert Path(root_dir) == (agents / "alice" / "memories").resolve()
    assert rel == "research/ok.md"

    # Single-tenant /memories mount must not double to /memories/alice/memories
    single_mem = tmp_path / "memories"
    single_mem.mkdir()
    monkeypatch.setenv("BRAINSOS_MEMORY_ROOT", str(single_mem))
    root_single, rel_single = resolve_tenant_memory_target("threads/t1.md")
    assert Path(root_single) == single_mem.resolve()
    assert rel_single == "threads/t1.md"


def test_resolve_tenant_memory_target_rejects_symlinks_and_invalid_agent_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = tmp_path / "agents"
    (agents / "alice" / "memories").mkdir(parents=True)
    (agents / "bob" / "memories").mkdir(parents=True)
    (agents / "bob" / "memories" / "secret.md").write_text("TOPSECRET\n", encoding="utf-8")

    # Symlinked tenant root: charlie -> bob
    (agents / "charlie").symlink_to(agents / "bob")

    # Symlinked memories dir: dave/memories -> bob/memories and erin/memories -> outside
    (agents / "dave").mkdir(parents=True)
    (agents / "dave" / "memories").symlink_to(agents / "bob" / "memories")
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    (agents / "erin").mkdir(parents=True)
    (agents / "erin" / "memories").symlink_to(outside)

    monkeypatch.setenv("BRAINSOS_MEMORY_ROOT", str(agents))
    monkeypatch.delenv("BRAINSOS_AGENT_ID", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("HERMES_AGENT_ID", raising=False)
    monkeypatch.delenv("TENANT_ID", raising=False)

    for bad_tenant in ("charlie", "dave", "erin"):
        with pytest.raises(PermissionError):
            resolve_tenant_memory_target("secret.md", agent_id=bad_tenant)
        with pytest.raises(PermissionError):
            resolve_tenant_memory_target(f"{bad_tenant}/secret.md")
        monkeypatch.setenv("BRAINSOS_AGENT_ID", bad_tenant)
        with pytest.raises(PermissionError):
            resolve_tenant_memory_target("secret.md")
        monkeypatch.delenv("BRAINSOS_AGENT_ID", raising=False)

    for invalid_id in (".", "..", "alice/sub", "alice\\sub", "alice/../../bob", ".hidden", "-alice"):
        with pytest.raises(PermissionError):
            resolve_tenant_memory_target("knowledge/note.md", agent_id=invalid_id)
        monkeypatch.setenv("BRAINSOS_AGENT_ID", invalid_id)
        with pytest.raises(PermissionError):
            resolve_tenant_memory_target("knowledge/note.md")
        monkeypatch.delenv("BRAINSOS_AGENT_ID", raising=False)

    root_dir, rel = resolve_tenant_memory_target("knowledge/note.md", agent_id="alice")
    assert Path(root_dir) == (agents / "alice" / "memories").resolve()
    assert rel == "knowledge/note.md"

