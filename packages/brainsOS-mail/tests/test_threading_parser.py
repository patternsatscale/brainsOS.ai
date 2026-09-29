"""Unit tests for RFC 5322 MIME parsing, thread resolution, and quote stripping."""

from __future__ import annotations

import email.message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pytest

from brainsos_mail.models import Attachment, ParsedInboundEmail
from brainsos_mail.parser import clean_email_body, extract_message_ids, parse_inbound_mime, resolve_thread_id


class TestThreadResolution:
    def test_direct_message_resolves_to_self(self) -> None:
        headers = {"Message-ID": "<msg-001@brainsos.local>"}
        assert resolve_thread_id(headers) == "<msg-001@brainsos.local>"

    def test_single_reply_resolves_to_in_reply_to(self) -> None:
        headers = {
            "Message-ID": "<msg-002@brainsos.local>",
            "In-Reply-To": "<msg-001@brainsos.local>",
        }
        assert resolve_thread_id(headers) == "<msg-001@brainsos.local>"

    def test_multi_turn_reply_resolves_to_root_references(self) -> None:
        headers = {
            "Message-ID": "<msg-005@brainsos.local>",
            "In-Reply-To": "<msg-004@brainsos.local>",
            "References": "<root-msg@brainsos.local> <msg-002@brainsos.local> <msg-003@brainsos.local> <msg-004@brainsos.local>",
        }
        assert resolve_thread_id(headers) == "<root-msg@brainsos.local>"

    def test_case_insensitive_header_lookup(self) -> None:
        headers = {
            "message-id": "<msg-abc@brainsos.local>",
            "references": "<root-abc@brainsos.local> <msg-001@brainsos.local>",
        }
        assert resolve_thread_id(headers) == "<root-abc@brainsos.local>"

    def test_circular_and_duplicate_references(self) -> None:
        headers = {
            "Message-ID": "<msg-current@brainsos.local>",
            "References": "<root-id@brainsos.local> <child-1@brainsos.local> <root-id@brainsos.local>",
        }
        assert resolve_thread_id(headers) == "<root-id@brainsos.local>"

    def test_references_without_brackets(self) -> None:
        headers = {
            "Message-ID": "msg-current@brainsos.local",
            "References": "root-id@brainsos.local child-1@brainsos.local",
        }
        assert resolve_thread_id(headers) == "root-id@brainsos.local"

    def test_missing_message_id_generates_safe_fallback(self) -> None:
        headers = {}
        thread_id = resolve_thread_id(headers)
        assert thread_id.startswith("<unthreaded-")
        assert thread_id.endswith("@brainsos.local>")


class TestQuoteAndSignatureStripping:
    def test_clean_single_line_attribution_and_quotes(self) -> None:
        body = """Sounds great, let's schedule the deployment for tomorrow morning.

On Mon, Sep 29, 2026 at 9:30 AM Alice Smith <alice@brainsos.local> wrote:
> Can we deploy the new agent runtime tomorrow?
> We have completed all regression tests.
"""
        cleaned = clean_email_body(body)
        assert cleaned == "Sounds great, let's schedule the deployment for tomorrow morning."

    def test_clean_two_line_attribution(self) -> None:
        body = """Approved.

On Monday, September 29, 2026,
Operator wrote:
> Do you approve this change?
"""
        cleaned = clean_email_body(body)
        assert cleaned == "Approved."

    def test_clean_standard_signature_block(self) -> None:
        body = """Please find the updated metrics below.

Everything looks healthy.

-- 
Dr. Jane Doe
Director of AI Systems
BrainsOS Autonomous Fleet
"""
        cleaned = clean_email_body(body)
        assert cleaned == "Please find the updated metrics below.\n\nEverything looks healthy."

    def test_clean_outlook_style_original_message(self) -> None:
        body = """Confirmed.

-----Original Message-----
From: admin@brainsos.local
Sent: Monday, September 29, 2026 8:00 AM
To: operator@brainsos.local
Subject: System Check
"""
        cleaned = clean_email_body(body)
        assert cleaned == "Confirmed."

    def test_clean_inline_responses_between_quotes(self) -> None:
        body = """> Will the shared runner handle concurrent requests?
Yes, LiteLLM serializes completions.

> Does it preserve memory plane purity?
Absolutely, memory stays in Markdown.
"""
        cleaned = clean_email_body(body)
        assert "Yes, LiteLLM serializes completions." in cleaned
        assert "Absolutely, memory stays in Markdown." in cleaned
        assert "> Will the shared runner handle" not in cleaned
        assert "> Does it preserve" not in cleaned

    def test_empty_or_whitespace_body(self) -> None:
        assert clean_email_body("") == ""
        assert clean_email_body("   \n\n  ") == ""


