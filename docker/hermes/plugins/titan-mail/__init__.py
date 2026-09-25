"""titan-mail plugin — Project Titan Asynchronous Email Integration & Webhooks.

Provides native Hermes tools for sending, searching, and reading emails, along with
a reactive inbound push-webhook endpoint (/webhook) backed by titan_queue.
Features dual FIFO queues:
1. Fast Response Queue (Queue A): Dispatches instant acknowledgements and triage warnings
   when the agent is engaged in long-running workloads (DGX hardware concurrency guard).
2. Workload Queue (Queue B): Serializes heavy agent reasoning and execution tasks
   with strict concurrency=1 (Rule 3).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional
import uuid

from titan_mail.calendar import generate_ics_event, write_ics_file
from titan_mail.client import TitanMailClient
from titan_queue import (
    FIFOQueueWorker,
    MemoryQueueBackend,
    QueueBackend,
    SQLiteQueueBackend,
    Task,
    TaskStatus,
    WorkQueue,
    get_queue,
)

from .tools import (
    READ_EMAIL_SCHEMA,
    SEARCH_EMAILS_SCHEMA,
    SEND_EMAIL_SCHEMA,
    handle_read_email,
    handle_search_emails,
    handle_send_email,
)

logger = logging.getLogger("titan-mail")

__all__ = ["register"]

_TOOLS = (
    (
        "send_email",
        SEND_EMAIL_SCHEMA,
        handle_send_email,
        "✉️",
        "Compose and send an email via Titan mail server with sender verification and RFC threading",
    ),
    (
        "search_emails",
        SEARCH_EMAILS_SCHEMA,
        handle_search_emails,
        "🔍",
        "Search personal or shared emails matching keywords, subject, sender, or date criteria",
    ),
    (
        "read_email",
        READ_EMAIL_SCHEMA,
        handle_read_email,
        "📖",
        "Retrieve the full message content and RFC headers of a specific email by Message-ID or seq num",
    ),
)

# Global queue and worker references per agent container
_FAST_QUEUE: Optional[WorkQueue] = None
_WORKLOAD_QUEUE: Optional[WorkQueue] = None
_FAST_WORKER: Optional[FIFOQueueWorker] = None
_WORKLOAD_WORKER: Optional[FIFOQueueWorker] = None
_INITIALIZED: bool = False
_INIT_LOCK = asyncio.Lock()


def _clean_email(addr: str) -> str:
    """Extract clean email address from string (e.g. 'Operator <op@titan.local>' -> 'op@titan.local')."""
    if not addr:
        return "unknown"
    if "<" in addr and ">" in addr:
        m = re.search(r"<([^>]+)>", addr)
        if m:
            addr = m.group(1).strip()
    return addr.replace('"', "").replace("'", "").strip()


def _get_queue_backend() -> QueueBackend:
    """Initialize a safe QueueBackend enforcing Rule 1 Memory Plane Purity."""
    db_path = os.getenv("TITAN_QUEUE_DB_PATH")
    if db_path:
        try:
            return SQLiteQueueBackend(db_path)
        except Exception as e:
            logger.warning("Failed to initialize SQLite backend at '%s': %s", db_path, e)

    # Search for writable non-memories workspace directories
    candidate_paths = [
        "/workspace/queue.db",
        "/opt/data/queue.db",
        "./data/agent_workspaces/queue.db",
    ]
    for cand in candidate_paths:
        try:
            p = Path(cand).resolve()
            # Rule 1 Invariant: Never allow queue database inside /memories
            if "/memories" in str(p) or "agent_memories" in str(p):
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            return SQLiteQueueBackend(str(p))
        except Exception:
            continue

    logger.info("Using MemoryQueueBackend for agent queues.")
    return MemoryQueueBackend()


async def _handle_fast_response_task(task: Task) -> Dict[str, Any]:
    """Process an item on the Fast Response Queue (Queue A).

    Logs inbound notification to memories and dispatches a fast acknowledgment
    with workload status (informing sender if a long-running workload is active).
    """
    payload = task.payload
    agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"
    assigned_identity = os.getenv("AGENT_MAIL_USER") or f"{agent_id}@titan.local"

    from_addr = payload.get("from", "unknown")
    to_addr = payload.get("to", assigned_identity)
    subject = payload.get("subject", "No Subject")
    message_id = payload.get("message_id", "")
    in_reply_to = payload.get("in_reply_to", "")
    workload_task_id = payload.get("workload_task_id", task.id)

    # 1. Log inbound email to /memories/logs (Rule 1 & Rule 12 compliant)
    mem_dir = os.getenv("MEMORY_DIR", "/memories")
    try:
        log_dir = Path(mem_dir) / "logs"
        if log_dir.exists() or Path(mem_dir).exists():
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "email_inbound.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"\n### Inbound Email: {subject}\n"
                    f"- **Timestamp**: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
                    f"- **From**: `{from_addr}`\n"
                    f"- **To**: `{to_addr}`\n"
                    f"- **Subject**: {subject}\n"
                    f"- **Message-ID**: `{message_id}`\n"
                    f"- **In-Reply-To**: `{in_reply_to}`\n"
                    f"- **Task ID**: `{workload_task_id}`\n"
                )
    except Exception as e:
        logger.debug("Could not write inbound email audit log to memories: %s", e)

    clean_from = _clean_email(from_addr)
    # Prevent mail loops or replying to self/unknown
    if not clean_from or clean_from == "unknown" or clean_from.lower() == assigned_identity.lower():
        logger.info("Skipping fast reply to self or unknown sender: '%s'", clean_from)
        return {"status": "skipped", "reason": "self_or_unknown"}

    # 2. Check if workload worker is currently busy
    is_busy = False
    if _WORKLOAD_WORKER and _WORKLOAD_WORKER.active_count > 0:
        is_busy = True
    elif _WORKLOAD_QUEUE:
        pending_workloads = await _WORKLOAD_QUEUE.size(status=TaskStatus.QUEUED)
        if pending_workloads > 1:
            is_busy = True

    reply_subj = f"Re: {subject}" if not subject.lower().startswith("re:") else subject

    if is_busy:
        reply_body = (
            f"hello!\n\n"
            f"This is an automated response from {assigned_identity}.\n"
            f"Received your message: \"{subject}\".\n\n"
            f"The agent is currently executing an active workload on the hardware cluster. "
            f"Your request has been queued in the workload pipeline (Task ID: {workload_task_id}) "
            f"and will be processed once preceding tasks finish.\n"
        )
    else:
        reply_body = (
            f"hello!\n\n"
            f"This is an automated response from {assigned_identity}.\n"
            f"Received your message: \"{subject}\".\n\n"
            f"Your request has been received and queued for execution (Task ID: {workload_task_id}).\n"
        )

    try:
        client = TitanMailClient.from_env()
        sent_id = client.send_mail(
            to=clean_from,
            subject=reply_subj,
            body=reply_body,
            from_addr=assigned_identity,
            in_reply_to=message_id or in_reply_to or None,
            references=message_id or in_reply_to or None,
        )
        logger.info(
            "Dispatched fast acknowledgment reply from '%s' to '%s' (Message-ID: %s, Busy: %s)",
            assigned_identity,
            clean_from,
            sent_id,
            is_busy,
        )
        return {"status": "dispatched", "message_id": sent_id, "busy": is_busy}
    except Exception as e:
        logger.error("Failed to dispatch fast email reply to '%s': %s", clean_from, e)
        raise


async def _handle_workload_task(task: Task) -> Dict[str, Any]:
    """Process an item on the Workload Queue (Queue B) with strict concurrency=1.

    Serializes agent execution, records start/end times, captures execution metadata,
    generates RFC 5545 calendar event data, and logs to memories.
    """
    start_time = time.time()
    payload = task.payload
    agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"
    assigned_identity = os.getenv("AGENT_MAIL_USER") or f"{agent_id}@titan.local"

    from_addr = payload.get("from", "unknown")
    subject = payload.get("subject", "No Subject")
    message_id = payload.get("message_id", "")

    logger.info("Executing workload task %s for subject '%s'", task.id, subject)

    # In current phase, workload execution is scripted; LLM reasoning will be wired in future ticket.
    # Yield control to simulate workload step
    await asyncio.sleep(0.01)

    end_time = time.time()
    duration_sec = round(end_time - start_time, 2)
    clean_from = _clean_email(from_addr)

    # 1. Generate RFC 5545 Calendar (ICS) Event
    try:
        ics_content = generate_ics_event(
            summary=f"[Workload] {subject}",
            start_time=start_time,
            end_time=end_time + 900.0,  # 15-minute slot on calendar
            description=(
                f"Automated agent workload execution for directive: {subject}\n"
                f"From: {from_addr}\n"
                f"Message-ID: {message_id}\n"
                f"Task ID: {task.id}\n"
                f"Duration: {duration_sec}s"
            ),
            uid=f"task-{task.id}@titan.local",
            organizer=assigned_identity,
            attendee=clean_from if clean_from != "unknown" else None,
            status="CONFIRMED",
        )

        # Store ICS file in workspace calendar directory (Rule 1 compliant)
        calendar_candidates = [
            Path("/workspace/calendar"),
            Path("/opt/data/calendar"),
            Path(f"./data/agent_workspaces/{agent_id}/calendar"),
        ]
        for cal_dir in calendar_candidates:
            try:
                dest = cal_dir / f"{task.id}.ics"
                if "/memories" not in str(dest.resolve()):
                    write_ics_file(dest, ics_content)
                    break
            except Exception:
                continue
    except Exception as e:
        logger.debug("Could not generate calendar ICS event: %s", e)

    # 2. Record workload execution to /memories/logs/email_workload.md (Rule 1 OKF Markdown)
    mem_dir = os.getenv("MEMORY_DIR", "/memories")
    try:
        log_dir = Path(mem_dir) / "logs"
        if log_dir.exists() or Path(mem_dir).exists():
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "email_workload.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"\n### Workload Completed: {subject}\n"
                    f"- **Task ID**: `{task.id}`\n"
                    f"- **Timestamp**: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
                    f"- **Duration**: {duration_sec}s\n"
                    f"- **From**: `{from_addr}`\n"
                    f"- **Subject**: {subject}\n"
                    f"- **Message-ID**: `{message_id}`\n"
                    f"- **Status**: Completed\n"
                )
    except Exception as e:
        logger.debug("Could not write workload audit log to memories: %s", e)

    logger.info("Workload task %s completed in %.2fs", task.id, duration_sec)
    return {
        "status": "completed",
        "task_id": task.id,
        "subject": subject,
        "duration": duration_sec,
    }


async def _ensure_queues_and_workers() -> None:
    """Idempotently initialize and start agent Fast Response and Workload queue workers."""
    global _FAST_QUEUE, _WORKLOAD_QUEUE, _FAST_WORKER, _WORKLOAD_WORKER, _INITIALIZED

    if _INITIALIZED:
        return

    async with _INIT_LOCK:
        if _INITIALIZED:
            return

        agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"
        backend = _get_queue_backend()

        _FAST_QUEUE = get_queue(f"{agent_id}_fast_response", backend=backend)
        _WORKLOAD_QUEUE = get_queue(f"{agent_id}_workload", backend=backend)

        # Worker A: Fast acknowledgment dispatcher
        _FAST_WORKER = FIFOQueueWorker(
            queue=_FAST_QUEUE,
            handler=_handle_fast_response_task,
            concurrency=1,
            poll_interval=0.05,
        )
        _FAST_WORKER.start()

        # Worker B: Serialized workload executor (Rule 3 Hardware Serialization)
        _WORKLOAD_WORKER = FIFOQueueWorker(
            queue=_WORKLOAD_QUEUE,
            handler=_handle_workload_task,
            concurrency=1,
            poll_interval=0.05,
        )
        _WORKLOAD_WORKER.start()

        _INITIALIZED = True
        logger.info("Initialized dual queue workers for agent '%s'", agent_id)


async def _handle_agent_email_webhook(req_self: Any, maybe_req: Any = None) -> Any:
    """Handle inbound POST /webhook from Dovecot Pigeonhole Sieve.

    Pushes the email into the dual-queue architecture (Fast Response + Serialized Workload)
    and immediately returns HTTP 200 OK without blocking LMTP delivery.
    """
    try:
        from aiohttp import web
    except ImportError:
        return None

    request = maybe_req if maybe_req is not None else req_self
    adapter = req_self if maybe_req is not None else (
        request.app.get("api_server_adapter") if hasattr(request, "app") and hasattr(request.app, "get") else None
    )

    # Enforce API server authentication if running under APIServerAdapter
    if adapter and hasattr(adapter, "_check_auth"):
        auth_err = adapter._check_auth(request)
        if auth_err:
            return auth_err

    try:
        payload = await request.json()
    except Exception:
        try:
            raw_text = await request.text()
            payload = json.loads(raw_text) if raw_text else {}
        except Exception:
            payload = {}

    to_addr = payload.get("to", "")
    from_addr = payload.get("from", "")
    subject = payload.get("subject", "")
    message_id = payload.get("message_id", "")
    agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"

    logger.info(
        "Received inbound email webhook for agent '%s' (From: %s, Subject: %s, Message-ID: %s)",
        agent_id,
        from_addr,
        subject,
        message_id,
    )

    # Initialize queues and workers
    await _ensure_queues_and_workers()

    # Create unified task ID linking fast response and workload
    task_id = str(uuid.uuid4())
    queue_payload = dict(payload)
    queue_payload["workload_task_id"] = task_id

    # Enqueue to Queue A (Fast Response) and Queue B (Workload)
    if _FAST_QUEUE:
        await _FAST_QUEUE.enqueue(queue_payload, task_id=f"fast-{task_id}")
    if _WORKLOAD_QUEUE:
        await _WORKLOAD_QUEUE.enqueue(queue_payload, task_id=task_id)

    return web.json_response({
        "status": "ok",
        "delivered": True,
        "queued": True,
        "task_id": task_id,
        "agent": agent_id,
        "recipient": to_addr,
        "message_id": message_id,
        "fast_queue": True,
        "workload_queue": True,
    })


def _patch_api_server_routes() -> None:
    """Inject the /webhook route into APIServerAdapter._http_route_table."""
    try:
        from gateway.platforms.api_server import APIServerAdapter
        if getattr(APIServerAdapter, "_titan_webhook_patched", False):
            return

        orig_route_table = APIServerAdapter._http_route_table

        def patched_route_table(self_adapter: Any) -> list:
            routes = orig_route_table(self_adapter)

            async def _webhook_handler(request: Any) -> Any:
                return await _handle_agent_email_webhook(self_adapter, request)

            routes.append(("POST", "/webhook", _webhook_handler))
            return routes

        APIServerAdapter._http_route_table = patched_route_table
        APIServerAdapter._titan_webhook_patched = True
        logger.info("Successfully registered POST /webhook in APIServerAdapter route table.")
    except Exception as e:
        logger.debug("Could not patch APIServerAdapter for /webhook: %s", e)


# Run patch immediately upon import
_patch_api_server_routes()


def register(ctx: Any) -> None:
    """Register tools with Hermes Agent plugin loader."""
    logger.info("Registering titan-mail plugin tools...")
    for name, schema, handler, emoji, desc in _TOOLS:
        try:
            ctx.register_tool(
                name=name,
                toolset="project",
                schema=schema,
                handler=handler,
                description=desc,
                emoji=emoji,
            )
            logger.info("Registered tool: %s (%s)", name, emoji)
        except Exception as e:
            logger.warning("Failed to register tool %s: %s", name, e)

    # Ensure APIServerAdapter route is active
    _patch_api_server_routes()
