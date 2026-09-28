"""brainsos_mcp.modules.telemetry — Observable Telemetry and Energy capabilities."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_telemetry_tools(mcp: FastMCP) -> list[str]:
    """Register telemetry and energy accounting tools onto the FastMCP server."""
    from brainsos_telemetry import (
        SyntheticEnergyObserver,
        TelemetryBus,
        TelemetryEvent,
    )

    bus = TelemetryBus()
    energy_observer = SyntheticEnergyObserver()
    bus.attach(energy_observer)

    @mcp.tool()
    def get_energy_metrics(duration_ms: float = 0.0, tokens: int = 0) -> str:
        """Get energy metrics in mJ."""
        try:
            if duration_ms > 0 or tokens > 0:
                calc_mj = (duration_ms * 25.0) + (tokens * 80.0)
            else:
                calc_mj = energy_observer.total_energy_millijoules
            return json.dumps({
                "success": True,
                "energy_millijoules": calc_mj,
                "total_recorded_millijoules": energy_observer.total_energy_millijoules,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def emit_telemetry_event(event_type: str, task_id: str = "") -> str:
        """Emit telemetry event."""
        try:
            event = TelemetryEvent(
                task_id=task_id if task_id else "ad-hoc",
                agent_id=os.environ.get("BRAINSOS_AGENT_ID", "brainsos-agent"),
                event_type=event_type,
            )
            bus.notify_sync(event)
            return json.dumps({
                "success": True,
                "event_type": event.event_type,
                "task_id": event.task_id,
                "timestamp": event.timestamp,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return ["get_energy_metrics", "emit_telemetry_event"]
