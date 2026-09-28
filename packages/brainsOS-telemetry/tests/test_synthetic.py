"""Unit tests for SyntheticEnergyObserver."""

import pytest
from brainsos_telemetry.events import TelemetryEvent
from brainsos_telemetry.observable import TelemetryBus
from brainsos_telemetry.observers.synthetic import SyntheticEnergyObserver


def test_calculate_energy_formula():
    # Formula: (duration_ms * 25.0) + (tokens * 80.0)
    # 100 ms * 25 = 2500 mJ
    # 50 tokens * 80 = 4000 mJ
    # Total = 6500 mJ
    energy = SyntheticEnergyObserver.calculate_energy(duration_ms=100.0, tokens=50)
    assert energy == 6500.0

    # Zero values
    assert SyntheticEnergyObserver.calculate_energy(duration_ms=0, tokens=0) == 0.0

    # Negative protection
    assert SyntheticEnergyObserver.calculate_energy(duration_ms=-10, tokens=-5) == 0.0


def test_synthetic_energy_observer_on_telemetry():
    observer = SyntheticEnergyObserver()
    event = TelemetryEvent(
        task_id="task-calc-1",
        agent_id="marvin",
        event_type="task_completed",
        metadata={"duration_ms": 200.0, "tokens": 100},
    )

    observer.on_telemetry(event)

    # 200 * 25 = 5000; 100 * 80 = 8000; sum = 13000
    assert event.energy_millijoules == 13000.0
    assert observer.total_energy_millijoules == 13000.0
    assert observer.processed_count == 1

    # Second event
    event2 = TelemetryEvent(
        task_id="task-calc-2",
        agent_id="terrastella",
        event_type="task_completed",
        metadata={"duration_ms": 50.0, "tokens": 10},
    )
    # 50 * 25 = 1250; 10 * 80 = 800; sum = 2050
    observer.on_telemetry(event2)
    assert event2.energy_millijoules == 2050.0
    assert observer.total_energy_millijoules == 15050.0
    assert observer.processed_count == 2


@pytest.mark.asyncio
async def test_synthetic_observer_with_bus():
    bus = TelemetryBus()
    observer = SyntheticEnergyObserver()
    bus.attach(observer)

    event = TelemetryEvent(
        task_id="task-async-1",
        agent_id="bawtford",
        event_type="task_completed",
        metadata={"duration_ms": 10.0, "tokens": 5},
    )
    # 10 * 25 = 250; 5 * 80 = 400; sum = 650
    await bus.notify(event)

    assert event.energy_millijoules == 650.0
    assert observer.total_energy_millijoules == 650.0
