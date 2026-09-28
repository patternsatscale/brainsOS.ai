"""Unit tests for brainsos_queue SQLiteQueueBackend."""

import os
import tempfile
import unittest

from brainsos_queue.backends.sqlite import SQLiteQueueBackend
from brainsos_queue.models import TaskStatus
from brainsos_queue.queue import WorkQueue


class TestSQLiteQueue(unittest.IsolatedAsyncioTestCase):
    def test_rule1_memory_plane_purity_violation(self):
        """Rule 1: SQLite backend must reject placement within /memories."""
        with self.assertRaises(ValueError):
            SQLiteQueueBackend(db_path="/memories/queue.db")

        with self.assertRaises(ValueError):
            SQLiteQueueBackend(db_path="./data/agent_memories/terrastella/queue.db")

    async def test_sqlite_fifo_ordering(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteQueueBackend(db_path=db_path)
            queue = WorkQueue("sqlite_fifo", backend=backend)

            await queue.enqueue({"seq": 100})
            await queue.enqueue({"seq": 200})

            self.assertEqual(await queue.size(), 2)

            t1 = await queue.dequeue()
            self.assertIsNotNone(t1)
            self.assertEqual(t1.payload["seq"], 100)
            self.assertEqual(t1.status, TaskStatus.PROCESSING)

            t2 = await queue.dequeue()
            self.assertIsNotNone(t2)
            self.assertEqual(t2.payload["seq"], 200)

            self.assertIsNone(await queue.dequeue())
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    async def test_sqlite_persistence_across_instances(self):
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
            self.assertEqual(await q2.size(), 1)

            dequeued = await q2.dequeue()
            self.assertIsNotNone(dequeued)
            self.assertEqual(dequeued.id, task.id)
            self.assertEqual(dequeued.payload["data"], "stored_in_sqlite")
            self.assertEqual(dequeued.status, TaskStatus.PROCESSING)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
