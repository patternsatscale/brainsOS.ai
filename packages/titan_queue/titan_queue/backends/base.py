"""titan_queue backends base — Abstract storage backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from titan_queue.models import Task, TaskStatus


class QueueBackend(ABC):
    """Abstract interface for work queue persistence and dequeuing."""

    @abstractmethod
    async def enqueue(self, task: Task) -> Task:
        """Enqueue a new task into its specified queue."""
        pass

    @abstractmethod
    async def dequeue(self, queue_name: str) -> Optional[Task]:
        """Atomically pop the next available FIFO task from the specified queue.

        Transitions the task status from QUEUED/FAILED to PROCESSING.
        """
        pass

    @abstractmethod
    async def peek(self, queue_name: str) -> Optional[Task]:
        """Inspect the next FIFO task in the queue without dequeuing it."""
        pass

    @abstractmethod
    async def update_task(self, task: Task) -> Task:
        """Persist updated state of an existing task."""
        pass

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task by its unique ID."""
        pass

    @abstractmethod
    async def size(self, queue_name: str, status: Optional[TaskStatus] = None) -> int:
        """Return the number of tasks in a queue, optionally filtered by status."""
        pass

    @abstractmethod
    async def list_tasks(self, queue_name: str, status: Optional[TaskStatus] = None) -> List[Task]:
        """List tasks for a given queue and optional status."""
        pass

    @abstractmethod
    async def clear(self, queue_name: Optional[str] = None) -> None:
        """Clear all tasks from a queue or from all queues if queue_name is None."""
        pass
