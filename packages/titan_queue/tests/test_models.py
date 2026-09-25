"""Unit tests for titan_queue models."""

import pytest
from titan_queue.models import Task, TaskStatus


def test_task_creation_and_defaults():
    task = Task(queue="test_q", payload={"foo": "bar"})
    assert task.queue == "test_q"
    assert task.payload == {"foo": "bar"}
    assert task.status == TaskStatus.QUEUED
    assert task.retries == 0
    assert task.max_retries == 3
    assert task.id is not None
    assert task.created_at > 0
    assert task.started_at is None
    assert task.completed_at is None


def test_task_lifecycle_transitions():
    task = Task(queue="test_q", payload={"msg": "hello"}, max_retries=2)

    # 1. Start
    task.mark_started()
    assert task.status == TaskStatus.PROCESSING
    assert task.started_at is not None

    # 2. First failure (should transition to FAILED for retry)
    task.mark_failed("Temporary network error")
    assert task.status == TaskStatus.FAILED
    assert task.retries == 1
    assert task.error == "Temporary network error"

    # 3. Second failure (retries == max_retries -> DEAD_LETTER)
    task.mark_failed("Permanent failure")
    assert task.status == TaskStatus.DEAD_LETTER
    assert task.retries == 2
    assert task.error == "Permanent failure"
    assert task.completed_at is not None

    # 4. Successful completion
    task2 = Task(queue="test_q", payload={})
    task2.mark_started()
    task2.mark_completed(result={"ok": True})
    assert task2.status == TaskStatus.COMPLETED
    assert task2.result == {"ok": True}
    assert task2.completed_at is not None


def test_task_serialization_roundtrip():
    original = Task(
        queue="email_inbound",
        payload={"subject": "test", "id": 123},
        retries=1,
        status=TaskStatus.PROCESSING,
    )
    serialized = original.to_dict()
    assert serialized["queue"] == "email_inbound"
    assert serialized["status"] == "processing"

    restored = Task.from_dict(serialized)
    assert restored.id == original.id
    assert restored.queue == original.queue
    assert restored.payload == original.payload
    assert restored.status == TaskStatus.PROCESSING
    assert restored.retries == 1
