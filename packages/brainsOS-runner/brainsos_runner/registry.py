"""Runner Registry and Configuration Loader for brainsOS cognitive compute nodes."""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

import yaml
from pydantic import ValidationError

from brainsos_runner.clients.base import RunnerClient
from brainsos_runner.config import RunnerConfig


class RunnerRegistryError(Exception):
    """Base exception for runner registry errors."""


class RunnerNotFoundError(RunnerRegistryError):
    """Raised when a requested runner_id is not registered."""


class InvalidRunnerConfigError(RunnerRegistryError):
    """Raised when runner configuration is malformed or invalid."""


ClientFactory = Callable[[RunnerConfig], RunnerClient]


class RunnerRegistry:
    """Registry managing available cognitive compute runners and sandboxes."""

    def __init__(self, runners: Optional[Dict[str, RunnerConfig]] = None) -> None:
        self._runners: Dict[str, RunnerConfig] = runners or {}
        self._client_factories: Dict[str, ClientFactory] = {}
        self._register_default_factories()

    def _register_default_factories(self) -> None:
        def _create_warm_http(config: RunnerConfig) -> RunnerClient:
            from brainsos_runner.clients.http import WarmHttpRunnerClient

            assert config.endpoint is not None
            return WarmHttpRunnerClient(
                endpoint=config.endpoint,
                default_timeout_sec=config.timeout_sec,
            )

        def _create_ephemeral_docker(config: RunnerConfig) -> RunnerClient:
            from brainsos_runner.clients.docker import EphemeralDockerRunnerClient

            assert config.image is not None
            return EphemeralDockerRunnerClient(
                image=config.image,
                default_timeout_sec=config.timeout_sec,
                memory_limit=config.memory_limit,
                cpu_limit=config.cpu_limit,
            )

        self._client_factories["warm_http"] = _create_warm_http
        self._client_factories["ephemeral_docker"] = _create_ephemeral_docker

    def register_client_factory(self, runner_type: str, factory: ClientFactory) -> None:
        """Register or override a client factory for a runner type."""
        self._client_factories[runner_type] = factory

    @classmethod
    def load_from_yaml(cls, path: Union[str, Path]) -> "RunnerRegistry":
        """Load runner registry from a YAML manifest file."""
        config_path = Path(path)
        if not config_path.is_file():
            if config_path.name in ("runners.yaml", "default_runners.yaml"):
                for cand in [
                    Path("data/settings/runners.yaml"),
                    Path("config/default_settings/runners.yaml"),
                    Path("config/runners.yaml"),
                ]:
                    if cand.is_file():
                        config_path = cand
                        break

        if not config_path.is_file():
            raise InvalidRunnerConfigError(f"Runner configuration file not found: {path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise InvalidRunnerConfigError(f"Failed to parse YAML from {config_path}: {e}") from e

        if not isinstance(data, dict) or "runners" not in data:
            raise InvalidRunnerConfigError(
                f"Invalid runner manifest at {config_path}: missing top-level 'runners' key"
            )

        raw_runners = data.get("runners")
        if not isinstance(raw_runners, list):
            raise InvalidRunnerConfigError("The 'runners' field must be a list of runner configurations")

        runners: Dict[str, RunnerConfig] = {}
        for entry in raw_runners:
            if not isinstance(entry, dict):
                raise InvalidRunnerConfigError(f"Runner entry must be a dictionary, got: {type(entry)}")
            try:
                config = RunnerConfig.model_validate(entry)
            except (ValidationError, ValueError) as err:
                runner_id = entry.get("id", "<unknown>")
                raise InvalidRunnerConfigError(f"Invalid runner config for '{runner_id}': {err}") from err

            if config.id in runners:
                raise InvalidRunnerConfigError(f"Duplicate runner id detected: '{config.id}'")

            runners[config.id] = config

        return cls(runners=runners)

    def get_runner_config(self, runner_id: str) -> RunnerConfig:
        """Retrieve the configuration for a given runner ID."""
        if runner_id not in self._runners:
            raise RunnerNotFoundError(f"Runner '{runner_id}' is not registered in the runner registry")
        return self._runners[runner_id]

    def get_runner(self, runner_id: str) -> RunnerClient:
        """Instantiate and return the appropriate RunnerClient for a runner ID."""
        config = self.get_runner_config(runner_id)
        factory = self._client_factories.get(config.type)
        if not factory:
            raise InvalidRunnerConfigError(
                f"No client factory registered for runner type '{config.type}' (runner: '{runner_id}')"
            )
        return factory(config)

    def list_runners(self) -> List[RunnerConfig]:
        """List all registered runner configurations."""
        return list(self._runners.values())
