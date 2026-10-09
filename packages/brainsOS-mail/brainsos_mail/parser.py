"""RFC 5322 MIME Parser and Canonical Thread Resolution for brainsOS."""

from __future__ import annotations

import email
import re
import uuid
from email import policy
from email.header import decode_header
from html.parser import HTMLParser
from typing import Any, cast

from .models import Attachment, ParsedInboundEmail


def _extract_payload_bytes(part: Any) -> bytes:
    """Safely extracts decoded payload bytes from an email message or part."""
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="replace")
    return b""


class _HTMLTextExtractor(HTMLParser):
    """Safely extracts visible plain text from an HTML email payload."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._ignore: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("script", "style", "head", "title"):
            self._ignore = True
        elif tag.lower() in ("p", "br", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style", "head", "title"):
            self._ignore = False
        elif tag.lower() in ("p", "div", "tr"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore:
            self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces).strip()


def _decode_header_str(val: Any) -> str:
    """Safely decodes an RFC 2047 encoded header string."""
    if not val:
        return ""
    try:
        parts = decode_header(str(val))
        decoded: list[str] = []
        for part, enc in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                decoded.append(str(part))
        return "".join(decoded).strip()
    except Exception:
        return str(val).strip()


def extract_message_ids(value: str | None) -> list[str]:
    """Extracts all Message-IDs from a header string."""
    if not value:
        return []
    # Match angle bracketed tokens: <id@host>
    found = re.findall(r"<[^>]+>", value)
    if found:
        return [f.strip() for f in found]
    # Fallback to whitespace splitting
    return [p.strip() for p in value.strip().split() if p.strip()]


def resolve_thread_id(headers: dict[str, Any]) -> str:
    """Deterministically resolves the conversation thread root Message-ID.

    Rules:
      1. If References exists, return the first Message-ID (root message).
      2. Else if In-Reply-To exists, return that Message-ID.
      3. Else, return the message's own Message-ID.
    """
    case_map = {k.lower(): v for k, v in headers.items() if v is not None}

    # 1. Check References header
    references = str(case_map.get("references", "")).strip()
    if references:
        ref_ids = extract_message_ids(references)
        if ref_ids:
            return ref_ids[0]

    # 2. Check In-Reply-To header
    in_reply_to = str(case_map.get("in-reply-to", "")).strip()
    if in_reply_to:
        reply_ids = extract_message_ids(in_reply_to)
        if reply_ids:
            return reply_ids[0]

    # 3. Check Message-ID header
    msg_id = str(case_map.get("message-id", "")).strip()
    if msg_id:
        msg_ids = extract_message_ids(msg_id)
        if msg_ids:
            return msg_ids[0]
        return msg_id

    # Fallback for headless or corrupted emails
    return f"<unthreaded-{uuid.uuid4().hex[:12]}@brainsos.local>"


def clean_email_body(raw_body: str, strip_chain: bool = False) -> str:
    """Cleans email body while preserving useful conversational context and email chains.

    By default (strip_chain=False), preserves reply blockquotes, attributions, and forwarded
    email chains, only stripping standard trailing signature blocks ('-- ', '--', '__').
    When strip_chain=True, strips reply blockquotes and attribution lines.
    """
    if not raw_body:
        return ""

    lines = raw_body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines: list[str] = []

    re_from_header = re.compile(r"^from:\s*.+@.+", re.IGNORECASE)
    re_sent_date_header = re.compile(r"^(sent|date):\s*.+", re.IGNORECASE)

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 1. Standard signature delimiters: "-- " or "--" or "__"
        if stripped in ("--", "-- ", "__"):
            break

        if strip_chain:
            # 2. Outlook/Exchange separator lines: "-----Original Message-----" or long underlines
            if re.match(r"^-{3,}\s*original message\s*-{3,}$", stripped, re.IGNORECASE) or re.match(r"^_{5,}$", stripped):
                break

            # 3. Header blocks: "From: ... \n Sent: ... "
            if re_from_header.match(stripped):
                next_idx = i + 1
                while next_idx < len(lines) and not lines[next_idx].strip():
                    next_idx += 1
                if next_idx < len(lines) and re_sent_date_header.match(lines[next_idx].strip()):
                    break

            # 4. Single-line attribution: "On <date>, <sender> wrote:" or "At <time>, <sender> wrote:"
            if re.match(r"^on\s+.+wrote\s*:?$", stripped, re.IGNORECASE) or re.match(
                r"^at\s+.+wrote\s*:?$", stripped, re.IGNORECASE
            ):
                break

            # 5. Two-line attribution: "On <date>,\n<sender> wrote:"
            if re.match(r"^on\s+.*,\s*$", stripped, re.IGNORECASE):
                next_idx = i + 1
                while next_idx < len(lines) and not lines[next_idx].strip():
                    next_idx += 1
                if next_idx < len(lines) and re.match(r"^.+wrote\s*:?$", lines[next_idx].strip(), re.IGNORECASE):
                    break

            # 6. Nested quote lines starting with '>' or '|'
            if stripped.startswith(">") or stripped.startswith("|"):
                i += 1
                continue

        cleaned_lines.append(line)
        i += 1

    return "\n".join(cleaned_lines).strip()


def parse_inbound_mime(raw_mime: bytes | str) -> ParsedInboundEmail:
    """Parses raw RFC 5322 MIME bytes into a clean, normalized ParsedInboundEmail."""
    if isinstance(raw_mime, str):
        raw_bytes = raw_mime.encode("utf-8", errors="replace")
    else:
        raw_bytes = raw_mime

    try:
        msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    except Exception:
        # Fallback to compat policy if default parser encounters an unhandled structure
        msg = email.message_from_bytes(raw_bytes, policy=cast(Any, policy.compat32))

    # Collect headers into dictionary
    headers: dict[str, str] = {}
    for k in msg.keys():
        headers[k] = _decode_header_str(msg.get(k, ""))

    raw_msg_id = headers.get("Message-ID", "").strip()
    msg_id = extract_message_ids(raw_msg_id)[0] if extract_message_ids(raw_msg_id) else raw_msg_id
    if not msg_id:
        msg_id = f"<inbound-{uuid.uuid4().hex[:12]}@brainsos.local>"

    thread_id = resolve_thread_id(headers)
    sender = headers.get("From", "").strip()
    recipient = (
        headers.get("To", "").strip()
        or headers.get("Delivered-To", "").strip()
        or headers.get("X-Envelope-To", "").strip()
    )
    subject = headers.get("Subject", "").strip()

    # Extract text/plain body, falling back to text/html
    plain_text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[Attachment] = []

    if msg.is_multipart():
        for part in msg.walk():
            # Check content disposition and filename
            disposition = str(part.get_content_disposition() or "").lower()
            filename = part.get_filename()
            content_type = str(part.get_content_type() or "").lower()

            if disposition == "attachment" or (filename and disposition != "inline"):
                payload = _extract_payload_bytes(part)
                attachments.append(
                    Attachment(
                        filename=_decode_header_str(filename or "attachment.bin"),
                        content_type=content_type,
                        payload=payload,
                        size=len(payload),
                    )
                )
            elif content_type == "text/plain":
                try:
                    text = part.get_content()
                except Exception:
                    payload_bytes = _extract_payload_bytes(part)
                    charset = part.get_content_charset() or "utf-8"
                    text = payload_bytes.decode(charset, errors="replace")
                plain_text_parts.append(text)
            elif content_type == "text/html":
                try:
                    html_content = part.get_content()
                except Exception:
                    payload_bytes = _extract_payload_bytes(part)
                    charset = part.get_content_charset() or "utf-8"
                    html_content = payload_bytes.decode(charset, errors="replace")
                html_parts.append(html_content)
    else:
        content_type = str(msg.get_content_type() or "").lower()
        if content_type == "text/plain":
            try:
                plain_text_parts.append(msg.get_content())
            except Exception:
                payload_bytes = _extract_payload_bytes(msg)
                charset = msg.get_content_charset() or "utf-8"
                plain_text_parts.append(payload_bytes.decode(charset, errors="replace"))
        elif content_type == "text/html":
            try:
                html_parts.append(msg.get_content())
            except Exception:
                payload_bytes = _extract_payload_bytes(msg)
                charset = msg.get_content_charset() or "utf-8"
                html_parts.append(payload_bytes.decode(charset, errors="replace"))

    raw_html = "\n\n".join(html_parts) if html_parts else None

    # Resolve raw conversational body
    if plain_text_parts:
        raw_body = "\n\n".join(plain_text_parts)
    elif html_parts:
        extractor = _HTMLTextExtractor()
        for h in html_parts:
            extractor.feed(h)
        raw_body = extractor.get_text()
    else:
        raw_body = ""

    clean_body = clean_email_body(raw_body, strip_chain=False)

    return ParsedInboundEmail(
        message_id=msg_id,
        thread_id=thread_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        clean_body=clean_body,
        body=raw_body,
        html_body=raw_html,
        date=headers.get("Date", ""),
        raw_mime=raw_bytes,
        attachments=attachments,
    )