class TestMIMEParser:
    def test_simple_plain_text_email(self) -> None:
        raw_email = (
            b"From: alice@brainsos.local\r\n"
            b"To: terrastella@brainsos.local\r\n"
            b"Subject: Hello Agent\r\n"
            b"Message-ID: <msg-100@brainsos.local>\r\n"
            b"Date: Mon, 29 Sep 2026 10:00:00 -0400\r\n"
            b"\r\n"
            b"Hello Terrastella, how are your systems running?\r\n"
        )
        parsed = parse_inbound_mime(raw_email)
        assert parsed.message_id == "<msg-100@brainsos.local>"
        assert parsed.thread_id == "<msg-100@brainsos.local>"
        assert parsed.sender == "alice@brainsos.local"
        assert parsed.recipient == "terrastella@brainsos.local"
        assert parsed.subject == "Hello Agent"
        assert parsed.clean_body == "Hello Terrastella, how are your systems running?"
        assert len(parsed.attachments) == 0

    def test_multipart_alternative_prioritizes_plain_text(self) -> None:
        msg = MIMEMultipart("alternative")
        msg["From"] = "bob@brainsos.local"
        msg["To"] = "marvin@brainsos.local"
        msg["Subject"] = "Status Request"
        msg["Message-ID"] = "<reply-200@brainsos.local>"
        msg["References"] = "<root-99@brainsos.local> <msg-199@brainsos.local>"

        part_plain = MIMEText("Plain text body content.\n\n-- \nBob", "plain")
        part_html = MIMEText("<html><body><p>HTML body content.</p></body></html>", "html")

        msg.attach(part_plain)
        msg.attach(part_html)

        parsed = parse_inbound_mime(msg.as_bytes())
        assert parsed.thread_id == "<root-99@brainsos.local>"
        assert parsed.clean_body == "Plain text body content."

    def test_html_only_email_fallback(self) -> None:
        msg = MIMEMultipart("alternative")
        msg["From"] = "charlie@brainsos.local"
        msg["To"] = "bawtford@brainsos.local"
        msg["Subject"] = "HTML Only Notification"
        msg["Message-ID"] = "<html-300@brainsos.local>"

        html_body = "<html><body><h1>Alert</h1><p>System disk usage at 12%.</p></body></html>"
        msg.attach(MIMEText(html_body, "html"))

        parsed = parse_inbound_mime(msg.as_bytes())
        assert "System disk usage at 12%." in parsed.clean_body
        assert "<html>" not in parsed.clean_body

    def test_email_with_attachments(self) -> None:
        msg = MIMEMultipart()
        msg["From"] = "dev@brainsos.local"
        msg["To"] = "terrastella@brainsos.local"
        msg["Subject"] = "Spec File"
        msg["Message-ID"] = "<att-400@brainsos.local>"

        msg.attach(MIMEText("Please inspect the attached log file.", "plain"))

        attachment_payload = b"2026-09-29 10:00:00 INFO Agent initialized successfully."
        part_att = MIMEApplication(attachment_payload, Name="agent.log")
        part_att["Content-Disposition"] = 'attachment; filename="agent.log"'
        msg.attach(part_att)

        parsed = parse_inbound_mime(msg.as_bytes())
        assert parsed.clean_body == "Please inspect the attached log file."
        assert len(parsed.attachments) == 1
        att = parsed.attachments[0]
        assert att.filename == "agent.log"
        assert att.payload == attachment_payload
        assert att.size == len(attachment_payload)

    def test_non_utf8_and_malformed_mime(self) -> None:
        # ISO-8859-1 payload with special characters
        iso_bytes = (
            b"From: =?ISO-8859-1?Q?Ren=E9?= <rene@brainsos.local>\r\n"
            b"To: admin@brainsos.local\r\n"
            b"Subject: =?ISO-8859-1?Q?Caf=E9?= rendezvous\r\n"
            b"Message-ID: <iso-500@brainsos.local>\r\n"
            b"Content-Type: text/plain; charset=ISO-8859-1\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n"
            b"\r\n"
            b"Ren\xe9 invited you to the caf\xe9.\r\n"
        )
        parsed = parse_inbound_mime(iso_bytes)
        assert "René" in parsed.sender
        assert "Café" in parsed.subject
        assert "René invited you to the café." in parsed.clean_body

    def test_completely_corrupted_raw_bytes_failsafe(self) -> None:
        corrupted = b"\x00\xff\xfe\xfa\x80random corrupted non-mime garbage"
        parsed = parse_inbound_mime(corrupted)
        assert isinstance(parsed, ParsedInboundEmail)
        assert parsed.raw_mime == corrupted
        assert parsed.thread_id.startswith("<")
