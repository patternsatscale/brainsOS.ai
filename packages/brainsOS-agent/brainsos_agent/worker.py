"""brainsOS Unified Asynchronous Agent Queue Worker Daemon.

Consumes inbound email tasks from SQLite WorkQueue with thread-partition
concurrency locking and routes them through the warm stateless Hermes runner
or deterministic auto-responder adapters.
Also hosts the high-performance non-blocking HTTP ingress receiver on port 8000
(POST /api/v1/mail/inbound) and provides zero-loss disk spool ingestion.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from brainsos_mail.client import BrainsOSMailClient
from brainsos_mail.parser import parse_inbound_mime
from brainsos_queue import FIFOQueueWorker, Task, WorkQueue

from brainsos_agent.adapters import get_runtime_adapter
from brainsos_agent.models import AgentProfile

logger = logging.getLogger("brainsos_agent.worker")


class AgentQueueWorkerDaemon:
    """Daemon running FIFOQueueWorker hooked to dynamic runtime adapters and HTTP mail ingress."""

    def __init__(
        self,
        manifest_path: str | Path = "config/agents.yaml",
        queue_db_path: str | Path = "./data/queue/tasks.db",
        concurrency: int = 1,
        ingress_host: str = "0.0.0.0",
        ingress_port: int = 8000,
        spool_dir: str | Path = "./data/comms/spool",
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.queue_db_path = Path(queue_db_path)
        self.concurrency = concurrency
        self.ingress_host = ingress_host
        self.ingress_port = ingress_port
        self.spool_dir = Path(spool_dir)
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        from brainsos_queue.backends.sqlite import SQLiteQueueBackend
        self.backend = SQLiteQueueBackend(db_path=str(self.queue_db_path))
        self.queue = WorkQueue("inbound_emails", backend=self.backend)
        self.worker: FIFOQueueWorker | None = None
        self._stop_event = asyncio.Event()
        self._http_runner: web.AppRunner | None = None
        self._processed_spool_files: set[str] = set()

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
        from email.utils import parseaddr
        _, clean_addr = parseaddr(recipient)
        clean_recip = (clean_addr or recipient).lower().strip()
        for p in profiles:
            p_email = p.email.lower()
            if (
                p_email == clean_recip
                or clean_recip.startswith(f"{p.id}@")
                or f"<{p_email}>" in recipient.lower()
                or f"{p.id}@" in recipient.lower()
            ):
                return p
        return None

    async def handle_inbound_http(self, request: web.Request) -> web.Response:
        """HTTP endpoint receiving streamed raw RFC 822 emails (POST /api/v1/mail/inbound)."""
        try:
            raw_mime = await request.read()
            if not raw_mime:
                return web.Response(status=400, text="Empty RFC 822 payload")

            # High-resolution spool file
            spool_file = self.spool_dir / f"{time.time_ns()}.eml"
            spool_file.write_bytes(raw_mime)
            self._processed_spool_files.add(spool_file.name)

            # Parse MIME to extract thread_id and recipient
            try:
                inbound_email = parse_inbound_mime(raw_mime)
                partition_key = inbound_email.thread_id
                recipient = inbound_email.recipient
            except Exception as pe:
                logger.warning("Failed to parse MIME headers for partition key: %s", pe)
                partition_key = "default"
                recipient = request.headers.get("X-Envelope-To", "unknown@brainsos.local")

            # Ignore non-agent deliveries (e.g. human user or system notifications)
            profiles = self.load_profiles()
            target_profile = self.find_profile_for_recipient(recipient, profiles)
            if not target_profile:
                logger.debug("Skipping inbound email for non-agent recipient '%s'", recipient)
                return web.json_response({
                    "status": "ignored",
                    "reason": "non_agent_recipient",
                    "recipient": recipient,
                })

            task = await self.queue.enqueue(
                payload={
                    "spool_path": str(spool_file),
                    "recipient": recipient,
                },
                partition_key=partition_key,
            )
            logger.info(
                "Ingested inbound email task %s for '%s' (%s, partition: %s)",
                task.id,
                target_profile.name,
                recipient,
                partition_key,
            )
            return web.json_response({
                "status": "enqueued",
                "task_id": task.id,
                "thread_id": partition_key,
                "recipient": recipient,
            })
        except Exception as e:
            logger.error("Ingress error processing inbound email: %s", e)
            return web.Response(status=500, text=f"Ingress error: {e}")

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint (GET /health/liveness)."""
        return web.json_response({
            "status": "ok",
            "service": "brainsos-agent-worker",
            "queue": self.queue.name,
        })

    async def _spool_scanner_loop(self) -> None:
        """Background fallback scanner ingesting spooled .eml files not received via HTTP."""
        while not self._stop_event.is_set():
            try:
                if self.spool_dir.exists():
                    for eml_file in sorted(self.spool_dir.glob("*.eml")):
                        if eml_file.name in self._processed_spool_files:
                            continue
                        done_marker = eml_file.with_suffix(".done")
                        if done_marker.exists():
                            self._processed_spool_files.add(eml_file.name)
                            continue

                        try:
                            raw_mime = eml_file.read_bytes()
                            inbound = parse_inbound_mime(raw_mime)
                            partition_key = inbound.thread_id
                            recipient = inbound.recipient
                        except Exception as parse_err:
                            logger.warning("Spool scanner parse error on %s: %s", eml_file, parse_err)
                            partition_key = "default"
                            recipient = "unknown@brainsos.local"

                        profiles = self.load_profiles()
                        if not self.find_profile_for_recipient(recipient, profiles):
                            self._processed_spool_files.add(eml_file.name)
                            continue

                        task = await self.queue.enqueue(
                            payload={
                                "spool_path": str(eml_file),
                                "recipient": recipient,
                            },
                            partition_key=partition_key,
                        )
                        self._processed_spool_files.add(eml_file.name)
                        logger.info("Spool scanner enqueued pending email %s as task %s", eml_file.name, task.id)
            except Exception as e:
                logger.error("Error in spool scanner loop: %s", e)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def handle_task(self, task: Task) -> None:
        """Processes a single dequeued email task."""
        payload: dict[str, Any] = task.payload if isinstance(task.payload, dict) else {}
        raw_mime: bytes = b""
        spool_file: Path | None = None

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
            logger.info("Ignoring task for non-agent recipient '%s'", inbound_email.recipient)
            if spool_file and spool_file.exists():
                try:
                    spool_file.with_suffix(".done").touch()
                    self._processed_spool_files.add(spool_file.name)
                except Exception:
                    pass
            return

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
        # Resolve password for specific agent from environment
        agent_pass = (
            os.getenv(f"{profile.id.upper()}_MAIL_PASSWORD")
            if profile.id
            else None
        ) or os.getenv("AGENT_MAIL_PASSWORD")
        if agent_pass:
            client.password = agent_pass

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

        # Mark spool file as completed if present
        if spool_file and spool_file.exists():
            try:
                done_marker = spool_file.with_suffix(".done")
                done_marker.touch()
                self._processed_spool_files.add(spool_file.name)
            except Exception:
                pass

    async def run(self) -> None:
        """Starts the queue worker loop and HTTP ingress server."""
        self.worker = FIFOQueueWorker(
            queue=self.queue,
            handler=self.handle_task,
            concurrency=self.concurrency,
            poll_interval=0.5,
        )
        self.worker.start()
        logger.info("AgentQueueWorkerDaemon started on queue '%s'", self.queue.name)

        # Start HTTP Ingress Server
        app = web.Application()
        app.router.add_post("/api/v1/mail/inbound", self.handle_inbound_http)
        app.router.add_get("/health/liveness", self.handle_health)
        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, host=self.ingress_host, port=self.ingress_port)
        await site.start()
        logger.info("Mail Ingress HTTP endpoint listening on http://%s:%d/api/v1/mail/inbound", self.ingress_host, self.ingress_port)

        # Start spool scanner loop
        scanner_task = asyncio.create_task(self._spool_scanner_loop())

        await self._stop_event.wait()

        # Shutdown gracefully
        scanner_task.cancel()
        try:
            await scanner_task
        except asyncio.CancelledError:
            pass

        if self._http_runner:
            await self._http_runner.cleanup()
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
    ingress_host = os.getenv("BRAINSOS_INGRESS_HOST", "0.0.0.0")
    ingress_port = int(os.getenv("BRAINSOS_INGRESS_PORT", "8000"))
    spool_dir = os.getenv("BRAINSOS_SPOOL_DIR", "./data/comms/spool")

    daemon = AgentQueueWorkerDaemon(
        manifest_path=manifest,
        queue_db_path=db_path,
        concurrency=concurrency,
        ingress_host=ingress_host,
        ingress_port=ingress_port,
        spool_dir=spool_dir,
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
