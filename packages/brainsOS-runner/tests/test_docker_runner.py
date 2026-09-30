"""Unit tests for EphemeralDockerRunnerClient."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from brainsos_runner.clients.docker import EphemeralDockerRunnerClient
from brainsos_runner.models import (
    AgentTurnRequest,
    AgentTurnResponse,
    ChatMessage,
)
from brainsos_runner.registry import RunnerRegistry


@pytest.fixture
def sample_request(tmp_path: Path) -> AgentTurnRequest:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return AgentTurnRequest(
        run_id="run-docker-01",
        agent_id="openhands",
        model="claude-3-7-sonnet",
        system_prompt="You are OpenHands.",
        conversation=[
            ChatMessage(role="user", content="ls files"),
        ],
        workspace_dir=str(ws),
        timeout_sec=10,
    )


def test_security_violation_docker_sock(tmp_path: Path):
    client = EphemeralDockerRunnerClient(image="test-image:latest")
    req = AgentTurnRequest(
        run_id="run-bad-01",
        agent_id="bad",
        model="m",
        system_prompt="s",
        conversation=[],
        workspace_dir="/var/run/docker.sock",
    )
    # The client execute_turn should return failed with error message
    resp = asyncio.run(client.execute_turn(req))
    assert resp.status == "failed"
    assert "Docker socket cannot be mounted" in (resp.error_message or "")


def test_security_violation_memories(tmp_path: Path):
    client = EphemeralDockerRunnerClient(image="test-image:latest")
    req = AgentTurnRequest(
        run_id="run-bad-02",
        agent_id="bad",
        model="m",
        system_prompt="s",
        conversation=[],
        workspace_dir=str(tmp_path / "data" / "agent_memories" / "bad"),
    )
    resp = asyncio.run(client.execute_turn(req))
    assert resp.status == "failed"
    assert "Agent /memories cannot be mounted" in (resp.error_message or "")


@pytest.mark.asyncio
async def test_successful_turn_structured_json(sample_request: AgentTurnRequest):
    client = EphemeralDockerRunnerClient(
        image="test-image:latest",
        memory_limit="1g",
        cpu_limit="1.0",
    )

    mock_resp = AgentTurnResponse(
        run_id=sample_request.run_id,
        status="completed",
        output_text="Files listed successfully.",
    )

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (
        mock_resp.model_dump_json().encode("utf-8"),
        b"",
    )

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc

        response = await client.execute_turn(sample_request)

        assert response.run_id == sample_request.run_id
        assert response.status == "completed"
        assert response.output_text == "Files listed successfully."

        # Verify command arguments passed to docker
        mock_exec.assert_called()
        call_args = mock_exec.call_args[0]
        cmd_str = " ".join(call_args)

        assert "docker run --rm -i" in cmd_str
        assert "--memory=1g" in cmd_str
        assert "--cpus=1.0" in cmd_str
        assert "--security-opt no-new-privileges:true" in cmd_str
        assert "-v " in cmd_str
        assert ":/workspace:rw" in cmd_str
        assert "docker.sock" not in cmd_str
        assert "/memories" not in cmd_str


@pytest.mark.asyncio
async def test_successful_turn_plaintext_fallback(sample_request: AgentTurnRequest):
    client = EphemeralDockerRunnerClient(image="test-image:latest")

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"file1.txt\nfile2.txt", b"")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        response = await client.execute_turn(sample_request)

        assert response.status == "completed"
        assert "file1.txt" in response.output_text


@pytest.mark.asyncio
async def test_container_failure(sample_request: AgentTurnRequest):
    client = EphemeralDockerRunnerClient(image="test-image:latest")

    mock_proc = AsyncMock()
    mock_proc.returncode = 137
    mock_proc.communicate.return_value = (b"", b"OOMKilled")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        response = await client.execute_turn(sample_request)

        assert response.status == "failed"
        assert "OOMKilled" in (response.error_message or "")


@pytest.mark.asyncio
async def test_container_timeout_and_kill(sample_request: AgentTurnRequest):
    client = EphemeralDockerRunnerClient(image="test-image:latest")

    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        response = await client.execute_turn(sample_request)

        assert response.status == "timed_out"
        assert "timed out" in (response.error_message or "").lower()

        # Check that docker kill and rm were called
        kill_or_rm_calls = [
            call[0] for call in mock_exec.call_args_list if "kill" in call[0] or "rm" in call[0]
        ]
        assert len(kill_or_rm_calls) >= 1


def test_registry_get_ephemeral_docker_runner():
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    registry = RunnerRegistry.load_from_yaml(repo_root / "config" / "runners.yaml")
    client = registry.get_runner("openhands-sandbox")
    assert isinstance(client, EphemeralDockerRunnerClient)
    assert client.image == "brainsos-openhands-sandbox:latest"
    assert client.memory_limit == "2g"
    assert client.cpu_limit == "2.0"
