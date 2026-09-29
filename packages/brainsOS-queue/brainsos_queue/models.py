"""brainsos_queue models — Data structures and lifecycle states for work queues."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Lifecycle state of a queued task."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class Task:
    """A discrete unit of asynchronous work."""
    queue: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.QUEUED
    partition_key: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    locked_at: float | None = None
    locked_by: str | None = None
    retries: int = 0
    max_retries: int = 3
    error: str | None = None
    result: Any | None = None

    def mark_started(self, worker_id: str | None = None) -> None:
        """Mark task as actively executing and record lease lock."""
        self.status = TaskStatus.PROCESSING
        now = time.time()
        self.started_at = now
        self.locked_at = now
        if worker_id:
            self.locked_by = worker_id

    def mark_completed(self, result: Any | None = None) -> None:
        """Mark task as successfully completed and release lease lock."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = time.time()
        self.result = result
        self.error = None
        self.locked_at = None
        self.locked_by = None

    def mark_failed(self, error: str) -> None:
        """Mark task as failed, increment retry count, and release lease lock."""
        self.retries += 1
        self.error = error
        self.locked_at = None
        self.locked_by = None
        if self.retries >= self.max_retries:
            self.status = TaskStatus.DEAD_LETTER
            self.completed_at = time.time()
        else:
            self.status = TaskStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to a JSON-compatible dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Deserialize task from a dictionary."""
        data_copy = dict(data)
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = TaskStatus(data_copy["status"])
        return cls(**data_copy)
