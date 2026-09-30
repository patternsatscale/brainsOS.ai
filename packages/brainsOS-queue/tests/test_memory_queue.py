"""Unit tests for brainsos_queue MemoryQueueBackend and WorkQueue."""

import unittest

from brainsos_queue.backends.memory import MemoryQueueBackend
from brainsos_queue.models import TaskStatus
from brainsos_queue.queue import WorkQueue, clear_registry, get_queue


class TestMemoryQueue(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        clear_registry()

    async def asyncTearDown(self):
        clear_registry()

    async def test_fifo_ordering(self):
        queue = WorkQueue("fifo_test", backend=MemoryQueueBackend())

        await queue.enqueue({"seq": 1})
        await queue.enqueue({"seq": 2})
        await queue.enqueue({"seq": 3})

        self.assertEqual(await queue.size(), 3)

        t1 = await queue.dequeue()
        self.assertIsNotNone(t1)
        self.assertEqual(t1.payload["seq"], 1)
        self.assertEqual(t1.status, TaskStatus.PROCESSING)

        t2 = await queue.dequeue()
        self.assertIsNotNone(t2)
        self.assertEqual(t2.payload["seq"], 2)

        t3 = await queue.dequeue()
        self.assertIsNotNone(t3)
        self.assertEqual(t3.payload["seq"], 3)

        self.assertIsNone(await queue.dequeue())

    async def test_peek_behavior(self):
        queue = WorkQueue("peek_test", backend=MemoryQueueBackend())
        await queue.enqueue({"data": "alpha"})

        peeked = await queue.peek()
        self.assertIsNotNone(peeked)
        self.assertEqual(peeked.payload["data"], "alpha")
        self.assertEqual(peeked.status, TaskStatus.QUEUED)

        # Queue size should not decrease on peek
        self.assertEqual(await queue.size(), 1)

        dequeued = await queue.dequeue()
        self.assertEqual(dequeued.id, peeked.id)
        self.assertEqual(dequeued.status, TaskStatus.PROCESSING)

    async def test_multi_queue_isolation(self):
        q_email = get_queue("email_inbound")
        q_builder = get_queue("web_builder")

        await q_email.enqueue({"email": "admin@brainsos.local"})
        await q_builder.enqueue({"site": "cindypawford"})

        self.assertEqual(await q_email.size(), 1)
        self.assertEqual(await q_builder.size(), 1)

        t_email = await q_email.dequeue()
        self.assertEqual(t_email.payload["email"], "admin@brainsos.local")

        # web_builder queue should still have its task
        self.assertEqual(await q_builder.size(TaskStatus.QUEUED), 1)
        t_builder = await q_builder.dequeue()
        self.assertEqual(t_builder.payload["site"], "cindypawford")

    async def test_queue_clear(self):
        queue = WorkQueue("clear_test")
        await queue.enqueue({"a": 1})
        await queue.enqueue({"b": 2})
        self.assertEqual(await queue.size(), 2)

        await queue.clear()
        self.assertEqual(await queue.size(), 0)
        self.assertIsNone(await queue.dequeue())


if __name__ == "__main__":
    unittest.main()
