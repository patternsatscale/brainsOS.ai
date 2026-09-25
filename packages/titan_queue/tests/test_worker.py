"""Unit tests for titan_queue FIFOQueueWorker and concurrency manager."""

import asyncio
import time
import pytest
from titan_queue.models import Task, TaskStatus
from titan_queue.queue import WorkQueue
from titan_queue.worker import FIFOQueueWorker


@pytest.mark.asyncio
async def test_worker_fifo_execution():
    queue = WorkQueue("worker_fifo_test")
    processed_items = []

    async def mock_handler(task: Task):
        processed_items.append(task.payload["seq"])
        return f"done_{task.payload['seq']}"

    worker = FIFOQueueWorker(queue=queue, handler=mock_handler, concurrency=1)
    worker.start()

    await queue.enqueue({"seq": 1})
    await queue.enqueue({"seq": 2})
    await queue.enqueue({"seq": 3})

    await worker.stop(drain=True, timeout=5.0)

    assert processed_items == [1, 2, 3]
    tasks = await queue.list_tasks(status=TaskStatus.COMPLETED)
    assert len(tasks) == 3


@pytest.mark.asyncio
async def test_worker_concurrency_serialization():
    """Verify concurrency=1 strictly serializes execution (Rule 3 Hardware Serialization)."""
    queue = WorkQueue("concurrency_test")
    active_concurrent_counts = []
    current_active = 0

    async def slow_handler(task: Task):
        nonlocal current_active
        current_active += 1
        active_concurrent_counts.append(current_active)
        await asyncio.sleep(0.05)
        current_active -= 1

    worker = FIFOQueueWorker(queue=queue, handler=slow_handler, concurrency=1)
    worker.start()

    for i in range(5):
        await queue.enqueue({"idx": i})

    await worker.stop(drain=True, timeout=5.0)

    # Concurrency was set to 1, so active count should never exceed 1
    assert max(active_concurrent_counts) == 1
    completed = await queue.list_tasks(status=TaskStatus.COMPLETED)
    assert len(completed) == 5


@pytest.mark.asyncio
async def test_worker_retries_and_dead_letter():
    queue = WorkQueue("retry_test")
    attempts = 0

    async def failing_handler(task: Task):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Transient connection failure")

    worker = FIFOQueueWorker(
        queue=queue,
        handler=failing_handler,
        concurrency=1,
        backoff_base=0.01,  # Fast backoff for testing
    )
    worker.start()

    # Enqueue task with max_retries=2
    task = await queue.enqueue({"data": "fail_test"}, max_retries=2)

    # Wait for retries to exhaust
    deadline = time.time() + 3.0
    while time.time() < deadline:
        t = await queue.get_task(task.id)
        if t and t.status == TaskStatus.DEAD_LETTER:
            break
        await asyncio.sleep(0.05)

    await worker.stop(drain=False)

    final_task = await queue.get_task(task.id)
    assert final_task is not None
    assert final_task.status == TaskStatus.DEAD_LETTER
    assert final_task.retries == 2
    assert "Transient connection failure" in (final_task.error or "")
