"""brainsos_telemetry events — Core telemetry models and event representations."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TelemetryEvent:
    """Represents an atomic telemetry, resource consumption, or lifecycle event.

    Attributes:
        task_id: Unique correlation identifier for the executed task.
        agent_id: Identifier of the autonomous agent executing the workload.
        event_type: Classification string (e.g. 'task_started', 'task_completed', 'task_failed').
        timestamp: Epoch timestamp (UTC float seconds) when the event occurred.
        energy_millijoules: Estimated or measured hardware energy in millijoules.
        thermal_celsius: Optional hardware temperature reading in degrees Celsius.
        metadata: Extensible key-value metadata (duration, token counts, error messages).
    """

    task_id: str
    agent_id: str
    event_type: str
    timestamp: float = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).timestamp())
    energy_millijoules: float = 0.0
    thermal_celsius: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
