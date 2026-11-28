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
def sample_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentTurnRequest:
    monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
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

        assert client.network == "brainsos-sandbox-net"
        assert "docker run --rm -i" in cmd_str
        assert "--network brainsos-sandbox-net" in cmd_str
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
        kill_or_rm_calls = [call[0] for call in mock_exec.call_args_list if "kill" in call[0] or "rm" in call[0]]
        assert len(kill_or_rm_calls) >= 1


def test_registry_get_ephemeral_docker_runner():
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    registry = RunnerRegistry.load_from_yaml(repo_root / "config" / "runners.yaml")
    client = registry.get_runner("openhands-sandbox")
    assert isinstance(client, EphemeralDockerRunnerClient)
    assert client.image == "brainsos-openhands-sandbox:latest"
    assert client.memory_limit == "2g"
    assert client.cpu_limit == "2.0"


@pytest.mark.asyncio
async def test_per_tenant_hardened_flags_containment_and_env_scoping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    agents_dir = tmp_path / "agents"
    alice_ws = agents_dir / "alice" / "workspace"
    alice_mem = agents_dir / "alice" / "memories"
    bob_ws = agents_dir / "bob" / "workspace"
    evil_ws = agents_dir / "alice-evil" / "workspace"
    for p in (alice_ws, alice_mem, bob_ws, evil_ws):
        p.mkdir(parents=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    link_ws = agents_dir / "charlie" / "workspace"
    link_ws.parent.mkdir(parents=True)
    link_ws.symlink_to(outside)

    monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents_dir))
    monkeypatch.setenv("ALICE_LITELLM_KEY", "sk-alice-only")
    monkeypatch.setenv("BOB_LITELLM_KEY", "sk-bob-forbidden")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-forbidden")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-forbidden")
    monkeypatch.setenv("HERMES_LANGFUSE_SECRET_KEY", "sk-hlf-forbidden")
    monkeypatch.setenv("TOOL_EGRESS_PROXY_TOKENS", "alice:tok-alice-only,bob:tok-bob-secret")
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "org/alice-repo")

    client = EphemeralDockerRunnerClient(image="brainsos-runner-hermes:latest", command=["python3", "/app/server.py"])

    # Containment rejections
    with pytest.raises(ValueError):
        client._validate_workspace(str(alice_ws))  # missing tenant_id when BRAINSOS_AGENTS_DIR set
    with pytest.raises(ValueError):
        client._validate_workspace(str(evil_ws), "alice")
    with pytest.raises(ValueError):
        client._validate_workspace(str(bob_ws), "alice")
    with pytest.raises(ValueError):
        client._validate_workspace(str(link_ws), "charlie")

    req = AgentTurnRequest(
        run_id="run-alice-01",
        agent_id="alice",
        model="brainsos-core",
        system_prompt="hi",
        conversation=[ChatMessage(role="user", content="hello")],
        workspace_dir=str(alice_ws),
    )
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (
        AgentTurnResponse(run_id="run-alice-01", status="completed", output_text="ok").model_dump_json().encode(),
        b"",
    )
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc
        resp = await client.execute_turn(req)

    assert resp.status == "completed"
    cmd = list(mock_exec.call_args[0])
    cmd_str = " ".join(cmd)
    for expected in (
        "--rm",
        "--cap-drop=ALL",
        "--security-opt no-new-privileges:true",
        "--pids-limit=256",
        "--user=10001:10001",
        "--read-only",
        "/tmp:rw,noexec,nosuid,size=128m",
        "brainsos.tenant=alice",
        f"{alice_ws.resolve()}:/workspace:rw",
        f"{alice_mem.resolve()}:/memories:rw",
        "BRAINSOS_AGENT_ID=alice",
        "LITELLM_API_KEY=sk-alice-only",
        "BRAINSOS_TELEMETRY_BACKEND=lens",
        "LENS_ENABLED=true",
        "LANGFUSE_ENABLED=false",
        "TOOL_EGRESS_PROXY_TOKEN=tok-alice-only",
        "GITHUB_ALLOWED_REPOS=org/alice-repo",
    ):
        assert expected in cmd_str

    for forbidden in ("sk-bob-forbidden", "sk-master-forbidden", "sk-lf-forbidden", "sk-hlf-forbidden", "tok-bob-secret"):
        assert forbidden not in cmd_str


