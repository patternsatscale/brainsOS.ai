"""Unit tests for TelemetryBus and TelemetryObserver protocol."""

import pytest
from brainsos_telemetry.events import TelemetryEvent
from brainsos_telemetry.observable import TelemetryBus


class MockSyncObserver:
    def __init__(self):
        self.received = []

    def on_telemetry(self, event: TelemetryEvent):
        self.received.append(event)


class MockAsyncObserver:
    def __init__(self):
        self.received = []

    async def on_telemetry(self, event: TelemetryEvent):
        self.received.append(event)


class FailingObserver:
    def on_telemetry(self, event: TelemetryEvent):
        raise RuntimeError("Observer hardware failure")


def test_telemetry_bus_attach_detach():
    bus = TelemetryBus()
    obs1 = MockSyncObserver()
    obs2 = MockSyncObserver()

    assert len(bus.observers) == 0

    bus.attach(obs1)
    bus.attach(obs2)
    assert len(bus.observers) == 2
    assert obs1 in bus.observers
    assert obs2 in bus.observers

    # Idempotent attach
    bus.attach(obs1)
    assert len(bus.observers) == 2

    # Detach
    bus.detach(obs1)
    assert len(bus.observers) == 1
    assert obs1 not in bus.observers

    # Detach non-existent
    bus.detach(obs1)
    assert len(bus.observers) == 1


@pytest.mark.asyncio
async def test_telemetry_bus_notify_sync_and_async():
    bus = TelemetryBus()
    sync_obs = MockSyncObserver()
    async_obs = MockAsyncObserver()
    failing_obs = FailingObserver()

    bus.attach(sync_obs)
    bus.attach(async_obs)
    bus.attach(failing_obs)

    event = TelemetryEvent(
        task_id="task-456",
        agent_id="bawtford",
        event_type="task_completed",
        metadata={"duration_ms": 200.0},
    )

    # notify should succeed despite failing_obs
    await bus.notify(event)

    assert len(sync_obs.received) == 1
    assert sync_obs.received[0].task_id == "task-456"

    assert len(async_obs.received) == 1
    assert async_obs.received[0].task_id == "task-456"


def test_telemetry_bus_notify_sync():
    bus = TelemetryBus()
    sync_obs = MockSyncObserver()
    failing_obs = FailingObserver()

    bus.attach(sync_obs)
    bus.attach(failing_obs)

    event = TelemetryEvent(
        task_id="task-789",
        agent_id="terrastella",
        event_type="task_started",
    )

    bus.notify_sync(event)
    assert len(sync_obs.received) == 1
    assert sync_obs.received[0].task_id == "task-789"
