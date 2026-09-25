"""Project Titan Mail Hermes Plugin Tools.

Provides native model tools for autonomous agents to send emails with sender verification,
search inbox messages, and read specific email threads.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from titan_mail.client import TitanMailClient

logger = logging.getLogger("titan-mail")

SEND_EMAIL_SCHEMA: Dict[str, Any] = {
    "name": "send_email",
    "description": (
        "Compose and dispatch an RFC-compliant email message via the internal Titan mail server. "
        "Enforces sender identity verification so agents can only send from their assigned @titan.local address. "
        "Supports RFC 5322 threading headers (in_reply_to, references) to maintain conversation threads."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address (e.g., 'operator@titan.local' or peer agent).",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Plaintext email message body.",
            },
            "in_reply_to": {
                "type": "string",
                "description": "Message-ID being replied to (e.g., '<msg-uuid@titan.local>'), linking this reply to a thread.",
            },
            "references": {
                "type": "string",
                "description": "RFC references header specifying parent or thread Message-IDs.",
            },
        },
        "required": ["to", "subject", "body"],
    },
}

SEARCH_EMAILS_SCHEMA: Dict[str, Any] = {
    "name": "search_emails",
    "description": (
        "Search emails in the agent mailbox using keyword, subject, sender, date, or read status filters. "
        "Executes RFC 3501 IMAP SEARCH queries without CPU-heavy continuous polling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to search within message bodies.",
            },
            "subject": {
                "type": "string",
                "description": "Keyword to filter by subject line.",
            },
            "from_addr": {
                "type": "string",
                "description": "Sender email address to filter by.",
            },
            "since_date": {
                "type": "string",
                "description": "Only return messages received on or after this date (format: DD-Mon-YYYY, e.g., '20-Sep-2026').",
            },
            "before_date": {
                "type": "string",
                "description": "Only return messages received before this date (format: DD-Mon-YYYY).",
            },
            "unread_only": {
                "type": "boolean",
                "description": "If true, returns only unread (UNSEEN) messages. Defaults to false.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of messages to return. Defaults to 10.",
            },
            "folder": {
                "type": "string",
                "description": "Mailbox folder to search. Defaults to 'INBOX'.",
            },
        },
    },
}

READ_EMAIL_SCHEMA: Dict[str, Any] = {
    "name": "read_email",
    "description": (
        "Retrieve the complete body and RFC headers of a specific email message by Message-ID or sequence number."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "The exact RFC Message-ID to locate and read.",
            },
            "seq_num": {
                "type": "string",
                "description": "IMAP mailbox sequence number to read.",
            },
            "folder": {
                "type": "string",
                "description": "Mailbox folder to read from. Defaults to 'INBOX'.",
            },
        },
    },
}


def _get_agent_identity() -> str:
    """Resolve and enforce the authenticated agent email identity."""
    agent_mail_user = os.getenv("AGENT_MAIL_USER")
    if agent_mail_user:
        return agent_mail_user.strip()
    agent_id = os.getenv("HERMES_AGENT_ID") or os.getenv("AGENT_ID") or "hermes"
    return f"{agent_id}@titan.local"


def handle_send_email(args: Any = None, **kwargs: Any) -> str:
    """Handler for send_email tool."""
    params = dict(args) if isinstance(args, dict) else dict(kwargs)
    if isinstance(args, dict):
        params.update(kwargs)

    to = params.get("to") or params.get("recipient")
    subject = params.get("subject")
    body = params.get("body")
    in_reply_to = params.get("in_reply_to")
    references = params.get("references")

    if not to or not subject or not body:
        return json.dumps({"error": "Missing required fields: 'to', 'subject', and 'body' are required."})

    assigned_identity = _get_agent_identity()

    # Enforce multi-tenant sender verification: Agents cannot spoof sender identity
    from_addr = params.get("from_addr") or params.get("sender")
    if from_addr and from_addr.strip().lower() != assigned_identity.lower():
        err_msg = (
            f"Sender verification failed: Agent identity is locked to '{assigned_identity}'. "
            f"Cannot send as '{from_addr}'."
        )
        logger.warning(err_msg)
        return json.dumps({"error": err_msg})

    try:
        client = TitanMailClient.from_env()
        msg_id = client.send_mail(
            to=to,
            subject=subject,
            body=body,
            from_addr=assigned_identity,
            in_reply_to=in_reply_to,
            references=references,
        )
        logger.info("Agent '%s' sent email to '%s' (Message-ID: %s)", assigned_identity, to, msg_id)
        return json.dumps({
            "status": "success",
            "message": f"Email successfully sent to {to}",
            "message_id": msg_id,
            "sender": assigned_identity,
            "subject": subject,
            "in_reply_to": in_reply_to,
        })
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return json.dumps({"error": f"Failed to send email: {str(e)}"})


def handle_search_emails(args: Any = None, **kwargs: Any) -> str:
    """Handler for search_emails tool."""
    params = dict(args) if isinstance(args, dict) else dict(kwargs)
    if isinstance(args, dict):
        params.update(kwargs)
    elif isinstance(args, str):
        params["query"] = args

    query = params.get("query")
    subject = params.get("subject")
    from_addr = params.get("from_addr") or params.get("sender")
    since_date = params.get("since_date")
    before_date = params.get("before_date")
    unread_only = bool(params.get("unread_only", False))
    folder = params.get("folder", "INBOX")
    limit = int(params.get("limit", 10))

    try:
        client = TitanMailClient.from_env()
        results = client.search_messages(
            query=query,
            subject=subject,
            from_addr=from_addr,
            since_date=since_date,
            before_date=before_date,
            unread_only=unread_only,
            folder=folder,
            limit=limit,
        )
        return json.dumps({
            "status": "success",
            "count": len(results),
            "folder": folder,
            "messages": results,
        })
    except Exception as e:
        logger.error("Failed to search emails: %s", e)
        return json.dumps({"error": f"Failed to search emails: {str(e)}"})


def handle_read_email(args: Any = None, **kwargs: Any) -> str:
    """Handler for read_email tool."""
    params = dict(args) if isinstance(args, dict) else dict(kwargs)
    if isinstance(args, dict):
        params.update(kwargs)

    message_id = params.get("message_id")
    seq_num = params.get("seq_num")
    folder = params.get("folder", "INBOX")

    try:
        client = TitanMailClient.from_env()
        msg = client.read_message(
            message_id=message_id,
            seq_num=seq_num,
            folder=folder,
        )
        if not msg:
            return json.dumps({
                "status": "not_found",
                "message": f"No email found matching criteria (message_id={message_id}, seq_num={seq_num}).",
            })
        return json.dumps({
            "status": "success",
            "message": msg,
        })
    except Exception as e:
        logger.error("Failed to read email: %s", e)
        return json.dumps({"error": f"Failed to read email: {str(e)}"})
