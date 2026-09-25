"""Unit tests for titan_queue MemoryQueueBackend and WorkQueue."""

import pytest
from titan_queue.backends.memory import MemoryQueueBackend
from titan_queue.models import Task, TaskStatus
from titan_queue.queue import WorkQueue, clear_registry, get_queue


@pytest.fixture(autouse=True)
def cleanup():
    clear_registry()
    yield
    clear_registry()


@pytest.mark.asyncio
async def test_fifo_ordering():
    queue = WorkQueue("fifo_test", backend=MemoryQueueBackend())

    await queue.enqueue({"seq": 1})
    await queue.enqueue({"seq": 2})
    await queue.enqueue({"seq": 3})

    assert await queue.size() == 3

    t1 = await queue.dequeue()
    assert t1 is not None
    assert t1.payload["seq"] == 1
    assert t1.status == TaskStatus.PROCESSING

    t2 = await queue.dequeue()
    assert t2 is not None
    assert t2.payload["seq"] == 2

    t3 = await queue.dequeue()
    assert t3 is not None
    assert t3.payload["seq"] == 3

    assert await queue.dequeue() is None


@pytest.mark.asyncio
async def test_peek_behavior():
    queue = WorkQueue("peek_test", backend=MemoryQueueBackend())
    await queue.enqueue({"data": "alpha"})

    peeked = await queue.peek()
    assert peeked is not None
    assert peeked.payload["data"] == "alpha"
    assert peeked.status == TaskStatus.QUEUED

    # Queue size should not decrease on peek
    assert await queue.size() == 1

    dequeued = await queue.dequeue()
    assert dequeued.id == peeked.id
    assert dequeued.status == TaskStatus.PROCESSING


@pytest.mark.asyncio
async def test_multi_queue_isolation():
    q_email = get_queue("email_inbound")
    q_builder = get_queue("web_builder")

    await q_email.enqueue({"email": "admin@titan.local"})
    await q_builder.enqueue({"site": "cindypawford"})

    assert await q_email.size() == 1
    assert await q_builder.size() == 1

    t_email = await q_email.dequeue()
    assert t_email.payload["email"] == "admin@titan.local"

    # web_builder queue should still have its task
    assert await q_builder.size(TaskStatus.QUEUED) == 1
    t_builder = await q_builder.dequeue()
    assert t_builder.payload["site"] == "cindypawford"


@pytest.mark.asyncio
async def test_queue_clear():
    queue = WorkQueue("clear_test")
    await queue.enqueue({"a": 1})
    await queue.enqueue({"b": 2})
    assert await queue.size() == 2

    await queue.clear()
    assert await queue.size() == 0
    assert await queue.dequeue() is None
