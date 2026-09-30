"""brainsos_telemetry observable — TelemetryObserver protocol and TelemetryBus."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Coroutine
from typing import Any, Protocol, cast, runtime_checkable

from brainsos_telemetry.events import TelemetryEvent

logger = logging.getLogger("brainsos_telemetry")


@runtime_checkable
class TelemetryObserver(Protocol):
    """Protocol implemented by telemetry observers (energy, thermals, audit logging)."""

    def on_telemetry(self, event: TelemetryEvent) -> Any:
        """Handle telemetry event (can be synchronous or asynchronous)."""
        ...


class TelemetryBus:
    """Central decoupled observable event bus for telemetry and energy accounting."""

    def __init__(self) -> None:
        self._observers: list[TelemetryObserver] = []

    @property
    def observers(self) -> list[TelemetryObserver]:
        """Return a snapshot list of currently registered observers."""
        return list(self._observers)

    def attach(self, observer: TelemetryObserver) -> None:
        """Register an observer with the event bus."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: TelemetryObserver) -> None:
        """Unregister an observer from the event bus."""
        if observer in self._observers:
            self._observers.remove(observer)

    async def notify(self, event: TelemetryEvent) -> None:
        """Asynchronously dispatch a telemetry event to all attached observers."""
        for observer in list(self._observers):
            try:
                res = observer.on_telemetry(event)
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                logger.exception("Error in telemetry observer %r: %s", observer, e)

    def notify_sync(self, event: TelemetryEvent) -> None:
        """Synchronously dispatch a telemetry event to synchronous observers."""
        for observer in list(self._observers):
            try:
                res = observer.on_telemetry(event)
                if inspect.isawaitable(res):
                    coro = cast("Coroutine[Any, Any, Any]", res)
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(coro)
                    except RuntimeError:
                        asyncio.run(coro)
            except Exception as e:
                logger.exception("Error in sync telemetry observer %r: %s", observer, e)
