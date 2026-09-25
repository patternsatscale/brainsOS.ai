"""titan-mail plugin — Project Titan Asynchronous Email Integration & Webhooks.

Provides native Hermes tools for sending, searching, and reading emails, along with
a reactive inbound push-webhook endpoint (/webhook) triggered by Dovecot Pigeonhole Sieve.
Zero polling, zero token waste, pure push-based doorbell wake-up.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .tools import (
    SEND_EMAIL_SCHEMA,
    SEARCH_EMAILS_SCHEMA,
    READ_EMAIL_SCHEMA,
    handle_send_email,
    handle_search_emails,
    handle_read_email,
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


async def _async_wake_agent(payload: Dict[str, Any]) -> None:
    """Handle inbound email webhook by logging and returning a generic 'hello!' message directly via SMTP."""
    agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"
    assigned_identity = os.getenv("AGENT_MAIL_USER") or f"{agent_id}@titan.local"

    from_addr = payload.get("from", "unknown")
    to_addr = payload.get("to", assigned_identity)
    subject = payload.get("subject", "No Subject")
    message_id = payload.get("message_id", "")
    in_reply_to = payload.get("in_reply_to", "")

    # 1. Log inbound email to /memories/logs if available (Rule 1 & Rule 12 compliant)
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
                )
    except Exception as e:
        logger.debug("Could not write inbound email audit log to memories: %s", e)

    # 2. Extract clean sender email
    clean_from = from_addr
    if "<" in from_addr and ">" in from_addr:
        import re
        m = re.search(r"<([^>]+)>", from_addr)
        if m:
            clean_from = m.group(1).strip()
    clean_from = clean_from.replace('"', '').strip()

    # Prevent loop / auto-replying to self or unknown sender
    if not clean_from or clean_from == "unknown" or clean_from.lower() == assigned_identity.lower():
        logger.info("Skipping generic reply to self or unknown sender: '%s'", clean_from)
        return

    # 3. Return a generic "hello!" reply directly via SMTP (no LLM proxy)
    reply_subj = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
    reply_body = (
        f"hello!\n\n"
        f"This is an automated response from {assigned_identity}.\n"
        f"Received your message: \"{subject}\".\n"
    )

    try:
        from titan_mail.client import TitanMailClient
        client = TitanMailClient.from_env()
        sent_id = client.send_mail(
            to=clean_from,
            subject=reply_subj,
            body=reply_body,
            from_addr=assigned_identity,
            in_reply_to=message_id or in_reply_to or None,
            references=message_id or in_reply_to or None,
        )
        logger.info("Dispatched generic 'hello!' reply from '%s' to '%s' (Message-ID: %s)", assigned_identity, clean_from, sent_id)
    except Exception as e:
        logger.error("Failed to dispatch generic 'hello!' email reply to '%s': %s", clean_from, e)


async def _handle_agent_email_webhook(req_self: Any, maybe_req: Any = None) -> Any:
    """Handle inbound POST /webhook from Dovecot Pigeonhole Sieve."""
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
        agent_id, from_addr, subject, message_id
    )

    # Spawn background response task without blocking Dovecot Sieve HTTP connection
    try:
        asyncio.create_task(_async_wake_agent(payload))
    except Exception as e:
        logger.warning("Failed to schedule background email response task: %s", e)

    return web.json_response({
        "status": "ok",
        "delivered": True,
        "agent": agent_id,
        "recipient": to_addr,
        "message_id": message_id,
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
            # Add POST /webhook to native route table bound to self_adapter
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
