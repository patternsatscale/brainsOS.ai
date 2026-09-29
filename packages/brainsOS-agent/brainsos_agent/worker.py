"""brainsOS Unified Asynchronous Agent Queue Worker Daemon.

Consumes inbound email tasks from SQLite WorkQueue with thread-partition
concurrency locking and routes them through the warm stateless Hermes runner.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import signal
import sys
from typing import Any

from brainsos_mail.client import BrainsOSMailClient
from brainsos_mail.parser import parse_inbound_mime
from brainsos_queue import FIFOQueueWorker, Task, WorkQueue
from brainsos_agent.adapters import get_runtime_adapter
from brainsos_agent.models import AgentProfile

logger = logging.getLogger("brainsos_agent.worker")


class AgentQueueWorkerDaemon:
    """Daemon running FIFOQueueWorker hooked to dynamic runtime adapters."""

    def __init__(
        self,
        manifest_path: str | Path = "config/agents.yaml",
        queue_db_path: str | Path = "./data/queue/tasks.db",
        concurrency: int = 1,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.queue_db_path = Path(queue_db_path)
        self.concurrency = concurrency
        from brainsos_queue.backends.sqlite import SQLiteQueueBackend
        self.backend = SQLiteQueueBackend(db_path=str(self.queue_db_path))
        self.queue = WorkQueue("inbound_emails", backend=self.backend)
        self.worker: FIFOQueueWorker | None = None
        self._stop_event = asyncio.Event()

    def load_profiles(self) -> list[AgentProfile]:
        """Loads agent profiles from manifest."""
        if not self.manifest_path.exists():
            logger.warning("Manifest not found at %s", self.manifest_path)
            return []
        try:
            profiles = AgentProfile.from_manifest_yaml(self.manifest_path)
            return profiles if isinstance(profiles, list) else [profiles]
        except Exception as e:
            logger.error("Failed to load agent profiles from %s: %s", self.manifest_path, e)
            return []

    def find_profile_for_recipient(self, recipient: str, profiles: list[AgentProfile]) -> AgentProfile | None:
        """Finds matching active AgentProfile for recipient email address."""
        clean_recip = recipient.lower().strip()
        for p in profiles:
            if p.email.lower() == clean_recip or clean_recip.startswith(f"{p.id}@"):
                return p
        return None

    async def handle_task(self, task: Task) -> None:
        """Processes a single dequeued email task."""
        payload: dict[str, Any] = task.payload if isinstance(task.payload, dict) else {}
        raw_mime: bytes = b""

        # 1. Extract raw MIME bytes from payload or spool file path
        if "raw_mime" in payload:
            raw = payload["raw_mime"]
            raw_mime = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        elif "spool_path" in payload:
            spool_file = Path(payload["spool_path"])
            if spool_file.exists():
                raw_mime = spool_file.read_bytes()
            else:
                raise FileNotFoundError(f"Spool file not found: {spool_file}")
        elif "body" in payload and "sender" in payload:
            # Synthetic task fallback
            from email.message import EmailMessage
            em = EmailMessage()
            em["From"] = payload.get("sender", "unknown@brainsos.local")
            em["To"] = payload.get("recipient", "agent@brainsos.local")
            em["Subject"] = payload.get("subject", "Task Notification")
            em["Message-ID"] = payload.get("message_id", f"<{task.id}@brainsos.local>")
            em.set_content(payload.get("body", ""))
            raw_mime = em.as_bytes()
        else:
            raise ValueError(f"Task payload missing raw_mime or spool_path: {payload.keys()}")

        # 2. Parse MIME structure
        inbound_email = parse_inbound_mime(raw_mime)

        # 3. Resolve target AgentProfile from manifest
        profiles = self.load_profiles()
        profile = self.find_profile_for_recipient(inbound_email.recipient, profiles)
        if not profile:
            raise LookupError(
                f"No agent configured for recipient '{inbound_email.recipient}' in {self.manifest_path}"
            )

        logger.info(
            "Processing email thread '%s' for agent '%s' (%s)",
            inbound_email.thread_id,
            profile.name,
            profile.email,
        )

        # 4. Dispatch through matched runtime adapter (Hermes, AutoResponder, etc.)
        adapter = get_runtime_adapter(profile.runtime)
        outbound = await adapter.process_message(inbound_email, profile)

        # 5. Dual-dispatch reply via SMTP & IMAP Sent folder
        client = BrainsOSMailClient.from_env()
        # Set agent identity for sender
        client.username = profile.email
        client.send_mail(
            to=outbound.to,
            subject=outbound.subject,
            body=outbound.body,
            from_addr=profile.email,
            in_reply_to=outbound.in_reply_to,
            references=outbound.references,
            sync_imap=True,
        )
        logger.info(
            "Completed turn for thread '%s' - replied to '%s'",
            inbound_email.thread_id,
            outbound.to,
        )

    async def run(self) -> None:
        """Starts the queue worker loop."""
        self.worker = FIFOQueueWorker(
            queue=self.queue,
            handler=self.handle_task,
            concurrency=self.concurrency,
            poll_interval=0.5,
        )
        await self.worker.start()
        logger.info("AgentQueueWorkerDaemon started on queue '%s'", self.queue.name)
        await self._stop_event.wait()
        await self.worker.stop(drain=True)
        logger.info("AgentQueueWorkerDaemon stopped cleanly.")

    def stop(self) -> None:
        """Signals daemon to stop."""
        self._stop_event.set()


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    manifest = os.getenv("BRAINSOS_AGENTS_MANIFEST", "config/agents.yaml")
    db_path = os.getenv("BRAINSOS_QUEUE_DB", "./data/queue/tasks.db")
    concurrency = int(os.getenv("BRAINSOS_QUEUE_CONCURRENCY", "1"))

    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=db_path,
        concurrency=concurrency,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, daemon.stop)
        except NotImplementedError:
            pass

    await daemon.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
