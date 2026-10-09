import os
from pathlib import Path

import pytest
from brainsos_agent.worker import SingleInstanceLock


def test_single_instance_lock_lifecycle(tmp_path: Path):
    lock_file = tmp_path / "test_worker.lock"
    lock1 = SingleInstanceLock(lock_file)

    # First acquisition succeeds
    assert lock1.acquire() is True
    assert lock_file.exists()
    assert lock_file.read_text().strip() == str(os.getpid())

    # Second acquisition on the same file fails immediately
    lock2 = SingleInstanceLock(lock_file)
    assert lock2.acquire() is False

    # Release first lock
    lock1.release()

    # Now second acquisition succeeds
    assert lock2.acquire() is True
    assert lock_file.exists()
    lock2.release()


def test_single_instance_lock_context_manager(tmp_path: Path):
    lock_file = tmp_path / "test_ctx.lock"

    with SingleInstanceLock(lock_file) as lock:
        assert lock_file.exists()
        # Nested attempt fails
        nested = SingleInstanceLock(lock_file)
        assert nested.acquire() is False

    # After context exit, lock is released and can be acquired again
    new_lock = SingleInstanceLock(lock_file)
    assert new_lock.acquire() is True
    new_lock.release()
