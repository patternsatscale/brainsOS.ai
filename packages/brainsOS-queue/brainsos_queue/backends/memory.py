"""brainsos_queue memory backend — High-performance in-memory async work queue."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from brainsos_queue.backends.base import QueueBackend
from brainsos_queue.models import Task, TaskStatus


class MemoryQueueBackend(QueueBackend):
    """In-memory work queue backend using asyncio locks and FIFO ordered dictionaries."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = OrderedDict()
        self._lock = asyncio.Lock()
        self._notify_events: dict[str, asyncio.Event] = {}

    def _get_event(self, queue_name: str) -> asyncio.Event:
        if queue_name not in self._notify_events:
            self._notify_events[queue_name] = asyncio.Event()
        return self._notify_events[queue_name]

    async def enqueue(self, task: Task) -> Task:
        async with self._lock:
            self._tasks[task.id] = task
            # Signal any waiting workers for this queue
            event = self._get_event(task.queue)
            event.set()
        return task

    async def dequeue(self, queue_name: str) -> Task | None:
        return await self.acquire_task(worker_id="default-memory-worker", queue_name=queue_name)

    async def acquire_task(
        self,
        worker_id: str,
        lease_timeout_sec: float = 120.0,
        queue_name: str | None = None,
    ) -> Task | None:
        async with self._lock:
            now = time.time()
            active_cutoff = now - lease_timeout_sec

            # 1. Reclaim expired leases
            for task in self._tasks.values():
                if task.status == TaskStatus.PROCESSING and task.locked_at is not None and task.locked_at <= active_cutoff:
                    task.mark_failed("Lease timeout exceeded (worker crashed)")

            # 2. Identify active partition keys
            active_partitions = {
                t.partition_key
                for t in self._tasks.values()
                if t.status == TaskStatus.PROCESSING
                and t.partition_key is not None
                and t.locked_at is not None
                and t.locked_at > active_cutoff
            }

            # 3. Find oldest queued/failed task not blocked by an active partition lock
            for task in self._tasks.values():
                if queue_name and task.queue != queue_name:
                    continue
                if task.status in (TaskStatus.QUEUED, TaskStatus.FAILED) and task.retries < task.max_retries:
                    if task.partition_key is None or task.partition_key not in active_partitions:
                        task.mark_started(worker_id=worker_id)
                        return task

            if queue_name:
                event = self._get_event(queue_name)
                event.clear()
            return None

    async def peek(self, queue_name: str) -> Task | None:
        async with self._lock:
            for task in self._tasks.values():
                if task.queue == queue_name and task.status in (TaskStatus.QUEUED, TaskStatus.FAILED):
                    return task
            return None

    async def update_task(self, task: Task) -> Task:
        async with self._lock:
            self._tasks[task.id] = task
            if task.status in (TaskStatus.QUEUED, TaskStatus.FAILED):
                event = self._get_event(task.queue)
                event.set()
        return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def size(self, queue_name: str, status: TaskStatus | None = None) -> int:
        async with self._lock:
            if status is None:
                return sum(1 for t in self._tasks.values() if t.queue == queue_name)
            return sum(1 for t in self._tasks.values() if t.queue == queue_name and t.status == status)

    async def list_tasks(self, queue_name: str, status: TaskStatus | None = None) -> list[Task]:
        async with self._lock:
            tasks = [t for t in self._tasks.values() if t.queue == queue_name]
            if status is not None:
                tasks = [t for t in tasks if t.status == status]
            return list(tasks)

    async def clear(self, queue_name: str | None = None) -> None:
        async with self._lock:
            if queue_name is None:
                self._tasks.clear()
                for event in self._notify_events.values():
                    event.clear()
            else:
                to_delete = [t_id for t_id, t in self._tasks.items() if t.queue == queue_name]
                for t_id in to_delete:
                    del self._tasks[t_id]
                event = self._get_event(queue_name)
                event.clear()

    async def wait_for_item(self, queue_name: str, timeout: float | None = None) -> bool:
        """Wait until a new item is available in the queue."""
        event = self._get_event(queue_name)
        try:
            if timeout is not None:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            else:
                await event.wait()
            return True
        except asyncio.TimeoutError:
            return False
