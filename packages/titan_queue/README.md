# Titan Work Queue (`titan-queue`)

Modular asynchronous FIFO work queue and concurrency manager designed for autonomous AI agent fleets in **Project Titan**.

## Overview

Inbound events (such as Dovecot Sieve push webhooks, cron jobs, git hooks, or background agent sub-tasks) must not trigger unconstrained, concurrent LLM reasoning turns.

Under Project Titan's hardware architecture (ASUS Ascent GX10 unified LPDDR5x memory bus and Apple Silicon workstations), inference bandwidth must be safeguarded. **Rule 3 (Hardware Serialization)** mandates serialized request scheduling (`max_parallel_requests: 1` or `2`).

`titan-queue` enforces execution serialization and decouples event ingestion from agent execution:

```text
Inbound Event (Webhook) ──► WorkQueue (FIFO) ──► FIFOQueueWorker (Concurrency Limiter) ──► Handler
```

## Features

- **Strict FIFO Ordering**: Guarantees First-In, First-Out queue consumption.
- **Hardware Serialization Guard**: Configurable concurrency pool (default: `concurrency=1`) preventing LLM inference thrashing and memory bus exhaustion (Rule 3).
- **Pluggable Backends**:
  - `MemoryQueueBackend`: Ultra-low-latency in-memory queue with event-driven wakeups (0 polling overhead).
  - `SQLiteQueueBackend`: Persistent crash-resilient queue storing data in container workspace or host volumes.
- **Memory Plane Purity (Rule 1)**: Programmatic safeguards guarantee queue state never pollutes `/memories`.
- **Fault Tolerance**: Automatic retries with exponential backoff and quarantine in `DEAD_LETTER` upon retry exhaustion.
- **Named Multi-Queue Architecture**: Global registry support for multiple domain-specific queues (`email_inbound`, `web_builder`, `maintenance`).

## Quickstart

```python
import asyncio
from titan_queue import WorkQueue, FIFOQueueWorker, Task

# 1. Initialize named queue
queue = WorkQueue("email_inbound")

# 2. Define async task handler
async def process_email(task: Task):
    print(f"Processing email task {task.id}: {task.payload['subject']}")
    # invoke agent reasoning or tool...
    return {"status": "replied"}

# 3. Start FIFO worker with concurrency=1 (Rule 3 compliant)
worker = FIFOQueueWorker(queue=queue, handler=process_email, concurrency=1)
worker.start()

# 4. Enqueue work asynchronously (e.g. from an HTTP webhook)
await queue.enqueue({"subject": "System status update", "from": "operator@titan.local"})
```
