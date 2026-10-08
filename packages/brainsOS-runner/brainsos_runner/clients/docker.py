"""Ephemeral Docker Sandbox Runner Client for deep execution agents."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from brainsos_runner.clients.base import RunnerClient
from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse

logger = logging.getLogger(__name__)


class EphemeralDockerRunnerClient(RunnerClient):
    """Client for launching isolated, on-demand Docker sandbox containers."""

    def __init__(
        self,
        image: str,
        default_timeout_sec: int = 120,
        memory_limit: Optional[str] = "2g",
        cpu_limit: Optional[str] = "2.0",
        network: Optional[str] = "brainsos-internal-net",
        docker_cmd: str = "docker",
    ) -> None:
        self.image = image
        self.default_timeout_sec = default_timeout_sec
        self.memory_limit = memory_limit or "2g"
        self.cpu_limit = cpu_limit or "2.0"
        self.network = network or "brainsos-internal-net"
        self.docker_cmd = docker_cmd

    def _validate_workspace(self, workspace_dir: str) -> Path:
        """Enforce Rule 1 (Memory Purity) and Rule 4 (Host Sandboxing) boundaries."""
        resolved = Path(workspace_dir).resolve()
        path_str = str(resolved).lower()

        # Inviolable Guardrail: Rule 4
        if "docker.sock" in path_str:
            raise ValueError("Host sandboxing violation: Docker socket cannot be mounted into runner container")

        # Inviolable Guardrail: Rule 1
        if "memories" in path_str or "agent_memories" in path_str:
            raise ValueError("Memory purity violation: Agent /memories cannot be mounted into sandbox container")

        if not resolved.exists():
            resolved.mkdir(parents=True, exist_ok=True)

        return resolved

    async def execute_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        """Launch ephemeral container, pipe request, await completion, and enforce hard cleanup."""
        timeout_sec = request.timeout_sec or self.default_timeout_sec

        try:
            workspace_path = self._validate_workspace(request.workspace_dir)
        except ValueError as err:
            logger.error("Sandbox workspace validation failed: %s", err)
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=str(err),
            )

        container_name = f"brainsos-sandbox-{request.run_id}-{int(time.time())}"
        request_file = workspace_path / f".brainsos_request_{request.run_id}.json"
        try:
            request_file.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Failed to write request payload: {exc}",
            )

        cmd = [
            self.docker_cmd,
            "run",
            "--rm",
            "-i",
            "--name",
            container_name,
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            f"--network={self.network}",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{workspace_path}:/workspace:rw",
            "-e",
            f"BRAINSOS_RUN_ID={request.run_id}",
            "-e",
            f"BRAINSOS_AGENT_ID={request.agent_id}",
            "-e",
            f"BRAINSOS_MODEL={request.model}",
            "-e",
            f"BRAINSOS_REQUEST_FILE=/workspace/{request_file.name}",
            self.image,
        ]

        proc = None
        timed_out = False
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=request.model_dump_json().encode("utf-8")),
                timeout=float(timeout_sec),
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        except (asyncio.TimeoutError, TimeoutError):
            timed_out = True
            logger.warning("Sandbox container %s timed out after %ds, killing...", container_name, timeout_sec)
            try:
                kill_proc = await asyncio.create_subprocess_exec(
                    self.docker_cmd,
                    "kill",
                    container_name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proc.wait()
            except Exception as kill_err:
                logger.error("Failed to kill container %s: %s", container_name, kill_err)

            return AgentTurnResponse(
                run_id=request.run_id,
                status="timed_out",
                output_text="",
                error_message=f"Sandbox container execution timed out after {timeout_sec}s",
            )
        except Exception as exc:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text="",
                error_message=f"Failed to spawn sandbox container: {exc}",
            )
        finally:
            # Clean up temporary request payload
            try:
                if request_file.exists():
                    request_file.unlink()
            except Exception:
                pass

            # Guarantee cleanup: remove any lingering container instance
            if timed_out or (proc and proc.returncode is None):
                try:
                    rm_proc = await asyncio.create_subprocess_exec(
                        self.docker_cmd,
                        "rm",
                        "-f",
                        container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await rm_proc.wait()
                except Exception:
                    pass

        # Attempt to parse response from stdout
        if proc.returncode == 0:
            # 1. Try direct JSON parse of full output
            try:
                data = json.loads(stdout)
                if isinstance(data, dict) and "run_id" in data and "status" in data:
                    return AgentTurnResponse.model_validate(data)
            except Exception:
                pass

            # 2. Check for response written by sandbox into workspace
            response_file = workspace_path / f".brainsos_response_{request.run_id}.json"
            if response_file.exists():
                try:
                    data = json.loads(response_file.read_text(encoding="utf-8"))
                    response_file.unlink()
                    return AgentTurnResponse.model_validate(data)
                except Exception:
                    pass

            # 3. Fallback: treat stdout as output text
            return AgentTurnResponse(
                run_id=request.run_id,
                status="completed",
                output_text=stdout,
            )
        else:
            return AgentTurnResponse(
                run_id=request.run_id,
                status="failed",
                output_text=stdout,
                error_message=stderr or f"Sandbox container exited with code {proc.returncode}",
            )
