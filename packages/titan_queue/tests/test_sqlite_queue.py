"""Unit tests for titan_queue SQLiteQueueBackend."""

import os
import tempfile
import pytest
from titan_queue.backends.sqlite import SQLiteQueueBackend
from titan_queue.models import Task, TaskStatus
from titan_queue.queue import WorkQueue


def test_rule1_memory_plane_purity_violation():
    """Rule 1: SQLite backend must reject placement within /memories."""
    with pytest.raises(ValueError, match="Rule 1 Invariant Violation"):
        SQLiteQueueBackend(db_path="/memories/queue.db")

    with pytest.raises(ValueError, match="Rule 1 Invariant Violation"):
        SQLiteQueueBackend(db_path="./data/agent_memories/terrastella/queue.db")


@pytest.mark.asyncio
async def test_sqlite_fifo_ordering():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        backend = SQLiteQueueBackend(db_path=db_path)
        queue = WorkQueue("sqlite_fifo", backend=backend)

        await queue.enqueue({"seq": 100})
        await queue.enqueue({"seq": 200})

        assert await queue.size() == 2

        t1 = await queue.dequeue()
        assert t1 is not None
        assert t1.payload["seq"] == 100
        assert t1.status == TaskStatus.PROCESSING

        t2 = await queue.dequeue()
        assert t2 is not None
        assert t2.payload["seq"] == 200

        assert await queue.dequeue() is None
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.mark.asyncio
async def test_sqlite_persistence_across_instances():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Enqueue with instance 1
        b1 = SQLiteQueueBackend(db_path=db_path)
        q1 = WorkQueue("persist_test", backend=b1)
        task = await q1.enqueue({"data": "stored_in_sqlite"})

        # Read back with instance 2
        b2 = SQLiteQueueBackend(db_path=db_path)
        q2 = WorkQueue("persist_test", backend=b2)
        assert await q2.size() == 1

        dequeued = await q2.dequeue()
        assert dequeued is not None
        assert dequeued.id == task.id
        assert dequeued.payload["data"] == "stored_in_sqlite"
        assert dequeued.status == TaskStatus.PROCESSING
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
