# brainsOS-telemetry

A lightweight, decoupled Observer/Observable telemetry, energy, and hardware thermals accounting library for **brainsOS** ([brainsOS.ai](https://brainsos.ai)).

---

## Architecture Overview

`brainsOS-telemetry` provides non-blocking, isolated event distribution for agent execution workloads and queue operations:

```text
┌───────────────────────────────┐
│   FIFOQueueWorker (Queue)     │
└──────────────┬────────────────┘
               │ Emits task_started, task_completed, task_failed
               ▼
┌───────────────────────────────┐
│        TelemetryBus           │
└──────┬─────────────────┬──────┘
       │                 │
       ▼                 ▼
┌────────────────┐ ┌───────────────────────────┐
│ SyntheticEnergy│ │ Custom Observers          │
│ Observer       │ │ (Langfuse, Thermals, CSV) │
└────────────────┘ └───────────────────────────┘
```

### Synthetic Energy Calculation
Computes estimated energy consumption for local inference and task dispatch:

$$\text{Energy (mJ)} = (\text{Duration ms} \times 25.0) + (\text{Tokens} \times 80.0)$$

---

## Usage Example

```python
import asyncio
from brainsos_telemetry import TelemetryBus, TelemetryEvent, SyntheticEnergyObserver

async def main():
    bus = TelemetryBus()
    energy_observer = SyntheticEnergyObserver()
    bus.attach(energy_observer)

    event = TelemetryEvent(
        task_id="task-123",
        agent_id="terrastella",
        event_type="task_completed",
        metadata={"duration_ms": 150.0, "tokens": 420},
    )

    await bus.notify(event)
    print(f"Energy: {event.energy_millijoules} mJ")

asyncio.run(main())
```
