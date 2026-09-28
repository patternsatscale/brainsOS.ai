"""Unit tests for brainsos_queue FIFOQueueWorker and concurrency manager."""

import asyncio
import time
import unittest

from brainsos_queue.models import Task, TaskStatus
from brainsos_queue.queue import WorkQueue
from brainsos_queue.worker import FIFOQueueWorker


class TestQueueWorker(unittest.IsolatedAsyncioTestCase):
    async def test_worker_fifo_execution(self):
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

        self.assertEqual(processed_items, [1, 2, 3])
        tasks = await queue.list_tasks(status=TaskStatus.COMPLETED)
        self.assertEqual(len(tasks), 3)

    async def test_worker_concurrency_serialization(self):
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
        self.assertEqual(max(active_concurrent_counts), 1)
        completed = await queue.list_tasks(status=TaskStatus.COMPLETED)
        self.assertEqual(len(completed), 5)

    async def test_worker_retries_and_dead_letter(self):
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
        self.assertIsNotNone(final_task)
        self.assertEqual(final_task.status, TaskStatus.DEAD_LETTER)
        self.assertEqual(final_task.retries, 2)
        self.assertIn("Transient connection failure", (final_task.error or ""))

    async def test_worker_telemetry_bus_integration(self):
        """Verify worker dispatches task_started, task_completed, and task_failed to TelemetryBus."""
        from brainsos_telemetry import SyntheticEnergyObserver, TelemetryBus

        bus = TelemetryBus()
        observer = SyntheticEnergyObserver()
        bus.attach(observer)

        queue = WorkQueue("telemetry_worker_test")
        events_captured = []

        class EventCollector:
            def on_telemetry(self, event):
                events_captured.append(event)

        bus.attach(EventCollector())

        async def handler(task: Task):
            if task.payload.get("should_fail"):
                raise ValueError("Intentional error")
            return "ok"

        worker = FIFOQueueWorker(queue=queue, handler=handler, concurrency=1, telemetry_bus=bus)
        worker.start()

        # Enqueue success task
        await queue.enqueue({"agent_id": "terrastella", "tokens": 150, "should_fail": False})
        # Enqueue failure task (max_retries=1 so it moves immediately to DEAD_LETTER)
        await queue.enqueue({"agent_id": "marvin", "tokens": 50, "should_fail": True}, max_retries=1)

        await worker.stop(drain=True, timeout=5.0)

        event_types = [e.event_type for e in events_captured]
        self.assertIn("task_started", event_types)
        self.assertIn("task_completed", event_types)
        self.assertIn("task_failed", event_types)

        # Verify synthetic energy was calculated for completed task
        completed_events = [e for e in events_captured if e.event_type == "task_completed"]
        self.assertTrue(len(completed_events) >= 1)
        self.assertTrue(completed_events[0].energy_millijoules > 0)
        self.assertEqual(completed_events[0].agent_id, "terrastella")


if __name__ == "__main__":
    unittest.main()
