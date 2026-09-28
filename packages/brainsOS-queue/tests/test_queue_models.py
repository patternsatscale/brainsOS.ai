"""Unit tests for brainsos_queue models."""

import unittest

from brainsos_queue.models import Task, TaskStatus


class TestQueueModels(unittest.TestCase):
    def test_task_creation_and_defaults(self):
        task = Task(queue="test_q", payload={"foo": "bar"})
        self.assertEqual(task.queue, "test_q")
        self.assertEqual(task.payload, {"foo": "bar"})
        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertEqual(task.retries, 0)
        self.assertEqual(task.max_retries, 3)
        self.assertIsNotNone(task.id)
        self.assertGreater(task.created_at, 0)
        self.assertIsNone(task.started_at)
        self.assertIsNone(task.completed_at)

    def test_task_lifecycle_transitions(self):
        task = Task(queue="test_q", payload={"msg": "hello"}, max_retries=2)

        # 1. Start
        task.mark_started()
        self.assertEqual(task.status, TaskStatus.PROCESSING)
        self.assertIsNotNone(task.started_at)

        # 2. First failure (should transition to FAILED for retry)
        task.mark_failed("Temporary network error")
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.retries, 1)
        self.assertEqual(task.error, "Temporary network error")

        # 3. Second failure (retries == max_retries -> DEAD_LETTER)
        task.mark_failed("Permanent failure")
        self.assertEqual(task.status, TaskStatus.DEAD_LETTER)
        self.assertEqual(task.retries, 2)
        self.assertEqual(task.error, "Permanent failure")
        self.assertIsNotNone(task.completed_at)

        # 4. Successful completion
        task2 = Task(queue="test_q", payload={})
        task2.mark_started()
        task2.mark_completed(result={"ok": True})
        self.assertEqual(task2.status, TaskStatus.COMPLETED)
        self.assertEqual(task2.result, {"ok": True})
        self.assertIsNotNone(task2.completed_at)

    def test_task_serialization_roundtrip(self):
        original = Task(
            queue="email_inbound",
            payload={"subject": "test", "id": 123},
            retries=1,
            status=TaskStatus.PROCESSING,
        )
        serialized = original.to_dict()
        self.assertEqual(serialized["queue"], "email_inbound")
        self.assertEqual(serialized["status"], "processing")

        restored = Task.from_dict(serialized)
        self.assertEqual(restored.id, original.id)
        self.assertEqual(restored.queue, original.queue)
        self.assertEqual(restored.payload, original.payload)
        self.assertEqual(restored.status, TaskStatus.PROCESSING)
        self.assertEqual(restored.retries, 1)


if __name__ == "__main__":
    unittest.main()
