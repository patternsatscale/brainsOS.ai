"""titan_queue memory backend — High-performance in-memory async work queue."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Dict, List, Optional

from titan_queue.backends.base import QueueBackend
from titan_queue.models import Task, TaskStatus


class MemoryQueueBackend(QueueBackend):
    """In-memory work queue backend using asyncio locks and FIFO ordered dictionaries."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = OrderedDict()
        self._lock = asyncio.Lock()
        self._notify_events: Dict[str, asyncio.Event] = {}

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

    async def dequeue(self, queue_name: str) -> Optional[Task]:
        async with self._lock:
            for task in self._tasks.values():
                if task.queue == queue_name and task.status in (TaskStatus.QUEUED, TaskStatus.FAILED):
                    task.mark_started()
                    return task
            # No eligible tasks; clear notification event
            event = self._get_event(queue_name)
            event.clear()
            return None

    async def peek(self, queue_name: str) -> Optional[Task]:
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

    async def get_task(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def size(self, queue_name: str, status: Optional[TaskStatus] = None) -> int:
        async with self._lock:
            if status is None:
                return sum(1 for t in self._tasks.values() if t.queue == queue_name)
            return sum(1 for t in self._tasks.values() if t.queue == queue_name and t.status == status)

    async def list_tasks(self, queue_name: str, status: Optional[TaskStatus] = None) -> List[Task]:
        async with self._lock:
            tasks = [t for t in self._tasks.values() if t.queue == queue_name]
            if status is not None:
                tasks = [t for t in tasks if t.status == status]
            return list(tasks)

    async def clear(self, queue_name: Optional[str] = None) -> None:
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

    async def wait_for_item(self, queue_name: str, timeout: Optional[float] = None) -> bool:
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
