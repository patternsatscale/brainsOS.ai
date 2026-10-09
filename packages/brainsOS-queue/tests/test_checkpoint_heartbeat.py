"""Tests for payload checkpoints and lease heartbeats used by long-running agent runs (#295)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from brainsos_queue.backends.memory import MemoryQueueBackend
from brainsos_queue.backends.sqlite import SQLiteQueueBackend
from brainsos_queue.models import Task, TaskStatus
from brainsos_queue.queue import WorkQueue
from brainsos_queue.worker import FIFOQueueWorker


@pytest.mark.asyncio
async def test_sqlite_update_task_persists_payload_checkpoint(tmp_path: Path) -> None:
    backend = SQLiteQueueBackend(db_path=tmp_path / "q.db")
    queue = WorkQueue("inbound", backend=backend)
    task = await queue.enqueue({"message_id": "<a@x>"})
    acquired = await queue.acquire_task(worker_id="w1")
    assert acquired is not None

    acquired.payload["hermes_run_id"] = "run_123"
    await queue.update_task(acquired)

    reloaded = await queue.get_task(task.id)
    assert reloaded is not None
    assert reloaded.payload["hermes_run_id"] == "run_123"
    assert reloaded.status == TaskStatus.PROCESSING


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["sqlite", "memory"])
async def test_heartbeat_refreshes_processing_lease(tmp_path: Path, backend_kind: str) -> None:
    backend = SQLiteQueueBackend(db_path=tmp_path / "q.db") if backend_kind == "sqlite" else MemoryQueueBackend()
    queue = WorkQueue("inbound", backend=backend)
    await queue.enqueue({"n": 1})
    task = await queue.acquire_task(worker_id="w1")
    assert task is not None
    first_lock = (await queue.get_task(task.id)).locked_at
    await asyncio.sleep(0.02)
    await queue.heartbeat(task.id)
    assert (await queue.get_task(task.id)).locked_at > first_lock


@pytest.mark.asyncio
async def test_worker_heartbeat_prevents_lease_reclaim_during_long_handler(tmp_path: Path) -> None:
    """A handler running longer than lease_timeout_sec must not be reclaimed and re-executed."""
    backend = SQLiteQueueBackend(db_path=tmp_path / "q.db")
    queue = WorkQueue("inbound", backend=backend)
    executions: list[float] = []

    async def slow_handler(task: Task) -> None:
        executions.append(time.time())
        await asyncio.sleep(3.5)  # > lease_timeout_sec (2s) -> needs >=1 heartbeat

    worker = FIFOQueueWorker(queue, slow_handler, concurrency=1, poll_interval=0.05, lease_timeout_sec=3.0)
    task = await queue.enqueue({"n": 1}, partition_key="thread-1")
    worker.start()
    # A second acquirer (e.g. a racing worker slot) must not steal the in-flight task.
    await asyncio.sleep(3.2)
    stolen = await backend.acquire_task(worker_id="intruder", lease_timeout_sec=3.0, queue_name="inbound")
    assert stolen is None
    await asyncio.sleep(0.6)
    await worker.stop()

    final = await queue.get_task(task.id)
    assert final is not None and final.status == TaskStatus.COMPLETED
    assert len(executions) == 1