@pytest.mark.asyncio
async def test_brainsos_data_dir_fallback_enforces_tenant_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    alice_ws = data_dir / "agents" / "alice" / "workspace"
    alice_mem = data_dir / "agents" / "alice" / "memories"
    bob_ws = data_dir / "agents" / "bob" / "workspace"
    bob_mem = data_dir / "agents" / "bob" / "memories"
    for p in (alice_ws, alice_mem, bob_ws, bob_mem):
        p.mkdir(parents=True)

    monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
    monkeypatch.setenv("BRAINSOS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("BRAINSOS_AGENT_ID", raising=False)

    client = EphemeralDockerRunnerClient(image="test-image:latest")

    with pytest.raises(ValueError):
        client._validate_workspace(str(alice_ws))
    with pytest.raises(ValueError):
        client._validate_workspace(str(bob_ws), "alice")
    with pytest.raises(ValueError):
        client._validate_memories(str(bob_mem), "alice")

    assert client._validate_workspace(str(alice_ws), "alice") == alice_ws.resolve()
    assert client._validate_memories(str(alice_mem), "alice") == alice_mem.resolve()


def test_unconfigured_mode_blocks_cross_tenant_agents_paths_and_trailing_slash_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_AGENT_ID", raising=False)

    agents = tmp_path / "agents"
    bob_ws = agents / "bob" / "workspace"
    bob_mem = agents / "bob" / "memories"
    bob_ws.mkdir(parents=True)
    bob_mem.mkdir(parents=True)

    dave_ws = agents / "dave" / "workspace"
    dave_ws.parent.mkdir(parents=True)
    dave_ws.symlink_to(bob_ws)

    link_ws = tmp_path / "link_ws"
    link_ws.symlink_to(bob_ws)

    client = EphemeralDockerRunnerClient(image="test-image:latest")

    with pytest.raises(ValueError):
        client._validate_workspace(str(bob_ws), "alice")
    with pytest.raises(ValueError):
        client._validate_memories(str(bob_mem), "alice")
    with pytest.raises(ValueError):
        client._validate_workspace(f"{link_ws}/", "alice")
    with pytest.raises(ValueError):
        client._validate_workspace(f"{dave_ws}/sub", "dave")


def test_component_wise_symlink_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    agents = data_dir / "agents"
    (agents / "bob" / "workspace").mkdir(parents=True)
    (agents / "bob" / "memories").mkdir(parents=True)
    (agents / "charlie" / "workspace").mkdir(parents=True)
    (agents / "charlie" / "memories").symlink_to(agents / "bob" / "memories")
    (agents / "dave" / "workspace").mkdir(parents=True)
    (agents / "dave" / "memories").symlink_to(agents / "bob" / "memories")
    (agents / "erin").symlink_to(agents / "bob")

    client = EphemeralDockerRunnerClient(image="test-image:latest")

    for env_mode in ("agents_dir", "data_dir"):
        if env_mode == "agents_dir":
            monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents))
            monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
        else:
            monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
            monkeypatch.setenv("BRAINSOS_DATA_DIR", str(data_dir))

        with pytest.raises(ValueError):
            client._validate_memories(f"{agents}/charlie/memories/", "charlie")
        with pytest.raises(ValueError):
            client._validate_memories(f"{agents}/dave/memories/sub", "dave")
        with pytest.raises(ValueError):
            client._validate_workspace(f"{agents}/erin/workspace", "erin")
        with pytest.raises(ValueError):
            client._validate_memories(f"{agents}/erin/memories", "erin")
        with pytest.raises(ValueError):
            client._validate_memories(None, "erin")


@pytest.mark.asyncio
async def test_virtual_key_env_positive_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "agents.yaml").write_text(
        "agents:\n  - id: alice\n    routing:\n      virtual_key: ALICE_CUSTOM_LITELLM_KEY\n",
        encoding="utf-8",
    )

    ws = tmp_path / "ws"
    ws.mkdir()

    monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)
    monkeypatch.setenv("BRAINSOS_SETTINGS_DIR", str(settings_dir))
    monkeypatch.setenv("ALICE_LITELLM_KEY", "sk-alice-default")
    monkeypatch.setenv("ALICE_CUSTOM_LITELLM_KEY", "sk-alice-custom")
    monkeypatch.setenv("BOB_LITELLM_KEY", "sk-bob-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret-forbidden")

    client = EphemeralDockerRunnerClient(image="test-image:latest")

    async def _run_with_extra(extra: dict[str, object]) -> list[str]:
        req = AgentTurnRequest(
            run_id="run-vkey-01",
            agent_id="alice",
            model="m",
            system_prompt="s",
            conversation=[ChatMessage(role="user", content="hi")],
            workspace_dir=str(ws),
            extra_params=dict(extra),
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            AgentTurnResponse(run_id="run-vkey-01", status="completed", output_text="ok").model_dump_json().encode(),
            b"",
        )
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            await client.execute_turn(req)
            return list(mock_exec.call_args[0])

    cmd_bob = " ".join(await _run_with_extra({"virtual_key_env": "BOB_LITELLM_KEY"}))
    assert "sk-bob-secret" not in cmd_bob
    assert "LITELLM_API_KEY=sk-alice-custom" in cmd_bob

    cmd_aws = " ".join(await _run_with_extra({"virtual_key_env": "AWS_SECRET_ACCESS_KEY"}))
    assert "aws-secret-forbidden" not in cmd_aws
    assert "LITELLM_API_KEY=sk-alice-custom" in cmd_aws


