"""Unit tests for RunnerRegistry and RunnerConfig."""

from pathlib import Path

import pytest
from brainsos_runner.clients.base import RunnerClient
from brainsos_runner.config import RunnerConfig
from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse
from brainsos_runner.registry import (
    InvalidRunnerConfigError,
    RunnerNotFoundError,
    RunnerRegistry,
)
from pydantic import ValidationError


def test_runner_config_validation():
    # Valid warm_http
    cfg = RunnerConfig(id="test-http", type="warm_http", endpoint="http://localhost:8000")
    assert cfg.id == "test-http"
    assert cfg.timeout_sec == 120
    assert cfg.concurrency_limit == 4

    # Invalid warm_http missing endpoint
    with pytest.raises(ValidationError):
        RunnerConfig(id="bad-http", type="warm_http")

    # Valid ephemeral_docker
    cfg_docker = RunnerConfig(id="test-docker", type="ephemeral_docker", image="ubuntu:latest")
    assert cfg_docker.image == "ubuntu:latest"

    # Invalid ephemeral_docker missing image
    with pytest.raises(ValidationError):
        RunnerConfig(id="bad-docker", type="ephemeral_docker")

    # Valid local_script
    cfg_script = RunnerConfig(id="test-script", type="local_script", script_path="/scripts/run.py")
    assert cfg_script.script_path == "/scripts/run.py"

    # Invalid local_script missing script_path
    with pytest.raises(ValidationError):
        RunnerConfig(id="bad-script", type="local_script")

    # Negative timeout
    with pytest.raises(ValidationError):
        RunnerConfig(id="bad-timeout", type="warm_http", endpoint="http://localhost", timeout_sec=0)


def test_load_authoritative_runners_yaml():
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    runners_yaml_path = (
        repo_root / "config" / "default_settings" / "runners.yaml"
        if (repo_root / "config" / "default_settings" / "runners.yaml").exists()
        else repo_root / "config" / "runners.yaml"
    )
    assert runners_yaml_path.exists(), f"Manifest missing at {runners_yaml_path}"

    registry = RunnerRegistry.load_from_yaml(runners_yaml_path)
    runners = registry.list_runners()
    assert len(runners) == 4

    # hermes-warm
    hermes = registry.get_runner_config("hermes-warm")
    assert hermes.type == "warm_http"
    assert "8642" in (hermes.endpoint or "")

    # openai-warm
    openai_cfg = registry.get_runner_config("openai-warm")
    assert openai_cfg.type == "warm_http"
    assert "8002" in (openai_cfg.endpoint or "")

    # claude-warm
    claude_cfg = registry.get_runner_config("claude-warm")
    assert claude_cfg.type == "warm_http"
    assert "8001" in (claude_cfg.endpoint or "")

    # openhands-sandbox
    sandbox = registry.get_runner_config("openhands-sandbox")
    assert sandbox.type == "ephemeral_docker"
    assert sandbox.image == "brainsos-openhands-sandbox:latest"
    assert sandbox.memory_limit == "2g"
    assert sandbox.cpu_limit == "2.0"


def test_registry_not_found(tmp_path: Path):
    reg = RunnerRegistry()
    with pytest.raises(RunnerNotFoundError):
        reg.get_runner_config("nonexistent")


def test_registry_file_not_found(tmp_path: Path):
    with pytest.raises(InvalidRunnerConfigError):
        RunnerRegistry.load_from_yaml(tmp_path / "nonexistent.yaml")


def test_registry_invalid_yaml(tmp_path: Path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("runners: [invalid yaml: ::", encoding="utf-8")
    with pytest.raises(InvalidRunnerConfigError):
        RunnerRegistry.load_from_yaml(bad_yaml)


def test_registry_missing_runners_key(tmp_path: Path):
    yaml_file = tmp_path / "missing_runners.yaml"
    yaml_file.write_text("version: '1.0'\nservices: []", encoding="utf-8")
    with pytest.raises(InvalidRunnerConfigError):
        RunnerRegistry.load_from_yaml(yaml_file)


def test_registry_duplicate_runner_id(tmp_path: Path):
    yaml_file = tmp_path / "dup.yaml"
    yaml_file.write_text(
        """
runners:
  - id: dup-1
    type: warm_http
    endpoint: http://localhost:8001
  - id: dup-1
    type: warm_http
    endpoint: http://localhost:8002
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidRunnerConfigError):
        RunnerRegistry.load_from_yaml(yaml_file)


def test_registry_custom_client_factory():
    class DummyClient(RunnerClient):
        async def execute_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="completed",
                output_text="dummy response",
            )

    registry = RunnerRegistry(
        runners={
            "custom": RunnerConfig(
                id="custom",
                type="warm_http",
                endpoint="http://dummy:8000",
            )
        }
    )
    registry.register_client_factory("warm_http", lambda cfg: DummyClient())

    client = registry.get_runner("custom")
    assert isinstance(client, DummyClient)


def test_registry_get_warm_http_runner():
    from brainsos_runner.clients.http import WarmHttpRunnerClient

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    registry = RunnerRegistry.load_from_yaml(repo_root / "config" / "runners.yaml")
    client = registry.get_runner("hermes-warm")
    assert isinstance(client, WarmHttpRunnerClient)
    assert client.endpoint == "http://runner-hermes:8642"
