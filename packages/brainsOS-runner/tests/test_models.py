"""Unit tests for brainsos_runner.models."""

import pytest
from brainsos_runner.models import (
    AgentTurnRequest,
    AgentTurnResponse,
    ChatMessage,
    ExecutionMetrics,
    McpServerConfig,
    MemoryDelta,
    ToolCallRecord,
)
from pydantic import ValidationError


def test_chat_message_valid():
    msg = ChatMessage(role="user", content="Hello, assistant!", author="user@example.com")
    assert msg.role == "user"
    assert msg.content == "Hello, assistant!"
    assert msg.author == "user@example.com"
    assert msg.tool_call_id is None

    # Test serialization roundtrip
    json_data = msg.model_dump_json()
    restored = ChatMessage.model_validate_json(json_data)
    assert restored == msg


def test_chat_message_invalid_role():
    with pytest.raises(ValidationError):
        ChatMessage(role="moderator", content="Invalid role")  # type: ignore[arg-type]


def test_mcp_server_config():
    config = McpServerConfig(name="filesystem", url="http://localhost:8000/sse", transport="sse")
    assert config.transport == "sse"

    # stdio transport
    config_stdio = McpServerConfig(name="cli", url="http://localhost:8001", transport="stdio")
    assert config_stdio.transport == "stdio"

    with pytest.raises(ValidationError):
        McpServerConfig(name="invalid", url="http://localhost", transport="grpc")  # type: ignore[arg-type]


def test_tool_call_record():
    record = ToolCallRecord(
        id="call_123",
        tool_name="bash_exec",
        arguments={"cmd": "ls -la"},
        output="total 0",
        exit_code=0,
    )
    assert record.id == "call_123"
    assert record.arguments == {"cmd": "ls -la"}
    assert record.exit_code == 0

    json_str = record.model_dump_json()
    assert ToolCallRecord.model_validate_json(json_str) == record


def test_memory_delta():
    delta = MemoryDelta(action="set", key="preferences.theme", value="dark")
    assert delta.action == "set"
    assert delta.value == "dark"

    delta_delete = MemoryDelta(action="delete", key="temp_cache")
    assert delta_delete.action == "delete"
    assert delta_delete.value is None

    with pytest.raises(ValidationError):
        MemoryDelta(action="replace", key="k", value="v")  # type: ignore[arg-type]


def test_execution_metrics():
    metrics = ExecutionMetrics(prompt_tokens=100, completion_tokens=50, duration_ms=1250)
    assert metrics.prompt_tokens == 100
    assert metrics.completion_tokens == 50
    assert metrics.duration_ms == 1250

    with pytest.raises(ValidationError):
        ExecutionMetrics(prompt_tokens=-1)

    with pytest.raises(ValidationError):
        ExecutionMetrics(duration_ms=-10)


def test_agent_turn_request_valid():
    req = AgentTurnRequest(
        run_id="run-001",
        agent_id="cindy",
        model="gpt-4o",
        system_prompt="You are Cindy.",
        conversation=[
            ChatMessage(role="user", content="Show status"),
        ],
        mcp_servers=[
            McpServerConfig(name="local", url="http://127.0.0.1:8999/sse"),
        ],
        workspace_dir="/data/workspaces/cindy",
        timeout_sec=60,
        extra_params={"temperature": 0.2},
    )
    assert req.run_id == "run-001"
    assert req.timeout_sec == 60
    assert len(req.conversation) == 1
    assert req.conversation[0].content == "Show status"
    assert len(req.mcp_servers) == 1

    # Roundtrip JSON
    data = req.model_dump_json()
    req_restored = AgentTurnRequest.model_validate_json(data)
    assert req_restored == req


def test_agent_turn_request_invalid_timeout():
    with pytest.raises(ValidationError):
        AgentTurnRequest(
            run_id="run-001",
            agent_id="cindy",
            model="gpt-4o",
            system_prompt="You are Cindy.",
            conversation=[],
            workspace_dir="/tmp",
            timeout_sec=0,
        )

    with pytest.raises(ValidationError):
        AgentTurnRequest(
            run_id="run-001",
            agent_id="cindy",
            model="gpt-4o",
            system_prompt="You are Cindy.",
            conversation=[],
            workspace_dir="/tmp",
            timeout_sec=-5,
        )


def test_agent_turn_request_missing_required_fields():
    with pytest.raises(ValidationError):
        AgentTurnRequest(
            run_id="run-001",
            # missing agent_id, model, system_prompt, conversation, workspace_dir
        )  # type: ignore[call-arg]


def test_agent_turn_response_completed():
    resp = AgentTurnResponse(
        run_id="run-001",
        status="completed",
        output_text="All systems nominal.",
        tool_calls=[
            ToolCallRecord(
                id="call-1",
                tool_name="status_check",
                arguments={},
                output="OK",
            )
        ],
        memory_deltas=[
            MemoryDelta(action="append", key="logs", value="checked status")
        ],
        metrics=ExecutionMetrics(prompt_tokens=40, completion_tokens=10, duration_ms=200),
    )
    assert resp.status == "completed"
    assert resp.error_message is None
    assert len(resp.tool_calls) == 1
    assert len(resp.memory_deltas) == 1
    assert resp.metrics.prompt_tokens == 40

    json_str = resp.model_dump_json()
    assert AgentTurnResponse.model_validate_json(json_str) == resp


def test_agent_turn_response_failed():
    resp = AgentTurnResponse(
        run_id="run-002",
        status="failed",
        output_text="",
        error_message="Process terminated with SIGSEGV",
    )
    assert resp.status == "failed"
    assert resp.error_message == "Process terminated with SIGSEGV"
    assert resp.tool_calls == []
    assert resp.memory_deltas == []


def test_agent_turn_response_timed_out():
    resp = AgentTurnResponse(
        run_id="run-003",
        status="timed_out",
        output_text="",
        error_message="Turn exceeded timeout of 120s",
    )
    assert resp.status == "timed_out"


def test_agent_turn_response_invalid_status():
    with pytest.raises(ValidationError):
        AgentTurnResponse(
            run_id="run-004",
            status="aborted",  # type: ignore[arg-type]
            output_text="",
        )