@pytest.mark.asyncio
async def test_run_id_validation_proxy_url_encoding_and_nonzero_cli_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.delenv("BRAINSOS_AGENTS_DIR", raising=False)
    monkeypatch.delenv("BRAINSOS_DATA_DIR", raising=False)

    client = EphemeralDockerRunnerClient(image="test-image:latest")

    bad_req = AgentTurnRequest(
        run_id="../escape;id",
        agent_id="alice",
        model="m",
        system_prompt="s",
        conversation=[],
        workspace_dir=str(ws),
    )
    bad_resp = await client.execute_turn(bad_req)
    assert bad_resp.status == "failed"
    assert "invalid run_id" in (bad_resp.error_message or "")

    # URL encoding of proxy_token and non-zero exit CLI JSON parsing + completed coercion
    req = AgentTurnRequest(
        run_id="run-encode-01",
        agent_id="alice",
        model="m",
        system_prompt="s",
        conversation=[ChatMessage(role="user", content="hi")],
        workspace_dir=str(ws),
        extra_params={"egress_proxy_token": "tok+a/b:c@d"},
    )

    mock_proc_fail = AsyncMock()
    mock_proc_fail.returncode = 1
    mock_proc_fail.communicate.return_value = (
        AgentTurnResponse(
            run_id="run-encode-01",
            status="failed",
            output_text="",
            error_message="LiteLLM error HTTP 401",
        )
        .model_dump_json()
        .encode(),
        b"cli failed",
    )
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc_fail
        resp_fail = await client.execute_turn(req)
        cmd_str = " ".join(mock_exec.call_args[0])

    assert "tok%2Ba%2Fb%3Ac%40d@" in cmd_str
    assert resp_fail.status == "failed"
    assert resp_fail.error_message == "LiteLLM error HTTP 401"

    mock_proc_spoof = AsyncMock()
    mock_proc_spoof.returncode = 1
    mock_proc_spoof.communicate.return_value = (
        AgentTurnResponse(run_id="run-encode-01", status="completed", output_text="spoofed").model_dump_json().encode(),
        b"nonzero exit",
    )
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc_spoof
        resp_spoof = await client.execute_turn(req)

    assert resp_spoof.status == "failed"
    assert "nonzero exit" in (resp_spoof.error_message or "")


@pytest.mark.asyncio
async def test_ephemeral_docker_runner_mints_v2_signed_proxy_token_with_repos_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import json

    agents = tmp_path / "agents"
    (agents / "bawtford" / "workspace").mkdir(parents=True)
    (agents / "bawtford" / "memories").mkdir(parents=True)
    (agents / "marvin" / "workspace").mkdir(parents=True)
    (agents / "marvin" / "memories").mkdir(parents=True)

    monkeypatch.setenv("BRAINSOS_AGENTS_DIR", str(agents))
    monkeypatch.setenv("TOOL_EGRESS_PROXY_SECRET", "proxy-hmac-secret-test")
    monkeypatch.delenv("TOOL_EGRESS_PROXY_TOKENS", raising=False)
    monkeypatch.setenv("GITHUB_ALLOWED_REPOS", "org/global-should-not-leak")

    client = EphemeralDockerRunnerClient(image="brainsos-runner-hermes:latest")

    async def _run_tenant(agent_id: str, extra_repos: list[str]) -> list[str]:
        req = AgentTurnRequest(
            run_id=f"run-{agent_id}-1",
            agent_id=agent_id,
            model="m",
            system_prompt="s",
            conversation=[ChatMessage(role="user", content="hi")],
            workspace_dir=str(agents / agent_id / "workspace"),
            extra_params={"github_allowed_repos": extra_repos},
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            AgentTurnResponse(run_id=req.run_id, status="completed", output_text="ok").model_dump_json().encode(),
            b"",
        )
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            await client.execute_turn(req)
            return list(mock_exec.call_args[0])

    def _extract_env(cmd: list[str], key: str) -> str:
        prefix = f"{key}="
        for item in cmd:
            if item.startswith(prefix):
                return item[len(prefix) :]
        return ""

    bawt_cmd = await _run_tenant("bawtford", ["https://github.com/patternsatscale/CindyPawford-Online.git"])
    bawt_tok = _extract_env(bawt_cmd, "TOOL_EGRESS_PROXY_TOKEN")
    assert bawt_tok.startswith("v2.")
    bawt_payload_b64 = bawt_tok.split(".")[1]
    bawt_payload = json.loads(base64.urlsafe_b64decode(bawt_payload_b64 + "=" * (-len(bawt_payload_b64) % 4)))
    assert bawt_payload["t"] == "bawtford"
    assert bawt_payload["repos"] == ["patternsatscale/cindypawford-online"]

    marvin_cmd = await _run_tenant("marvin", [])
    marvin_tok = _extract_env(marvin_cmd, "TOOL_EGRESS_PROXY_TOKEN")
    assert marvin_tok.startswith("v2.")
    marvin_payload_b64 = marvin_tok.split(".")[1]
    marvin_payload = json.loads(base64.urlsafe_b64decode(marvin_payload_b64 + "=" * (-len(marvin_payload_b64) % 4)))
    assert marvin_payload["t"] == "marvin"
    assert marvin_payload["repos"] == []
    assert _extract_env(marvin_cmd, "GITHUB_ALLOWED_REPOS") == ""


