"""Unit tests for thread-partition concurrency locking in SQLite work queue."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest

from brainsos_queue.backends.sqlite import SQLiteQueueBackend
from brainsos_queue.models import Task, TaskStatus
from brainsos_queue.queue import WorkQueue
from brainsos_queue.worker import FIFOQueueWorker


class TestPartitionLock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp_file.name
        self.tmp_file.close()
        self.backend = SQLiteQueueBackend(db_path=self.db_path)

    async def asyncTearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_sequential_execution_same_partition(self):
        """Verify multiple jobs for Thread A are processed sequentially."""
        backend = self.backend
        q = "test-sequential"

        task_a1 = Task(queue=q, payload={"step": 1}, partition_key="thread-A")
        task_a2 = Task(queue=q, payload={"step": 2}, partition_key="thread-A")

        await backend.enqueue(task_a1)
        await backend.enqueue(task_a2)

        # Worker 1 acquires task A1
        w1_task = await backend.acquire_task(worker_id="worker-1", queue_name=q)
        self.assertIsNotNone(w1_task)
        self.assertEqual(w1_task.id, task_a1.id)
        self.assertEqual(w1_task.status, TaskStatus.PROCESSING)
        self.assertEqual(w1_task.partition_key, "thread-A")

        # Worker 2 attempts to acquire while task A1 is processing -> must be blocked
        w2_task = await backend.acquire_task(worker_id="worker-2", queue_name=q)
        self.assertIsNone(w2_task, "Worker 2 must not acquire task A2 while Thread A partition is locked")

        # Worker 1 completes task A1 -> releases partition lock
        w1_task.mark_completed({"output": "done"})
        await backend.update_task(w1_task)

        # Now Worker 2 can acquire task A2
        w2_task_after = await backend.acquire_task(worker_id="worker-2", queue_name=q)
        self.assertIsNotNone(w2_task_after)
        self.assertEqual(w2_task_after.id, task_a2.id)
        self.assertEqual(w2_task_after.payload["step"], 2)

    async def test_concurrent_execution_distinct_partitions(self):
        """Verify a job for Thread B executes in parallel alongside Thread A without blocking."""
        backend = self.backend
        q = "test-concurrent"

        task_a1 = Task(queue=q, payload={"thread": "A", "step": 1}, partition_key="thread-A")
        task_a2 = Task(queue=q, payload={"thread": "A", "step": 2}, partition_key="thread-A")
        task_b1 = Task(queue=q, payload={"thread": "B", "step": 1}, partition_key="thread-B")

        await backend.enqueue(task_a1)
        await backend.enqueue(task_a2)
        await backend.enqueue(task_b1)

        # Worker 1 acquires task A1
        w1_task = await backend.acquire_task(worker_id="worker-1", queue_name=q)
        self.assertIsNotNone(w1_task)
        self.assertEqual(w1_task.id, task_a1.id)
        self.assertEqual(w1_task.partition_key, "thread-A")

        # Worker 2 attempts acquire: task A2 is blocked by partition-A, so it skips to task B1!
        w2_task = await backend.acquire_task(worker_id="worker-2", queue_name=q)
        self.assertIsNotNone(w2_task)
        self.assertEqual(w2_task.id, task_b1.id)
        self.assertEqual(w2_task.partition_key, "thread-B")

        # Worker 3 attempts acquire: partition A is locked, partition B is locked, no tasks left
        w3_task = await backend.acquire_task(worker_id="worker-3", queue_name=q)
        self.assertIsNone(w3_task)

    async def test_null_partition_key_concurrency(self):
        """Verify tasks without a partition key do not block each other."""
        backend = self.backend
        q = "test-null-partition"

        task_1 = Task(queue=q, payload={"job": 1}, partition_key=None)
        task_2 = Task(queue=q, payload={"job": 2}, partition_key=None)

        await backend.enqueue(task_1)
        await backend.enqueue(task_2)

        w1_task = await backend.acquire_task(worker_id="worker-1", queue_name=q)
        self.assertIsNotNone(w1_task)
        self.assertEqual(w1_task.id, task_1.id)

        # Second null-partition task can be acquired concurrently
        w2_task = await backend.acquire_task(worker_id="worker-2", queue_name=q)
        self.assertIsNotNone(w2_task)
        self.assertEqual(w2_task.id, task_2.id)

    async def test_partition_lock_lease_expiration_and_reclaim(self):
        """Verify partition locks automatically expire after lease_timeout if worker crashes."""
        backend = self.backend
        q = "test-reclaim"

        task_a1 = Task(queue=q, payload={"step": 1}, partition_key="thread-A")
        task_a2 = Task(queue=q, payload={"step": 2}, partition_key="thread-A")

        await backend.enqueue(task_a1)
        await backend.enqueue(task_a2)

        # Worker 1 acquires task with short lease timeout of 0.2s
        w1_task = await backend.acquire_task(worker_id="worker-1", lease_timeout_sec=0.2, queue_name=q)
        self.assertIsNotNone(w1_task)
        self.assertEqual(w1_task.id, task_a1.id)

        # Worker 1 "crashes" (does not mark completed or update)
        # Attempt to acquire immediately -> blocked
        blocked = await backend.acquire_task(worker_id="worker-2", lease_timeout_sec=0.2, queue_name=q)
        self.assertIsNone(blocked)

        # Wait for lease to expire
        await asyncio.sleep(0.25)

        # Worker 2 acquires task -> lease is reclaimed, expired task fails/retries, task acquired
        reclaimed = await backend.acquire_task(worker_id="worker-2", lease_timeout_sec=0.2, queue_name=q)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed.partition_key, "thread-A")

    async def test_worker_fifo_partition_execution_timeline(self):
        """Test FIFOQueueWorker with concurrency=2: Thread A tasks are sequential while Thread B overlaps."""
        backend = self.backend
        queue = WorkQueue(name="worker-partition-test", backend=backend)

        execution_log: list[tuple[str, str, float]] = []

        async def handler(task: Task):
            name = task.payload["name"]
            execution_log.append((name, "start", time.time()))
            await asyncio.sleep(0.1)
            execution_log.append((name, "end", time.time()))
            return "done"

        worker = FIFOQueueWorker(queue=queue, handler=handler, concurrency=2, poll_interval=0.02)
        worker.start()

        # Enqueue: A1 (0.1s), A2 (0.1s), B1 (0.1s)
        await queue.enqueue(payload={"name": "A1"}, partition_key="thread-A")
        await queue.enqueue(payload={"name": "A2"}, partition_key="thread-A")
        await queue.enqueue(payload={"name": "B1"}, partition_key="thread-B")

        # Wait for processing
        await asyncio.sleep(0.35)
        await worker.stop(drain=True)

        events: dict[str, dict[str, float]] = {}
        for name, event_type, ts in execution_log:
            if name not in events:
                events[name] = {}
            events[name][event_type] = ts

        self.assertIn("A1", events)
        self.assertIn("A2", events)
        self.assertIn("B1", events)

        # Concurrency verification: A1 and B1 execute concurrently (A1 start <= B1 end and B1 start <= A1 end)
        self.assertLess(events["A1"]["start"], events["B1"]["end"])
        self.assertLess(events["B1"]["start"], events["A1"]["end"])

        # Causality verification: A2 starts strictly AFTER A1 has ended (Thread A is serialized)
        self.assertGreaterEqual(events["A2"]["start"], events["A1"]["end"] - 0.02)

    def test_rule1_memory_plane_purity(self):
        """Verify Rule 1: Queue database path must never reside within /memories."""
        with self.assertRaises(ValueError):
            SQLiteQueueBackend(db_path="/memories/queue.db")

        with self.assertRaises(ValueError):
            SQLiteQueueBackend(db_path="/data/agent_memories/marvin/queue.db")


if __name__ == "__main__":
    unittest.main()
