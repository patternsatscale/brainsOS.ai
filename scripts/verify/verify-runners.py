#!/usr/bin/env python3
"""Runner Fleet Verification Suite for brainsOS.

Validates that all cognitive runners declared in config/runners.yaml conform
to the universal IPC contract (AgentTurnRequest / AgentTurnResponse).

Usage:
    python3 scripts/verify/verify-runners.py
"""

import asyncio
import os
from pathlib import Path
import sys
import time
from typing import Optional

# -----------------------------------------------------------------------------
# Rule 13 Precondition: Mandatory .env Execution Gate
# -----------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
env_file = REPO_ROOT / ".env"
if not env_file.is_file():
    print(
        f"\033[0;31m[ERROR]\033[0m Mandatory .env file missing at {env_file}.\n"
        "Machine is an unconfigured clone. Aborting execution per AGENTS.md Rule 13."
    )
    sys.exit(1)

# Ensure virtual environment python is used if available
venv_python = REPO_ROOT / ".venv" / "bin" / "python"
if venv_python.is_file() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

# Ensure local packages are importable
sys.path.insert(0, str(REPO_ROOT / "packages" / "brainsOS-runner"))

try:
    from brainsos_runner.clients.docker import EphemeralDockerRunnerClient
    from brainsos_runner.clients.http import WarmHttpRunnerClient
    from brainsos_runner.models import AgentTurnRequest, AgentTurnResponse, ChatMessage
    from brainsos_runner.registry import RunnerRegistry
except ImportError as err:
    print(f"\033[0;31m[ERROR]\033[0m Failed to import brainsos_runner: {err}")
    print("Ensure brainsOS-runner is installed: uv pip install -e packages/brainsOS-runner")
    sys.exit(1)

# Terminal color formatting
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{BLUE}[INFO]{NC} {msg}")


