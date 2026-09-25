"""Project Titan Mail Client.

Zero-dependency RFC 5322 compliant client utilizing python standard library
smtplib and imaplib.
"""

from __future__ import annotations

import email
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib
import os
import smtplib
from typing import Any, Dict, List, Optional


class TitanMailClient:
    """Lightweight mail client for Project Titan agents."""

    def __init__(
        self,
        smtp_host: str = "127.0.0.1",
        smtp_port: int = 25,
        imap_host: str = "127.0.0.1",
        imap_port: int = 143,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.username = username
        self.password = password

    @classmethod
    def from_env(cls) -> TitanMailClient:
        """Initialize client from container or host environment variables."""
        return cls(
            smtp_host=os.getenv("TITAN_MAIL_SMTP_HOST", os.getenv("MAIL_SERVER_HOST", "mail-server")),
            smtp_port=int(os.getenv("TITAN_MAIL_SMTP_PORT", os.getenv("MAIL_SMTP_PORT", "25"))),
            imap_host=os.getenv("TITAN_MAIL_IMAP_HOST", os.getenv("MAIL_SERVER_HOST", "mail-server")),
            imap_port=int(os.getenv("TITAN_MAIL_IMAP_PORT", os.getenv("MAIL_IMAP_PORT", "143"))),
            username=os.getenv("AGENT_MAIL_USER"),
            password=os.getenv("AGENT_MAIL_PASSWORD"),
        )

    def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        from_addr: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Compose and dispatch an RFC-compliant email message.

        Returns the generated Message-ID.
        """
        sender = from_addr or self.username or "agent@titan.local"
        msg = EmailMessage()
        msg_id = make_msgid(domain="titan.local")

        msg["Message-ID"] = msg_id
        msg["Date"] = formatdate(localtime=True)
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject

        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to

        if extra_headers:
            for k, v in extra_headers.items():
                msg[k] = v

        msg.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                except Exception:
                    # Fallback to direct submission if unauthenticated local relay is allowed
                    pass
            server.send_message(msg)

        return msg_id

    def fetch_messages(
        self,
        folder: str = "INBOX",
        criteria: str = "ALL",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch messages matching criteria from the specified IMAP folder."""
        if not self.username or not self.password:
            raise ValueError("IMAP operations require username and password")

        results: List[Dict[str, Any]] = []

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
                typ, data = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not data:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", errors="replace"
                            )
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

                results.append(
                    {
                        "seq_num": num.decode(),
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
    ) -> List[Dict[str, Any]]:
        """Fetch unread (UNSEEN) messages from the specified folder."""
        return self.fetch_messages(folder=folder, criteria="UNSEEN", limit=limit)

    def search_messages(
        self,
        query: Optional[str] = None,
        subject: Optional[str] = None,
        from_addr: Optional[str] = None,
        since_date: Optional[str] = None,
        before_date: Optional[str] = None,
        unread_only: bool = False,
        folder: str = "INBOX",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search messages matching criteria (keywords, subject, sender, date).

        Builds standard RFC 3501 IMAP SEARCH query.
        Example queries:
          - search_messages(query="deployment")
          - search_messages(subject="approval", unread_only=True)
          - search_messages(from_addr="admin@titan.local", since_date="20-Sep-2026")
        """
        tokens: List[str] = []
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

    def list_folders(self) -> List[str]:
        """List all visible IMAP folders for the authenticated user."""
        if not self.username or not self.password:
            raise ValueError("IMAP operations require username and password")

        with imaplib.IMAP4(self.imap_host, self.imap_port) as imap:
            imap.login(self.username, self.password)
            status, folders = imap.list()
            if status != "OK" or not folders:
                return []
            return [f.decode() for f in folders if f]

    def read_message(
        self,
        message_id: Optional[str] = None,
        seq_num: Optional[str] = None,
        folder: str = "INBOX",
    ) -> Optional[Dict[str, Any]]:
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
                fetch_id = str(seq_num).encode()
                typ, data = imap.fetch(fetch_id, "(RFC822)")
                if typ != "OK" or not data or not data[0]:
                    return None
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(
                                part.get_content_charset() or "utf-8", errors="replace"
                            )
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
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
