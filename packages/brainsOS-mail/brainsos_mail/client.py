"""brainsOS Mail Client.

Zero-dependency RFC 5322 compliant client utilizing python standard library
smtplib and imaplib.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

logger = logging.getLogger("brainsos_mail.client")


def _format_msg_id(val: str) -> str:
    """Ensures message ID is enclosed in RFC 5322 angle brackets."""
    v = val.strip()
    if not v:
        return ""
    if not v.startswith("<") and not v.endswith(">"):
        return f"<{v}>"
    return v


class BrainsOSMailClient:
    """Lightweight mail client for brainsOS agents."""

    def __init__(
        self,
        smtp_host: str = "127.0.0.1",
        smtp_port: int = 25,
        imap_host: str = "127.0.0.1",
        imap_port: int = 143,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.username = username
        self.password = password

    @classmethod
    def from_env(cls) -> BrainsOSMailClient:
        """Initialize client from container or host environment variables."""
        smtp_host = os.getenv("BRAINSOS_MAIL_SMTP_HOST", os.getenv("MAIL_SERVER_HOST"))
        imap_host = os.getenv("BRAINSOS_MAIL_IMAP_HOST", os.getenv("MAIL_SERVER_HOST"))

        if not smtp_host:
            try:
                import socket

                socket.gethostbyname("mail-server")
                smtp_host = "mail-server"
                default_smtp_port = "25"
            except (socket.gaierror, OSError):
                smtp_host = "127.0.0.1"
                default_smtp_port = os.getenv("MAIL_SMTP_PORT", "10025")
        else:
            default_smtp_port = "25"

        if not imap_host:
            try:
                import socket

                socket.gethostbyname("mail-server")
                imap_host = "mail-server"
                default_imap_port = "143"
            except (socket.gaierror, OSError):
                imap_host = "127.0.0.1"
                default_imap_port = os.getenv("MAIL_IMAP_PORT", "10143")
        else:
            default_imap_port = "143"

        smtp_port = int(os.getenv("BRAINSOS_MAIL_SMTP_PORT", default_smtp_port))
        imap_port = int(os.getenv("BRAINSOS_MAIL_IMAP_PORT", default_imap_port))

        return cls(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            imap_host=imap_host,
            imap_port=imap_port,
            username=os.getenv("AGENT_MAIL_USER"),
            password=os.getenv("AGENT_MAIL_PASSWORD"),
        )

    def sync_to_sent_folder(
        self,
        msg: EmailMessage | bytes,
        sent_folder: str = "Sent",
        flags: str = "\\Seen",
    ) -> bool:
        """Appends the raw RFC 822 email payload to the mailbox's Sent folder.

        Logs warnings without failing delivery if IMAP append encounters a transient error.
        """
        if not self.username or not self.password:
            logger.debug("IMAP sync skipped: username or password not configured")
            return False

        try:
            raw_bytes = msg.as_bytes() if isinstance(msg, EmailMessage) else msg
            msg_id = msg.get("Message-ID", "") if isinstance(msg, EmailMessage) else ""

            with imaplib.IMAP4(self.imap_host, self.imap_port) as imap:
                imap.login(self.username, self.password)
                mailbox = f'"{sent_folder}"' if " " in sent_folder and not sent_folder.startswith('"') else sent_folder
                internal_date = imaplib.Time2Internaldate(time.time())

                status, response = imap.append(mailbox, flags, internal_date, raw_bytes)
                if status == "OK":
                    logger.debug("Successfully synced message %s to IMAP %s", msg_id, sent_folder)
                    return True
                else:
                    logger.warning(
                        "IMAP append to '%s' returned status %s: %s",
                        sent_folder,
                        status,
                        response,
                    )
                    return False
        except Exception as e:
            logger.warning("Transient error syncing message to IMAP folder '%s': %s", sent_folder, e)
            return False

    def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        from_addr: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        extra_headers: dict[str, str] | None = None,
        sync_imap: bool = True,
        sent_folder: str = "Sent",
    ) -> str:
        """Compose and dispatch an RFC-compliant email message with dual-dispatch IMAP sync.

        Returns the generated Message-ID.
        """
        domain = os.getenv("BRAINSOS_DOMAIN", "brainsos.local")
        sender = from_addr or self.username or f"agent@{domain}"
        msg = EmailMessage()
        msg_id = make_msgid(domain=domain)

        msg["Message-ID"] = msg_id
        msg["Date"] = formatdate(localtime=True)
        msg["From"] = sender
        msg["To"] = to

        # Threading header injection:
        # Subject: Re: <inbound.subject> avoiding duplicate Re: Re: prefixes
        clean_subj = subject.strip()
        if in_reply_to:
            raw_subj = re.sub(r"^(re:\s*)+", "", clean_subj, flags=re.IGNORECASE).strip()
            msg["Subject"] = f"Re: {raw_subj}"

            reply_id = _format_msg_id(in_reply_to)
            msg["In-Reply-To"] = reply_id

            if references:
                ref_tokens = [_format_msg_id(t) for t in references.strip().split() if t.strip()]
                if reply_id not in ref_tokens:
                    ref_tokens.append(reply_id)
                msg["References"] = " ".join(ref_tokens)
            else:
                msg["References"] = reply_id
        else:
            msg["Subject"] = clean_subj
            if references:
                ref_tokens = [_format_msg_id(t) for t in references.strip().split() if t.strip()]
                msg["References"] = " ".join(ref_tokens)

        if extra_headers:
            for k, v in extra_headers.items():
                msg[k] = v

        msg.set_content(body)

        # Step 1: SMTP Dispatch
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                except Exception:
                    # Fallback to direct submission if unauthenticated local relay is allowed
                    pass
            server.send_message(msg)

        # Step 2: IMAP Synchronization (Dual-Dispatch to Sent folder)
        if sync_imap and self.username and self.password:
            self.sync_to_sent_folder(msg, sent_folder=sent_folder)

        return msg_id

    def fetch_messages(
        self,
        folder: str = "INBOX",
        criteria: str = "ALL",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch messages matching criteria from the specified IMAP folder."""
        if not self.username or not self.password:
            raise ValueError("IMAP operations require username and password")

        results: list[dict[str, Any]] = []

        with imaplib.IMAP4(self.imap_host, self.imap_port) as imap:
            imap.login(self.username, self.password)

            # Quote folder name if it contains spaces (e.g. "Agent Fleet/terrastella")
            mailbox = f'"{folder}"' if " " in folder and not folder.startswith('"') else folder
            status, _ = imap.select(mailbox)
            if status != "OK":
                return results

            status, msg_nums = imap.search(None, criteria)
            if status != "OK" or not msg_nums[0]:
                return results

            id_list = msg_nums[0].split()
            # Fetch latest messages up to limit
            for num in id_list[-limit:]:
                seq_str = num.decode() if isinstance(num, bytes) else str(num)
                typ, data = imap.fetch(seq_str, "(RFC822)")
                if typ != "OK" or not data or not isinstance(data[0], tuple) or len(data[0]) < 2:
                    continue

                raw_email = data[0][1]
                if not isinstance(raw_email, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(raw_email)

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if isinstance(payload, bytes):
                                body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

                results.append(
                    {
                        "seq_num": seq_str,
                        "message_id": msg.get("Message-ID", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "subject": msg.get("Subject", ""),
                        "date": msg.get("Date", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                        "references": msg.get("References", ""),
                        "body": body.strip(),
                    }
                )

        return results

    def get_unread_messages(
        self,
        folder: str = "INBOX",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch unread (UNSEEN) messages from the specified folder."""
        return self.fetch_messages(folder=folder, criteria="UNSEEN", limit=limit)

    def search_messages(
        self,
        query: str | None = None,
        subject: str | None = None,
        from_addr: str | None = None,
        since_date: str | None = None,
        before_date: str | None = None,
        unread_only: bool = False,
        folder: str = "INBOX",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search messages matching criteria (keywords, subject, sender, date).

        Builds standard RFC 3501 IMAP SEARCH query.
        Example queries:
          - search_messages(query="deployment")
          - search_messages(subject="approval", unread_only=True)
          - search_messages(from_addr="admin@brainsos.local", since_date="20-Sep-2026")
        """
        tokens: list[str] = []
        if unread_only:
            tokens.append("UNSEEN")
        if query:
            tokens.append(f'TEXT "{query}"')
        if subject:
            tokens.append(f'SUBJECT "{subject}"')
        if from_addr:
            tokens.append(f'FROM "{from_addr}"')
        if since_date:
            tokens.append(f'SINCE "{since_date}"')
        if before_date:
            tokens.append(f'BEFORE "{before_date}"')

        criteria = " ".join(tokens) if tokens else "ALL"
        return self.fetch_messages(folder=folder, criteria=criteria, limit=limit)

    def list_folders(self) -> list[str]:
        """List all visible IMAP folders for the authenticated user."""
        if not self.username or not self.password:
            raise ValueError("IMAP operations require username and password")

        with imaplib.IMAP4(self.imap_host, self.imap_port) as imap:
            imap.login(self.username, self.password)
            status, folders = imap.list()
            if status != "OK" or not folders:
                return []
            result: list[str] = []
            for f in folders:
                if isinstance(f, bytes):
                    result.append(f.decode())
                elif isinstance(f, tuple) and f and isinstance(f[0], bytes):
                    result.append(f[0].decode())
            return result

    def read_message(
        self,
        message_id: str | None = None,
        seq_num: str | None = None,
        folder: str = "INBOX",
    ) -> dict[str, Any] | None:
        """Fetch and return a single message by Message-ID or IMAP sequence number."""
        if not self.username or not self.password:
            raise ValueError("IMAP operations require username and password")

        if message_id:
            clean_id = message_id.strip()
            # Clean enclosing angle brackets if present for IMAP header query
            header_query = clean_id
            if header_query.startswith("<") and header_query.endswith(">"):
                header_query = header_query[1:-1]
            criteria = f'HEADER Message-ID "{header_query}"'
            msgs = self.fetch_messages(folder=folder, criteria=criteria, limit=1)
            if msgs:
                return msgs[0]
            # Fallback search if exact HEADER match didn't return
            msgs = self.search_messages(query=clean_id, folder=folder, limit=1)
            return msgs[0] if msgs else None

        if seq_num:
            with imaplib.IMAP4(self.imap_host, self.imap_port) as imap:
                imap.login(self.username, self.password)
                mailbox = f'"{folder}"' if " " in folder and not folder.startswith('"') else folder
                status, _ = imap.select(mailbox)
                if status != "OK":
                    return None
                fetch_id = str(seq_num)
                typ, data = imap.fetch(fetch_id, "(RFC822)")
                if typ != "OK" or not data or not isinstance(data[0], tuple) or len(data[0]) < 2:
                    return None
                raw_email = data[0][1]
                if not isinstance(raw_email, (bytes, bytearray)):
                    return None
                msg = email.message_from_bytes(raw_email)
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if isinstance(payload, bytes):
                                body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

                return {
                    "seq_num": str(seq_num),
                    "message_id": msg.get("Message-ID", ""),
                    "from": msg.get("From", ""),
                    "to": msg.get("To", ""),
                    "subject": msg.get("Subject", ""),
                    "date": msg.get("Date", ""),
                    "in_reply_to": msg.get("In-Reply-To", ""),
                    "references": msg.get("References", ""),
                    "body": body.strip(),
                }

        # If neither specified, fetch latest message in folder
        latest = self.fetch_messages(folder=folder, criteria="ALL", limit=1)
        return latest[0] if latest else None
