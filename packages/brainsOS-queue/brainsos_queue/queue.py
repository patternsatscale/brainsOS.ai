"""brainsos_queue queue — WorkQueue class and registry management."""

from __future__ import annotations

import logging
from typing import Any

from brainsos_queue.backends.base import QueueBackend
from brainsos_queue.backends.memory import MemoryQueueBackend
from brainsos_queue.models import Task, TaskStatus

logger = logging.getLogger("brainsos_queue")


class WorkQueue:
    """A named asynchronous work queue."""

    def __init__(self, name: str, backend: QueueBackend | None = None) -> None:
        self.name = name
        self.backend = backend or MemoryQueueBackend()

    async def enqueue(
        self,
        payload: dict[str, Any],
        task_id: str | None = None,
        max_retries: int = 3,
        partition_key: str | None = None,
    ) -> Task:
        """Enqueue a new unit of work into this queue."""
        kwargs: dict[str, Any] = {
            "queue": self.name,
            "payload": payload,
            "max_retries": max_retries,
            "partition_key": partition_key,
        }
        if task_id:
            kwargs["id"] = task_id

        task = Task(**kwargs)
        enqueued = await self.backend.enqueue(task)
        logger.debug("Enqueued task %s to queue '%s' (partition=%s)", enqueued.id, self.name, partition_key)
        return enqueued

    async def dequeue(self) -> Task | None:
        """Atomically pop the next available FIFO task."""
        return await self.backend.dequeue(self.name)

    async def acquire_task(self, worker_id: str, lease_timeout_sec: float = 120.0) -> Task | None:
        """Atomically acquire the next available task respecting partition locks."""
        return await self.backend.acquire_task(
            worker_id=worker_id, lease_timeout_sec=lease_timeout_sec, queue_name=self.name
        )

    async def peek(self) -> Task | None:
        """Peek at the next available task without dequeuing."""
        return await self.backend.peek(self.name)

    async def update_task(self, task: Task) -> Task:
        """Persist updated task state."""
        return await self.backend.update_task(task)

    async def get_task(self, task_id: str) -> Task | None:
        """Retrieve task by ID."""
        return await self.backend.get_task(task_id)

    async def size(self, status: TaskStatus | None = None) -> int:
        """Return the number of tasks in this queue."""
        return await self.backend.size(self.name, status=status)

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks in this queue."""
        return await self.backend.list_tasks(self.name, status=status)

    async def clear(self) -> None:
        """Clear all tasks from this queue."""
        await self.backend.clear(self.name)


# Global named queue registry
_QUEUES: dict[str, WorkQueue] = {}
_DEFAULT_BACKEND: QueueBackend | None = None


def set_default_backend(backend: QueueBackend) -> None:
    """Set the default backend used when creating registered queues."""
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = backend


def get_queue(name: str = "default", backend: QueueBackend | None = None) -> WorkQueue:
    """Retrieve or create a singleton named queue."""
    if name not in _QUEUES:
        selected_backend = backend or _DEFAULT_BACKEND or MemoryQueueBackend()
        _QUEUES[name] = WorkQueue(name=name, backend=selected_backend)
    return _QUEUES[name]


def clear_registry() -> None:
    """Reset the global queue registry (primarily for test teardown)."""
    global _DEFAULT_BACKEND
    _QUEUES.clear()
    _DEFAULT_BACKEND = None
