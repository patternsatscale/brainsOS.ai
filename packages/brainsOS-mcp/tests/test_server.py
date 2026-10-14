"""Integration tests for brainsos_mcp server, tool listing, schemas, and execution."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import tiktoken
from brainsos_mcp.server import create_server


@pytest.fixture
def mcp_server(tmp_path, monkeypatch):
    """Fixture providing a fresh configured MCP server with isolated memory root."""
    monkeypatch.setenv("BRAINSOS_MEMORY_ROOT", str(tmp_path / "memories"))
    (tmp_path / "memories" / "knowledge").mkdir(parents=True)
    return create_server()


def test_tool_listing_and_token_budget(mcp_server):
    """Verify tool listing returns standard capabilities under 800 tokens."""
    tools = mcp_server._tool_manager.list_tools()
    tool_names = {t.name for t in tools}

    expected_tools = {
        "read_memory",
        "write_memory",
        "enqueue_task",
        "get_task_status",
        "send_email",
        "read_email",
        "get_energy_metrics",
        "emit_telemetry_event",
    }
    assert expected_tools.issubset(tool_names)

    schemas = [{"name": t.name, "description": t.description, "inputSchema": t.parameters} for t in tools]
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = len(enc.encode(json.dumps(schemas)))

    assert tokens < 800, f"Tool schemas exceeded 800 tokens: {tokens}"


@pytest.mark.asyncio
async def test_memory_tool_execution(mcp_server):
    """Verify write_memory and read_memory tools succeed via call_tool."""
    write_res = await mcp_server.call_tool(
        "write_memory",
        {
            "rel_path": "knowledge/mcp_test.md",
            "content": "# MCP Test Note\nVerified via MCP tools/call.",
            "title": "MCP Test Note",
        },
    )
    assert write_res is not None
    write_data = json.loads(write_res[0][0].text)
    assert write_data["success"] is True

    read_res = await mcp_server.call_tool(
        "read_memory",
        {"rel_path": "knowledge/mcp_test.md"},
    )
    assert read_res is not None
    read_data = json.loads(read_res[0][0].text)
    assert read_data["success"] is True
    assert "MCP Test Note" in read_data["body"]


@pytest.mark.asyncio
async def test_queue_tool_execution(mcp_server):
    """Verify enqueue_task and get_task_status tools succeed via call_tool."""
    enq_res = await mcp_server.call_tool(
        "enqueue_task",
        {
            "task_type": "mcp_sample_task",
            "payload_json": json.dumps({"action": "test", "value": 42}),
        },
    )
    assert enq_res is not None
    enq_data = json.loads(enq_res[0][0].text)
    assert enq_data["success"] is True
    task_id = enq_data["task_id"]

    status_res = await mcp_server.call_tool(
        "get_task_status",
        {"task_id": task_id},
    )
    assert status_res is not None
    status_data = json.loads(status_res[0][0].text)
    assert status_data["success"] is True
    assert status_data["task_id"] == task_id
    assert status_data["status"] == "queued"


@pytest.mark.asyncio
async def test_telemetry_tool_execution(mcp_server):
    """Verify emit_telemetry_event and get_energy_metrics succeed via call_tool."""
    emit_res = await mcp_server.call_tool(
        "emit_telemetry_event",
        {"event_type": "mcp_task_completed", "task_id": "task-mcp-1"},
    )
    assert emit_res is not None
    emit_data = json.loads(emit_res[0][0].text)
    assert emit_data["success"] is True
    assert emit_data["event_type"] == "mcp_task_completed"

    # Energy calculation: 100ms * 25.0 + 50 tokens * 80.0 = 2500 + 4000 = 6500 mJ
    energy_res = await mcp_server.call_tool(
        "get_energy_metrics",
        {"duration_ms": 100.0, "tokens": 50},
    )
    assert energy_res is not None
    energy_data = json.loads(energy_res[0][0].text)
    assert energy_data["success"] is True
    assert energy_data["energy_millijoules"] == 6500.0


@pytest.mark.asyncio
async def test_mail_tool_execution(mcp_server):
    """Verify send_email and read_email succeed via call_tool with mocked client."""
    mock_client = MagicMock()
    mock_client.send_mail.return_value = "<mcp-msg-123@brainsos.local>"
    mock_client.read_message.return_value = {
        "message_id": "<mcp-msg-123@brainsos.local>",
        "subject": "MCP Notification",
        "body": "Test email body",
    }

    with patch("brainsos_mail.client.BrainsOSMailClient", return_value=mock_client):
        send_res = await mcp_server.call_tool(
            "send_email",
            {
                "to": "operator@brainsos.local",
                "subject": "MCP Notification",
                "body": "Hello via MCP!",
            },
        )
        assert send_res is not None
        send_data = json.loads(send_res[0][0].text)
        assert send_data["success"] is True
        assert send_data["message_id"] == "<mcp-msg-123@brainsos.local>"

        read_res = await mcp_server.call_tool(
            "read_email",
            {"query_or_id": "<mcp-msg-123@brainsos.local>"},
        )
        assert read_res is not None
        read_data = json.loads(read_res[0][0].text)
        assert read_data["success"] is True
        assert read_data["message"]["subject"] == "MCP Notification"


@pytest.mark.asyncio
async def test_tenant_scoped_memory_execution(tmp_path, monkeypatch):
    """Verify write_memory and read_memory route to agent-centric partitions (agents/<id>/memories/)."""
    agents_dir = tmp_path / "agents"
    bawtford_mem = agents_dir / "bawtford" / "memories"
    bawtford_mem.mkdir(parents=True)

    monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents_dir))
    monkeypatch.delenv("BRAINSOS_MEMORY_ROOT", raising=False)
    monkeypatch.delenv("BRAINSOS_MEMORIES_DIR", raising=False)

    server = create_server()

    # 1. Transparent memory write without agent_id parameter
    write_res = await server.call_tool(
        "write_memory",
        {
            "rel_path": "notes/ideas.md",
            "content": "# Ideas\nAgent scoped idea.",
        },
    )
    assert write_res is not None
    write_data = json.loads(write_res[0][0].text)
    assert write_data["success"] is True
    target_file = bawtford_mem / "notes" / "ideas.md"
    assert target_file.exists()

    read_res = await server.call_tool(
        "read_memory",
        {
            "rel_path": "notes/ideas.md",
        },
    )
    assert read_res is not None
    read_data = json.loads(read_res[0][0].text)
    assert read_data["success"] is True
    assert "Agent scoped idea." in read_data["body"]

    # 2. Prefixed rel_path (e.g. bawtford/rules/rule1.md) without agent_id
    write_res2 = await server.call_tool(
        "write_memory",
        {
            "rel_path": "bawtford/rules/rule1.md",
            "content": "# Rule 1\nAlways check tenant isolation.",
        },
    )
    assert write_res2 is not None
    write_data2 = json.loads(write_res2[0][0].text)
    assert write_data2["success"] is True
    target_rule = bawtford_mem / "rules" / "rule1.md"
    assert target_rule.exists()

    # 3. Leading agents/ and memories/ prefixes (e.g. agents/bawtford/memories/research/thesis.md)
    write_res3 = await server.call_tool(
        "write_memory",
        {
            "rel_path": "agents/bawtford/memories/research/thesis.md",
            "content": "# Thesis\nPrimary care data quality.",
        },
    )
    assert write_res3 is not None
    write_data3 = json.loads(write_res3[0][0].text)
    assert write_data3["success"] is True
    target_thesis = bawtford_mem / "research" / "thesis.md"
    assert target_thesis.exists()

    # 4. Hermes state.db active session detection for unscoped rel_path
    # Create another tenant 'terrastella' so base_root is unambiguously multi-tenant
    terrastella_mem = agents_dir / "terrastella" / "memories"
    terrastella_mem.mkdir(parents=True)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    import sqlite3

    db_path = hermes_home / "state.db"
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, last_activity_at REAL, started_at REAL)")
    cur.execute("INSERT INTO sessions VALUES ('mail-bawtford-thread-999', 1000.0, 900.0)")
    con.commit()
    con.close()

    # Unscoped path without agent_id (e.g. research/notes.md) should auto-detect bawtford from state.db
    write_res4 = await server.call_tool(
        "write_memory",
        {
            "rel_path": "research/notes.md",
            "content": "# Research\nInferred bawtford from runner session.",
        },
    )
    assert write_res4 is not None
    write_data4 = json.loads(write_res4[0][0].text)
    assert write_data4["success"] is True
    target_inferred = bawtford_mem / "research" / "notes.md"
    assert target_inferred.exists()

    # Verify no files or category directories were written directly to agents_dir
    assert not (agents_dir / "research").exists()
    assert not (agents_dir / "rules").exists()
    assert not (agents_dir / "knowledge").exists()

    # 5. Guard check: when no agent can be inferred, reject unscoped write
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "nonexistent"))
    write_res5 = await server.call_tool(
        "write_memory",
        {
            "rel_path": "research/mystery.md",
            "content": "# Mystery",
        },
    )
    assert write_res5 is not None
    write_data5 = json.loads(write_res5[0][0].text)
    assert write_data5["success"] is False
    assert "Cannot resolve target tenant agent" in write_data5["error"]

