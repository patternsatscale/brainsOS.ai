"""brainsos_queue sqlite backend — Persistent SQLite work queue backend."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from brainsos_queue.backends.base import QueueBackend
from brainsos_queue.models import Task, TaskStatus


class SQLiteQueueBackend(QueueBackend):
    """Persistent SQLite-backed work queue.

    Enforces Rule 1 (Memory Plane Purity): Database path must never be placed inside /memories.
    """

    def __init__(self, db_path: str = "/workspace/queue.db") -> None:
        # Enforce Rule 1 Memory Plane Purity
        resolved = Path(db_path).resolve()
        path_str = str(resolved)
        if "/memories" in path_str or "agent_memories" in path_str:
            raise ValueError(
                f"Rule 1 Invariant Violation: Queue database path '{db_path}' resides within /memories. "
                "Queue persistence files must reside in container workspace or host data paths."
            )

        self.db_path = str(resolved)
        # Ensure parent directory exists
        resolved.parent.mkdir(parents=True, exist_ok=True)

        self._lock = asyncio.Lock()
        self._notify_events: dict[str, asyncio.Event] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    queue TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    retries INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    error TEXT,
                    result TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_queue_status ON tasks(queue, status, created_at)")
            conn.commit()

    def _get_event(self, queue_name: str) -> asyncio.Event:
        if queue_name not in self._notify_events:
            self._notify_events[queue_name] = asyncio.Event()
        return self._notify_events[queue_name]

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            queue=row["queue"],
            payload=json.loads(row["payload"]),
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            retries=row["retries"],
            max_retries=row["max_retries"],
            error=row["error"],
            result=json.loads(row["result"]) if row["result"] is not None else None,
        )

    async def enqueue(self, task: Task) -> Task:
        async with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tasks (id, queue, payload, status, created_at, started_at, completed_at, retries, max_retries, error, result)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.id,
                        task.queue,
                        json.dumps(task.payload),
                        task.status.value,
                        task.created_at,
                        task.started_at,
                        task.completed_at,
                        task.retries,
                        task.max_retries,
                        task.error,
                        json.dumps(task.result) if task.result is not None else None,
                    ),
                )
                conn.commit()
            event = self._get_event(task.queue)
            event.set()
        return task

    async def dequeue(self, queue_name: str) -> Optional[Task]:
        async with self._lock:
            with self._get_connection() as conn:
                # Find oldest task with status 'queued' or 'failed' where retries < max_retries
                cursor = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE queue = ? AND status IN ('queued', 'failed') AND retries < max_retries
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (queue_name,),
                )
                row = cursor.fetchone()
                if not row:
                    event = self._get_event(queue_name)
                    event.clear()
                    return None

                task = self._row_to_task(row)
                task.mark_started()

                conn.execute(
                    "UPDATE tasks SET status = ?, started_at = ? WHERE id = ?",
                    (task.status.value, task.started_at, task.id),
                )
                conn.commit()
                return task

    async def peek(self, queue_name: str) -> Optional[Task]:
        async with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE queue = ? AND status IN ('queued', 'failed') AND retries < max_retries
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (queue_name,),
                )
                row = cursor.fetchone()
                return self._row_to_task(row) if row else None

    async def update_task(self, task: Task) -> Task:
        async with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE tasks SET
                        status = ?,
                        started_at = ?,
                        completed_at = ?,
                        retries = ?,
                        error = ?,
                        result = ?
                    WHERE id = ?
                    """,
                    (
                        task.status.value,
                        task.started_at,
                        task.completed_at,
                        task.retries,
                        task.error,
                        json.dumps(task.result) if task.result is not None else None,
                        task.id,
                    ),
                )
                conn.commit()
            if task.status in (TaskStatus.QUEUED, TaskStatus.FAILED):
                event = self._get_event(task.queue)
                event.set()
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                return self._row_to_task(row) if row else None

    async def size(self, queue_name: str, status: Optional[TaskStatus] = None) -> int:
        async with self._lock:
            with self._get_connection() as conn:
                if status is None:
                    cursor = conn.execute("SELECT COUNT(*) FROM tasks WHERE queue = ?", (queue_name,))
                else:
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE queue = ? AND status = ?",
                        (queue_name, status.value),
                    )
                return cursor.fetchone()[0]

    async def list_tasks(self, queue_name: str, status: Optional[TaskStatus] = None) -> List[Task]:
        async with self._lock:
            with self._get_connection() as conn:
                if status is None:
                    cursor = conn.execute("SELECT * FROM tasks WHERE queue = ? ORDER BY created_at ASC", (queue_name,))
                else:
                    cursor = conn.execute(
                        "SELECT * FROM tasks WHERE queue = ? AND status = ? ORDER BY created_at ASC",
                        (queue_name, status.value),
                    )
                return [self._row_to_task(r) for r in cursor.fetchall()]

    async def clear(self, queue_name: Optional[str] = None) -> None:
        async with self._lock:
            with self._get_connection() as conn:
                if queue_name is None:
                    conn.execute("DELETE FROM tasks")
                    for event in self._notify_events.values():
                        event.clear()
                else:
                    conn.execute("DELETE FROM tasks WHERE queue = ?", (queue_name,))
                    event = self._get_event(queue_name)
                    event.clear()
                conn.commit()

    async def wait_for_item(self, queue_name: str, timeout: Optional[float] = None) -> bool:
        event = self._get_event(queue_name)
        try:
            if timeout is not None:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            else:
                await event.wait()
            return True
        except asyncio.TimeoutError:
            return False
