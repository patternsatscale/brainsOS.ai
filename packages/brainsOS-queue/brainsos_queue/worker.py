"""brainsos_queue worker — FIFO Concurrency Manager & Task Processor."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional, Set

from brainsos_queue.models import Task, TaskStatus
from brainsos_queue.queue import WorkQueue

logger = logging.getLogger("brainsos_queue")


class FIFOQueueWorker:
    """Consumes tasks from a WorkQueue in FIFO order with strict concurrency limiting.

    Guarantees that hardware serialization constraints (Rule 3) are upheld by limiting
    concurrent task execution across autonomous agent fleets.
    """

    def __init__(
        self,
        queue: WorkQueue,
        handler: Callable[[Task], Awaitable[Any]],
        concurrency: int = 1,
        poll_interval: float = 0.05,
        backoff_base: float = 0.2,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"Concurrency must be at least 1, got {concurrency}")

        self.queue = queue
        self.handler = handler
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.backoff_base = backoff_base

        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._active_tasks: Set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        """Return True if worker is active."""
        return self._running

    @property
    def active_count(self) -> int:
        """Return number of currently executing task handlers."""
        return len(self._active_tasks)

    def start(self) -> asyncio.Task:
        """Start the background worker loop."""
        if self._running:
            return self._loop_task  # type: ignore

        self._running = True
        self._loop_task = asyncio.create_task(self._main_loop())
        logger.info(
            "Started FIFOQueueWorker for queue '%s' (concurrency=%d)",
            self.queue.name,
            self.concurrency,
        )
        return self._loop_task

    async def stop(self, drain: bool = False, timeout: float = 10.0) -> None:
        """Stop worker processing.

        Args:
            drain: If True, waits for remaining queued and active tasks to complete.
            timeout: Maximum seconds to wait during drain.
        """
        logger.info("Stopping FIFOQueueWorker for queue '%s' (drain=%s)", self.queue.name, drain)
        self._running = False

        if drain:
            deadline = time.time() + timeout
            while time.time() < deadline:
                pending_count = await self.queue.size(status=TaskStatus.QUEUED)
                if pending_count == 0 and len(self._active_tasks) == 0:
                    break
                # Dequeue remaining tasks if loop stopped
                task = await self.queue.dequeue()
                if task:
                    await self._semaphore.acquire()
                    t = asyncio.create_task(self._process_task(task))
                    self._active_tasks.add(t)
                    t.add_done_callback(self._active_tasks.discard)
                await asyncio.sleep(0.05)

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        # Wait for any in-flight active tasks up to timeout
        if self._active_tasks:
            await asyncio.wait(self._active_tasks, timeout=timeout)

    async def _main_loop(self) -> None:
        """Main dispatcher loop."""
        while self._running:
            try:
                # Wait for available concurrency slot before popping task
                await self._semaphore.acquire()

                task = await self.queue.dequeue()
                if not task:
                    self._semaphore.release()
                    # Wait for new items or sleep poll_interval
                    if hasattr(self.queue.backend, "wait_for_item"):
                        await self.queue.backend.wait_for_item(self.queue.name, timeout=self.poll_interval)
                    else:
                        await asyncio.sleep(self.poll_interval)
                    continue

                # Spawn task execution in background holding the acquired semaphore slot
                t = asyncio.create_task(self._process_task(task))
                self._active_tasks.add(t)
                t.add_done_callback(self._active_tasks.discard)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in queue worker dispatcher loop: %s", e)
                await asyncio.sleep(self.poll_interval)

    async def _process_task(self, task: Task) -> None:
        """Execute task handler with retries and status tracking."""
        try:
            logger.debug("Executing task %s on queue '%s'", task.id, task.queue)
            result = await self.handler(task)
            task.mark_completed(result=result)
            await self.queue.update_task(task)
            logger.info("Task %s completed successfully", task.id)
        except Exception as e:
            logger.warning("Task %s failed: %s", task.id, e)
            task.mark_failed(str(e))
            await self.queue.update_task(task)

            # If retries remain, back off before making task eligible for retry
            if task.status == TaskStatus.FAILED:
                backoff_delay = self.backoff_base * (2 ** (task.retries - 1))
                logger.info(
                    "Task %s will be retried (attempt %d/%d) after %.2fs backoff",
                    task.id,
                    task.retries,
                    task.max_retries,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)
                # Signal readiness for next pickup
                if hasattr(self.queue.backend, "_get_event"):
                    self.queue.backend._get_event(task.queue).set()
            else:
                logger.error("Task %s moved to DEAD_LETTER after %d retries", task.id, task.retries)
        finally:
            self._semaphore.release()
