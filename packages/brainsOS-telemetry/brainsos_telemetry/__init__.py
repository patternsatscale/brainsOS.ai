"""brainsOS-telemetry — Decoupled Observer/Observable Telemetry & Synthetic Energy Accounting."""

from brainsos_telemetry.events import TelemetryEvent
from brainsos_telemetry.observable import TelemetryBus, TelemetryObserver
from brainsos_telemetry.observers.synthetic import SyntheticEnergyObserver
from brainsos_telemetry.system import create_system_api_app, get_system_status, stream_system_update

__version__ = "0.1.0"

__all__ = [
    "SyntheticEnergyObserver",
    "TelemetryBus",
    "TelemetryEvent",
    "TelemetryObserver",
    "create_system_api_app",
    "get_system_status",
    "stream_system_update",
]
