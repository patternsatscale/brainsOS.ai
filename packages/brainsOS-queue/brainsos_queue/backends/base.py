"""brainsos_queue backends base — Abstract storage backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from brainsos_queue.models import Task, TaskStatus


class QueueBackend(ABC):
    """Abstract interface for work queue persistence and dequeuing."""

    @abstractmethod
    async def enqueue(self, task: Task) -> Task:
        """Enqueue a new task into its specified queue."""

    @abstractmethod
    async def dequeue(self, queue_name: str) -> Task | None:
        """Atomically pop the next available FIFO task from the specified queue.

        Transitions the task status from QUEUED/FAILED to PROCESSING.
        """

    @abstractmethod
    async def acquire_task(
        self,
        worker_id: str,
        lease_timeout_sec: float = 120.0,
        queue_name: str | None = None,
    ) -> Task | None:
        """Atomically acquire the next available task respecting partition-level concurrency locks.

        Tasks with the same partition_key are serialized; tasks with distinct partition keys
        execute concurrently. Expired leases (locked_at > lease_timeout_sec) are automatically reclaimed.
        """

    @abstractmethod
    async def peek(self, queue_name: str) -> Task | None:
        """Inspect the next FIFO task in the queue without dequeuing it."""

    @abstractmethod
    async def update_task(self, task: Task) -> Task:
        """Persist updated state of an existing task (including its payload)."""

    async def heartbeat(self, task_id: str) -> None:  # noqa: B027 - optional hook
        """Refresh the lease of a PROCESSING task so long-running handlers are not reclaimed.

        Default implementation is a no-op for backends without lease semantics.
        """

    @abstractmethod
    async def get_task(self, task_id: str) -> Task | None:
        """Retrieve task by its unique ID."""

    @abstractmethod
    async def size(self, queue_name: str, status: TaskStatus | None = None) -> int:
        """Return the number of tasks in a queue, optionally filtered by status."""

    @abstractmethod
    async def list_tasks(self, queue_name: str, status: TaskStatus | None = None) -> list[Task]:
        """List tasks for a given queue and optional status."""

    @abstractmethod
    async def clear(self, queue_name: str | None = None) -> None:
        """Clear all tasks from a queue or from all queues if queue_name is None."""
