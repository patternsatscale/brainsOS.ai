"""brainsos_queue worker — FIFO Concurrency Manager & Task Processor."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

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
        telemetry_bus: Any | None = None,
        worker_id: str | None = None,
        lease_timeout_sec: float = 120.0,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"Concurrency must be at least 1, got {concurrency}")

        self.queue = queue
        self.handler = handler
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.backoff_base = backoff_base
        self.telemetry_bus = telemetry_bus
        self.worker_id = worker_id or f"worker-{id(self):x}"
        self.lease_timeout_sec = lease_timeout_sec

        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._active_tasks: set[asyncio.Task] = set()

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
                if hasattr(self.queue, "acquire_task"):
                    task = await self.queue.acquire_task(
                        worker_id=self.worker_id,
                        lease_timeout_sec=self.lease_timeout_sec,
                    )
                else:
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

                if hasattr(self.queue, "acquire_task"):
                    task = await self.queue.acquire_task(
                        worker_id=self.worker_id,
                        lease_timeout_sec=self.lease_timeout_sec,
                    )
                else:
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

    async def _emit_telemetry(
        self,
        event_type: str,
        task: Task,
        duration_ms: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit telemetry event to attached TelemetryBus if configured."""
        if not self.telemetry_bus:
            return
        try:
            agent_id = "unknown"
            tokens = 0
            if isinstance(task.payload, dict):
                agent_id = task.payload.get("agent_id") or task.payload.get("agent") or "unknown"
                tokens = int(task.payload.get("tokens") or task.payload.get("total_tokens") or 0)

            metadata: dict[str, Any] = {
                "queue": task.queue,
                "duration_ms": duration_ms,
                "tokens": tokens,
                "retries": task.retries,
            }
            if extra:
                metadata.update(extra)

            try:
                from brainsos_telemetry import TelemetryEvent

                event = TelemetryEvent(
                    task_id=task.id,
                    agent_id=agent_id,
                    event_type=event_type,
                    metadata=metadata,
                )
            except ImportError:

                class _EventStub:
                    def __init__(self, task_id: str, agent_id: str, event_type: str, metadata: dict[str, Any]):
                        self.task_id = task_id
                        self.agent_id = agent_id
                        self.event_type = event_type
                        self.metadata = metadata
                        self.energy_millijoules = 0.0
                        self.thermal_celsius = None

                event = _EventStub(task.id, agent_id, event_type, metadata)  # type: ignore

            res = self.telemetry_bus.notify(event)
            if inspect.isawaitable(res):
                await res
        except Exception as e:
            logger.debug("Failed to emit telemetry: %s", e)

    async def _process_task(self, task: Task) -> None:
        """Execute task handler with retries and status tracking."""
        start_perf = time.perf_counter()
        await self._emit_telemetry("task_started", task)
        try:
            logger.debug("Executing task %s on queue '%s'", task.id, task.queue)
            result = await self.handler(task)
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            task.mark_completed(result=result)
            await self.queue.update_task(task)
            await self._emit_telemetry("task_completed", task, duration_ms=duration_ms)
            logger.info("Task %s completed successfully", task.id)
        except Exception as e:
            duration_ms = (time.perf_counter() - start_perf) * 1000.0
            logger.warning("Task %s failed: %s", task.id, e)
            task.mark_failed(str(e))
            await self.queue.update_task(task)
            await self._emit_telemetry(
                "task_failed",
                task,
                duration_ms=duration_ms,
                extra={"error": str(e)},
            )

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
