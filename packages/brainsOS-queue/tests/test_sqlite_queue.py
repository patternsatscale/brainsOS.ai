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

    def test_default_queue_db_path_resolution(self):
        from brainsos_queue.backends.sqlite import get_default_queue_db_path

        old_q = os.environ.get("BRAINSOS_QUEUE_DB")
        old_d = os.environ.get("BRAINSOS_DATA_DIR")

        try:
            os.environ.pop("BRAINSOS_QUEUE_DB", None)
            os.environ.pop("BRAINSOS_DATA_DIR", None)
            self.assertEqual(get_default_queue_db_path(), "/workspace/queue.db")

            os.environ["BRAINSOS_DATA_DIR"] = "/tmp/ext_data"
            self.assertEqual(get_default_queue_db_path(), "/tmp/ext_data/queue/tasks.db")

            os.environ["BRAINSOS_QUEUE_DB"] = "/tmp/custom_queue.db"
            self.assertEqual(get_default_queue_db_path(), "/tmp/custom_queue.db")
        finally:
            for k, v in [("BRAINSOS_QUEUE_DB", old_q), ("BRAINSOS_DATA_DIR", old_d)]:
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