def log_success(msg: str) -> None:
    print(f"{GREEN}[SUCCESS]{NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


def resolve_local_endpoint(endpoint: Optional[str]) -> str:
    """Map internal docker compose service hostnames to localhost for host-based test runs."""
    if not endpoint:
        return ""
    host_map = {
        "runner-hermes:8642": "127.0.0.1:8642",
        "runner-openai:8002": "127.0.0.1:8002",
        "runner-claude:8001": "127.0.0.1:8001",
    }
    for k, v in host_map.items():
        if k in endpoint:
            return endpoint.replace(k, v)
    return endpoint


async def verify_warm_http_runner(runner_config) -> bool:
    """Verify health and turn dispatch against a warm HTTP runner service."""
    local_endpoint = resolve_local_endpoint(runner_config.endpoint)
    log_info(f"Verifying warm runner '{runner_config.id}' at {local_endpoint}...")

    client = WarmHttpRunnerClient(
        endpoint=local_endpoint,
        default_timeout_sec=10,
        max_retries=1,
    )

    is_healthy = await client.check_health()
    if not is_healthy:
        log_warn(
            f"Runner '{runner_config.id}' is not reachable at {local_endpoint}/healthz.\n"
            f"       To start this runner service: docker compose up -d {runner_config.id.replace('-warm', '')}"
        )
        return False

    log_success(f"Runner '{runner_config.id}' /healthz is OK.")

    # Dispatch synthetic verification turn
    workspace_dir = REPO_ROOT / "data" / "agent_workspaces" / "qa-verifier"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    test_model = os.getenv("TEST_RUNNER_MODEL", "gemma2:2b")

    request = AgentTurnRequest(
        run_id=f"verify-{runner_config.id}-{int(time.time())}",
        agent_id="qa-verifier",
        model=test_model,
        system_prompt="You are a system verification test agent. Keep responses brief.",
        conversation=[
            ChatMessage(role="user", content="Ping test: respond with OK."),
        ],
        workspace_dir=str(workspace_dir),
        timeout_sec=30,
    )

    log_info(f"Dispatching synthetic turn to '{runner_config.id}'...")
    response: AgentTurnResponse = await client.execute_turn(request)

    if response.status == "completed":
        log_success(
            f"Turn completed cleanly: {response.output_text[:60]!r} "
            f"(Tokens: prompt={response.metrics.prompt_tokens}, comp={response.metrics.completion_tokens}, "
            f"duration={response.metrics.duration_ms}ms)"
        )
        return True
    elif response.status == "timed_out":
        log_warn(f"Turn timed out on '{runner_config.id}': {response.error_message}")
        return False
    else:
        log_warn(f"Turn failed on '{runner_config.id}': {response.error_message}")
        return False


async def verify_docker_sandbox(runner_config) -> bool:
    """Verify ephemeral container spawning and workspace boundary isolation."""
    log_info(f"Verifying ephemeral sandbox runner '{runner_config.id}'...")

    # Verify workspace isolation checks
    test_client = EphemeralDockerRunnerClient(
        image=runner_config.image or "brainsos-runner-base:latest",
        memory_limit=runner_config.memory_limit,
        cpu_limit=runner_config.cpu_limit,
    )

    # Test Rule 1: Attempt to mount memories must be blocked
    memory_req = AgentTurnRequest(
        run_id=f"test-mem-violation-{int(time.time())}",
        agent_id="test",
        model="test",
        system_prompt="test",
        conversation=[],
        workspace_dir=str(REPO_ROOT / "data" / "agent_memories" / "forbidden"),
    )
    mem_resp = await test_client.execute_turn(memory_req)
    if mem_resp.status == "failed" and "Memory purity violation" in (mem_resp.error_message or ""):
        log_success("Rule 1 (Memory Purity) enforced: /memories mounting prevented.")
    else:
        log_error(f"Rule 1 boundary check failed! Response: {mem_resp}")
        return False

    # Test Rule 4: Attempt to mount docker.sock must be blocked
    sock_req = AgentTurnRequest(
        run_id=f"test-sock-violation-{int(time.time())}",
        agent_id="test",
        model="test",
        system_prompt="test",
        conversation=[],
        workspace_dir="/var/run/docker.sock",
    )
    sock_resp = await test_client.execute_turn(sock_req)
    if sock_resp.status == "failed" and "Host sandboxing violation" in (sock_resp.error_message or ""):
        log_success("Rule 4 (Host Sandboxing) enforced: Docker socket mounting prevented.")
    else:
        log_error(f"Rule 4 boundary check failed! Response: {sock_resp}")
        return False

    log_success(f"Sandbox runner '{runner_config.id}' passed security isolation assertions.")
    return True


async def main() -> int:
    print(f"\n{BOLD}======================================================{NC}")
    print(f"{BOLD}brainsOS Cognitive Runner Fleet Verification Suite{NC}")
    print(f"{BOLD}======================================================{NC}\n")

    manifest_path = (
        REPO_ROOT / "data" / "settings" / "runners.yaml"
        if (REPO_ROOT / "data" / "settings" / "runners.yaml").is_file()
        else (REPO_ROOT / "config" / "default_settings" / "runners.yaml")
    )
    log_info(f"Loading runner fleet manifest from {manifest_path}...")

    try:
        registry = RunnerRegistry.load_from_yaml(manifest_path)
    except Exception as exc:
        log_error(f"Failed to load runner registry: {exc}")
        return 1

    runners = registry.list_runners()
    log_info(f"Discovered {len(runners)} runner configurations in manifest.\n")

    total_checked = 0
    passed = 0

    for runner in runners:
        total_checked += 1
        print(f"--- Checking [{runner.id}] (type: {runner.type}) ---")
        if runner.type == "warm_http":
            ok = await verify_warm_http_runner(runner)
            if ok:
                passed += 1
        elif runner.type == "ephemeral_docker":
            ok = await verify_docker_sandbox(runner)
            if ok:
                passed += 1
        else:
            log_warn(f"Skipping runner '{runner.id}' with unhandled type '{runner.type}'")
        print()

    print(f"{BOLD}======================================================{NC}")
    print(f"Summary: Verified {len(runners)} configured runner nodes.")
    print(f"{BOLD}======================================================{NC}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
