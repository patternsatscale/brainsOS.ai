"""brainsOS Unified Asynchronous Agent Queue Worker Daemon.

Consumes inbound email tasks from SQLite WorkQueue with thread-partition
concurrency locking and routes them through the warm stateless Hermes runner
or deterministic auto-responder adapters.
Also hosts the high-performance non-blocking HTTP ingress receiver on port 8000
(POST /api/v1/mail/inbound) and provides zero-loss disk spool ingestion.
"""

from __future__ import annotations

import asyncio
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore
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

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from brainsos_agent.adapters import get_runtime_adapter
from brainsos_agent.config import get_comms_dir, get_control_plane_dir, get_data_dir
from brainsos_agent.models import AgentProfile

logger = logging.getLogger("brainsos_agent.worker")


class SingleInstanceLock:
    """Kernel-level file lock (fcntl.flock) ensuring a singleton daemon process.

    If another process holds the flock on lock_path, acquire() fails immediately
    with non-blocking semantics and identifies the active PID holding the lock.
    """

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path).resolve()
        self.file_handle: Any = None
        self._acquired = False

    def acquire(self) -> bool:
        """Attempts non-blocking exclusive lock acquisition. Returns True if acquired, False otherwise."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.file_handle = open(self.lock_path, "a+")
            if fcntl:
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.file_handle.seek(0)
            self.file_handle.truncate()
            self.file_handle.write(f"{os.getpid()}\n")
            self.file_handle.flush()
            self._acquired = True
            return True
        except (BlockingIOError, OSError):
            existing_pid = "unknown"
            try:
                if self.lock_path.exists():
                    existing_pid = self.lock_path.read_text(encoding="utf-8").strip() or "unknown"
            except Exception:
                pass
            logger.error(
                "CRITICAL: Another instance of AgentQueueWorkerDaemon is already running (PID: %s, lockfile: %s). Exiting.",
                existing_pid,
                self.lock_path,
            )
            if self.file_handle:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
            return False

    def release(self) -> None:
        """Releases the lock and removes the lockfile."""
        if not self._acquired:
            return
        if self.file_handle:
            try:
                if fcntl:
                    fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
                self.file_handle.close()
            except Exception:
                pass
            self.file_handle = None
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
        except Exception:
            pass
        self._acquired = False

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            sys.exit(1)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()



class AgentQueueWorkerDaemon:
    """Daemon running FIFOQueueWorker hooked to dynamic runtime adapters and HTTP mail ingress."""

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        queue_db_path: str | Path | None = None,
        concurrency: int = 1,
        ingress_host: str = "0.0.0.0",
        ingress_port: int = 8000,
        spool_dir: str | Path | None = None,
    ) -> None:
        from brainsos_agent.config import resolve_manifest_path

        self.manifest_path = resolve_manifest_path(manifest_path)
        self.queue_db_path = Path(queue_db_path) if queue_db_path else (get_data_dir() / "queue" / "tasks.db")
        self.concurrency = concurrency
        self.ingress_host = ingress_host
        self.ingress_port = ingress_port
        self.spool_dir = Path(spool_dir) if spool_dir else (get_comms_dir() / "spool")
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        from brainsos_queue.backends.sqlite import SQLiteQueueBackend

        self.backend = SQLiteQueueBackend(db_path=str(self.queue_db_path))
        self.queue = WorkQueue("inbound_emails", backend=self.backend)
        self.worker: FIFOQueueWorker | None = None
        self._stop_event = asyncio.Event()
        self._http_runner: web.AppRunner | None = None
        self._processed_spool_files: set[str] = set()
        self._processed_message_ids: set[str] = set()

        if self.spool_dir.exists():
            for done_file in self.spool_dir.glob("*.done"):
                self._processed_spool_files.add(done_file.with_suffix(".eml").name)

    def load_profiles(self) -> list[AgentProfile]:
        """Loads agent profiles from manifest."""
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

            # Parse MIME to extract thread_id, message_id, and recipient
            try:
                inbound_email = parse_inbound_mime(raw_mime)
                partition_key = inbound_email.thread_id
                recipient = inbound_email.recipient
                msg_id = inbound_email.message_id
            except Exception as pe:
                logger.warning("Failed to parse MIME headers for partition key: %s", pe)
                partition_key = "default"
                recipient = request.headers.get("X-Envelope-To", "unknown@brainsos.local")
                msg_id = None

            # Deduplication: check if message ID was already ingested recently
            if msg_id and msg_id in self._processed_message_ids:
                logger.info("Ignoring duplicate inbound email with Message-ID %s", msg_id)
                return web.json_response(
                    {
                        "status": "ignored",
                        "reason": "duplicate_message_id",
                        "message_id": msg_id,
                    }
                )

            # Check X-Spool-Filename header from agent-webhook.sh
            spool_filename = request.headers.get("X-Spool-Filename")
            if spool_filename:
                self._processed_spool_files.add(spool_filename)
                if (self.spool_dir / spool_filename).exists():
                    spool_file = self.spool_dir / spool_filename
                else:
                    spool_file = self.spool_dir / f"{time.time_ns()}.eml"
                    spool_file.write_bytes(raw_mime)
            else:
                spool_file = self.spool_dir / f"{time.time_ns()}.eml"
                spool_file.write_bytes(raw_mime)
            self._processed_spool_files.add(spool_file.name)

            if msg_id:
                self._processed_message_ids.add(msg_id)

            # Ignore non-agent deliveries (e.g. human user or system notifications)
            profiles = self.load_profiles()
            target_profile = self.find_profile_for_recipient(recipient, profiles)
            if not target_profile:
                logger.debug("Skipping inbound email for non-agent recipient '%s'", recipient)
                return web.json_response(
                    {
                        "status": "ignored",
                        "reason": "non_agent_recipient",
                        "recipient": recipient,
                    }
                )

            task = await self.queue.enqueue(
                payload={
                    "spool_path": str(spool_file),
                    "raw_mime": raw_mime.decode("utf-8", errors="replace"),
                    "recipient": recipient,
                    "message_id": msg_id,
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
            return web.json_response(
                {
                    "status": "enqueued",
                    "task_id": task.id,
                    "thread_id": partition_key,
                    "recipient": recipient,
                }
            )
        except Exception as e:
            logger.error("Ingress error processing inbound email: %s", e)
            return web.Response(status=500, text=f"Ingress error: {e}")

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint (GET /health/liveness)."""
        return web.json_response(
            {
                "status": "ok",
                "service": "brainsos-agent-worker",
                "queue": self.queue.name,
            }
        )

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
                            msg_id = inbound.message_id
                        except Exception as parse_err:
                            logger.warning("Spool scanner parse error on %s: %s", eml_file, parse_err)
                            partition_key = "default"
                            recipient = "unknown@brainsos.local"
                            msg_id = None

                        # Deduplication check against recently processed HTTP or scanner messages
                        if msg_id and msg_id in self._processed_message_ids:
                            self._processed_spool_files.add(eml_file.name)
                            try:
                                eml_file.with_suffix(".done").touch()
                            except Exception:
                                pass
                            continue

                        profiles = self.load_profiles()
                        if not self.find_profile_for_recipient(recipient, profiles):
                            self._processed_spool_files.add(eml_file.name)
                            continue

                        if msg_id:
                            self._processed_message_ids.add(msg_id)

                        task = await self.queue.enqueue(
                            payload={
                                "spool_path": str(eml_file),
                                "recipient": recipient,
                                "message_id": msg_id,
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
        agent_pass = (os.getenv(f"{profile.id.upper()}_MAIL_PASSWORD") if profile.id else None) or os.getenv(
            "AGENT_MAIL_PASSWORD"
        )
        if agent_pass:
            client.password = agent_pass

        # Determine appropriate From address:
        # Internal emails on dgx use @dgx.local.brainsos.ai; external destinations use configured public domain
        sender_email = profile.email
        to_domain = outbound.to.split("@")[-1].lower() if "@" in outbound.to else ""
        is_internal_dest = (
            to_domain.endswith(".local")
            or to_domain == "localhost"
            or "local.brainsos.ai" in to_domain
            or to_domain == "brainsos.local"
            or to_domain == os.getenv("BRAINSOS_DOMAIN", "").lower()
            or to_domain == os.getenv("BRAINSOS_MAIL_DOMAIN", "").lower()
        )
        is_external_dest = not is_internal_dest

        if "dgx.local.brainsos.ai" in to_domain or (
            os.getenv("BRAINSOS_DOMAIN") and "dgx.local.brainsos.ai" in os.getenv("BRAINSOS_DOMAIN", "")
        ):
            sender_email = f"{profile.id}@dgx.local.brainsos.ai"
        elif is_external_dest:
            configured_public_domain = (
                os.getenv("BRAINSOS_EMAIL_DOMAIN", "").split(",")[0].strip()
                or os.getenv("BRAINSOS_EXTERNAL_EMAIL_DOMAIN", "").split(",")[0].strip()
                or (f"{os.getenv('BRAINSOS_STAGE')}.public.brainsos.ai" if os.getenv("BRAINSOS_STAGE") else None)
            )
            if configured_public_domain and not configured_public_domain.endswith(".example.com"):
                sender_email = f"{profile.id}@{configured_public_domain}"
            elif inbound_email and "@" in inbound_email.recipient:
                inbound_dom = inbound_email.recipient.split("@")[-1].strip().lower()
                if not inbound_dom.endswith(".local") and not inbound_dom.startswith("local."):
                    sender_email = f"{profile.id}@{inbound_dom}"

        client.send_mail(
            to=outbound.to,
            subject=outbound.subject,
            body=outbound.body,
            from_addr=sender_email,
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

        if "message_id" in payload and payload["message_id"]:
            self._processed_message_ids.add(payload["message_id"])

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
        logger.info(
            "Mail Ingress HTTP endpoint listening on http://%s:%d/api/v1/mail/inbound",
            self.ingress_host,
            self.ingress_port,
        )

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
    manifest = os.getenv("BRAINSOS_AGENTS_MANIFEST")
    db_path = os.getenv("BRAINSOS_QUEUE_DB", str(get_data_dir() / "queue" / "tasks.db"))
    concurrency = int(os.getenv("BRAINSOS_QUEUE_CONCURRENCY", "1"))
    ingress_host = os.getenv("BRAINSOS_INGRESS_HOST", "0.0.0.0")
    ingress_port = int(os.getenv("BRAINSOS_INGRESS_PORT", "8000"))
    spool_dir = os.getenv("BRAINSOS_SPOOL_DIR", str(get_comms_dir() / "spool"))
    lock_path = os.getenv("BRAINSOS_QUEUE_LOCK_FILE", str(get_control_plane_dir() / "queue_worker.lock"))

    lock = SingleInstanceLock(lock_path)
    if not lock.acquire():
        sys.exit(1)

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

    try:
        await daemon.run()
    finally:
        lock.release()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except SystemExit as exc:
        sys.exit(exc.code)

