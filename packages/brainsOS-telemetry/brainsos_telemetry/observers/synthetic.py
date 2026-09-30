"""brainsos_telemetry observers.synthetic — Synthetic energy accounting observer."""

from __future__ import annotations

import logging

from brainsos_telemetry.events import TelemetryEvent

logger = logging.getLogger("brainsos_telemetry.synthetic")


class SyntheticEnergyObserver:
    """Observer that calculates synthetic energy consumption based on task duration and tokens.

    Formula:
        Energy (mJ) = (Duration ms * 25.0) + (Tokens * 80.0)
    """

    MS_COEFFICIENT: float = 25.0
    TOKEN_COEFFICIENT: float = 80.0

    def __init__(self) -> None:
        self._total_energy_millijoules: float = 0.0
        self._processed_events: list[TelemetryEvent] = []

    @property
    def total_energy_millijoules(self) -> float:
        """Return cumulative energy calculated across all observed events."""
        return self._total_energy_millijoules

    @property
    def processed_count(self) -> int:
        """Return count of processed events."""
        return len(self._processed_events)

    @classmethod
    def calculate_energy(cls, duration_ms: float = 0.0, tokens: int = 0) -> float:
        """Compute synthetic energy consumption in millijoules."""
        duration = max(0.0, float(duration_ms))
        toks = max(0, int(tokens))
        return (duration * cls.MS_COEFFICIENT) + (toks * cls.TOKEN_COEFFICIENT)

    def on_telemetry(self, event: TelemetryEvent) -> None:
        """Compute synthetic energy for completed/executed tasks and record metrics."""
        duration_ms = float(event.metadata.get("duration_ms", 0.0))
        tokens = int(
            event.metadata.get("tokens") or event.metadata.get("total_tokens") or event.metadata.get("token_count", 0)
        )

        computed_mj = self.calculate_energy(duration_ms=duration_ms, tokens=tokens)
        event.energy_millijoules = computed_mj
        self._total_energy_millijoules += computed_mj
        self._processed_events.append(event)
        logger.debug(
            "Computed synthetic energy for task '%s': %.2f mJ (duration=%.1f ms, tokens=%d)",
            event.task_id,
            computed_mj,
            duration_ms,
            tokens,
        )
