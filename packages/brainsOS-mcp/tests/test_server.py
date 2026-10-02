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
