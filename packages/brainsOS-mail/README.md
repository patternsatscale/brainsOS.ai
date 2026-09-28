# brainsOS Mail Client (`brainsOS-mail`)

Lightweight, zero-external-dependency RFC 5322 compliant email client designed specifically for autonomous AI agents in **brainsOS**.

## Features

- **Zero External Dependencies**: Built entirely upon Python's standard library (`smtplib`, `imaplib`, `email`).
- **Autonomous Agent Threading**: Automatically injects and tracks `Message-ID`, `In-Reply-To`, and `References` headers for multi-turn asynchronous agent conversations and Human-in-the-Loop (HITL) approvals.
- **Multi-Tenant Credentials**: Safe configuration via environment variables (`AGENT_MAIL_USER`, `AGENT_MAIL_PASSWORD`).
- **Shared Namespace Support**: Supports querying standard personal folders (`INBOX`) as well as shared administrative namespaces (`Agent Fleet/<agent>`).

## Quickstart

```python
from brainsos_mail import BrainsOSMailClient

# Initialize client from container environment variables
client = BrainsOSMailClient.from_env()

# Send an RFC-compliant notification or directive
msg_id = client.send_mail(
    to="admin@brainsos.local",
    subject="Approval Request: Release Layout v2.1",
    body="The automated visual tests passed. Awaiting human confirmation to merge.",
)

# Fetch unread messages
unread = client.get_unread_messages()
for msg in unread:
    print(f"From: {msg['from']} | Subject: {msg['subject']}")
    print(f"Body: {msg['body']}")

    # Reply preserving conversational thread
    client.send_mail(
        to=msg["from"],
        subject=f"Re: {msg['subject']}",
        body="Acknowledged directive. Commencing execution.",
        in_reply_to=msg["message_id"],
    )

# Search messages by keyword, subject, or sender
matches = client.search_messages(query="deployment", subject="approval")
for m in matches:
    print(f"Found related message: {m['subject']} from {m['from']}")
```

