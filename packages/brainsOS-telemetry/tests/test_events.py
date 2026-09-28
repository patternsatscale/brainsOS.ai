"""Unit tests for TelemetryEvent dataclass."""

import datetime

from brainsos_telemetry.events import TelemetryEvent


def test_telemetry_event_initialization():
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    event = TelemetryEvent(
        task_id="task-001",
        agent_id="terrastella",
        event_type="task_completed",
        timestamp=now,
        energy_millijoules=1250.5,
        thermal_celsius=42.0,
        metadata={"duration_ms": 100.0, "tokens": 15},
    )

    assert event.task_id == "task-001"
    assert event.agent_id == "terrastella"
    assert event.event_type == "task_completed"
    assert event.timestamp == now
    assert event.energy_millijoules == 1250.5
    assert event.thermal_celsius == 42.0
    assert event.metadata["duration_ms"] == 100.0
    assert event.metadata["tokens"] == 15


def test_telemetry_event_defaults():
    event = TelemetryEvent(
        task_id="task-002",
        agent_id="marvin",
        event_type="task_started",
    )

    assert event.task_id == "task-002"
    assert event.agent_id == "marvin"
    assert event.event_type == "task_started"
    assert isinstance(event.timestamp, float)
    assert event.energy_millijoules == 0.0
    assert event.thermal_celsius is None
    assert event.metadata == {}
