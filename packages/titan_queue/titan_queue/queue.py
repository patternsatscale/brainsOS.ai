"""titan_queue queue — WorkQueue class and registry management."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from titan_queue.backends.base import QueueBackend
from titan_queue.backends.memory import MemoryQueueBackend
from titan_queue.models import Task, TaskStatus

logger = logging.getLogger("titan_queue")


class WorkQueue:
    """A named asynchronous work queue."""

    def __init__(self, name: str, backend: Optional[QueueBackend] = None) -> None:
        self.name = name
        self.backend = backend or MemoryQueueBackend()

    async def enqueue(
        self,
        payload: Dict[str, Any],
        task_id: Optional[str] = None,
        max_retries: int = 3,
    ) -> Task:
        """Enqueue a new unit of work into this queue."""
        kwargs: Dict[str, Any] = {
            "queue": self.name,
            "payload": payload,
            "max_retries": max_retries,
        }
        if task_id:
            kwargs["id"] = task_id

        task = Task(**kwargs)
        enqueued = await self.backend.enqueue(task)
        logger.debug("Enqueued task %s to queue '%s'", enqueued.id, self.name)
        return enqueued

    async def dequeue(self) -> Optional[Task]:
        """Atomically pop the next available FIFO task."""
        return await self.backend.dequeue(self.name)

    async def peek(self) -> Optional[Task]:
        """Peek at the next available task without dequeuing."""
        return await self.backend.peek(self.name)

    async def update_task(self, task: Task) -> Task:
        """Persist updated task state."""
        return await self.backend.update_task(task)

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task by ID."""
        return await self.backend.get_task(task_id)

    async def size(self, status: Optional[TaskStatus] = None) -> int:
        """Return the number of tasks in this queue."""
        return await self.backend.size(self.name, status=status)

    async def list_tasks(self, status: Optional[TaskStatus] = None) -> List[Task]:
        """List tasks in this queue."""
        return await self.backend.list_tasks(self.name, status=status)

    async def clear(self) -> None:
        """Clear all tasks from this queue."""
        await self.backend.clear(self.name)


# Global named queue registry
_QUEUES: Dict[str, WorkQueue] = {}
_DEFAULT_BACKEND: Optional[QueueBackend] = None


def set_default_backend(backend: QueueBackend) -> None:
    """Set the default backend used when creating registered queues."""
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = backend


def get_queue(name: str = "default", backend: Optional[QueueBackend] = None) -> WorkQueue:
    """Retrieve or create a singleton named queue."""
    global _QUEUES, _DEFAULT_BACKEND
    if name not in _QUEUES:
        selected_backend = backend or _DEFAULT_BACKEND or MemoryQueueBackend()
        _QUEUES[name] = WorkQueue(name=name, backend=selected_backend)
    return _QUEUES[name]


def clear_registry() -> None:
    """Reset the global queue registry (primarily for test teardown)."""
    global _QUEUES, _DEFAULT_BACKEND
    _QUEUES.clear()
    _DEFAULT_BACKEND = None
