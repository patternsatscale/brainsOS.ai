"""Unit tests for BrainsOSMailClient threading headers and IMAP synchronization."""

from __future__ import annotations

import email
import imaplib
import unittest
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from brainsos_mail.client import BrainsOSMailClient, _format_msg_id


class TestBrainsOSMailClientThreadingAndSync(unittest.TestCase):
    """Test suite validating RFC 5322 threading headers and dual-dispatch IMAP sync."""

    def setUp(self):
        self.client = BrainsOSMailClient(
            smtp_host="mail-test.local",
            smtp_port=25,
            imap_host="mail-test.local",
            imap_port=143,
            username="agent@brainsos.local",
            password="test-secret-password",
        )

    def test_format_msg_id(self):
        """Verify angle bracket formatting helper."""
        self.assertEqual(_format_msg_id("<test@brainsos.local>"), "<test@brainsos.local>")
        self.assertEqual(_format_msg_id("test@brainsos.local"), "<test@brainsos.local>")
        self.assertEqual(_format_msg_id("  <test@brainsos.local>  "), "<test@brainsos.local>")
        self.assertEqual(_format_msg_id(""), "")

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_send_mail_subject_normalization_with_reply(self, mock_imap_cls, mock_smtp_cls):
        """Verify Subject has 'Re: ' added and duplicate 'Re: Re:' prefixes are collapsed."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        # Case 1: Fresh subject gets Re:
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Sprint Planning",
            body="Acknowledged.",
            in_reply_to="<msg-001@brainsos.local>",
        )
        msg1 = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg1["Subject"], "Re: Sprint Planning")

        # Case 2: Subject with existing 'Re: ' remains 'Re: '
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Re: Sprint Planning",
            body="Acknowledged.",
            in_reply_to="<msg-001@brainsos.local>",
        )
        msg2 = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg2["Subject"], "Re: Sprint Planning")

        # Case 3: Subject with case-insensitive 're:   re:  Sprint Planning' collapses to 'Re: Sprint Planning'
        self.client.send_mail(
            to="user@brainsos.local",
            subject="re:  RE:   Sprint Planning",
            body="Acknowledged.",
            in_reply_to="<msg-001@brainsos.local>",
        )
        msg3 = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg3["Subject"], "Re: Sprint Planning")

        # Case 4: Outbound message without in_reply_to preserves original subject
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Fresh Notice",
            body="Hello!",
        )
        msg4 = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg4["Subject"], "Fresh Notice")

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_send_mail_threading_headers_missing_or_empty_references(self, mock_imap_cls, mock_smtp_cls):
        """Verify In-Reply-To and References when references is missing or empty."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        # Missing references
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Hello",
            body="Reply text",
            in_reply_to="<root-001@brainsos.local>",
        )
        msg = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg["In-Reply-To"], "<root-001@brainsos.local>")
        self.assertEqual(msg["References"], "<root-001@brainsos.local>")

        # Empty string references
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Hello",
            body="Reply text",
            in_reply_to="root-002@brainsos.local",
            references="",
        )
        msg_empty = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg_empty["In-Reply-To"], "<root-002@brainsos.local>")
        self.assertEqual(msg_empty["References"], "<root-002@brainsos.local>")

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_send_mail_threading_headers_chain(self, mock_imap_cls, mock_smtp_cls):
        """Verify In-Reply-To and References chain resolution."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        self.client.send_mail(
            to="user@brainsos.local",
            subject="Thread Follow-up",
            body="Chained reply",
            in_reply_to="<turn-2@brainsos.local>",
            references="<root-0@brainsos.local> <turn-1@brainsos.local>",
        )
        msg = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(msg["In-Reply-To"], "<turn-2@brainsos.local>")
        self.assertEqual(
            msg["References"],
            "<root-0@brainsos.local> <turn-1@brainsos.local> <turn-2@brainsos.local>",
        )

        # Do not duplicate if in_reply_to is already present in references
        self.client.send_mail(
            to="user@brainsos.local",
            subject="Thread Follow-up",
            body="Chained reply",
            in_reply_to="<turn-2@brainsos.local>",
            references="<root-0@brainsos.local> <turn-2@brainsos.local>",
        )
        msg_dup = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(
            msg_dup["References"],
            "<root-0@brainsos.local> <turn-2@brainsos.local>",
        )

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_dual_dispatch_smtp_and_imap_append(self, mock_imap_cls, mock_smtp_cls):
        """Verify SMTP transmission followed by IMAP Sent folder append."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        msg_id = self.client.send_mail(
            to="cindy@brainsos.local",
            subject="Design Specs",
            body="Here are the latest design tokens.",
            sent_folder="Sent",
        )

        # 1. Verify SMTP
        mock_smtp.login.assert_called_once_with("agent@brainsos.local", "test-secret-password")
        mock_smtp.send_message.assert_called_once()
        sent_msg = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(sent_msg["Message-ID"], msg_id)

        # 2. Verify IMAP Append
        mock_imap.login.assert_called_once_with("agent@brainsos.local", "test-secret-password")
        mock_imap.append.assert_called_once()
        args, kwargs = mock_imap.append.call_args
        self.assertEqual(args[0], "Sent")
        self.assertEqual(args[1], "\\Seen")
        # Internaldate is args[2]
        self.assertIsInstance(args[2], str)
        # Raw bytes payload is args[3]
        self.assertIsInstance(args[3], bytes)
        parsed_back = email.message_from_bytes(args[3])
        self.assertEqual(parsed_back["Message-ID"], msg_id)

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_imap_transient_error_does_not_fail_smtp_delivery(self, mock_imap_cls, mock_smtp_cls):
        """Verify that IMAP append failure logs warning but does not raise or interrupt SMTP delivery."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.side_effect = imaplib.IMAP4.error("IMAP connection lost")
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        msg_id = self.client.send_mail(
            to="cindy@brainsos.local",
            subject="Resilience Test",
            body="Ensuring delivery succeeds despite IMAP issues.",
        )

        self.assertTrue(msg_id.startswith("<") and msg_id.endswith(">"))
        mock_smtp.send_message.assert_called_once()

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_sync_imap_disabled_or_unauthenticated(self, mock_imap_cls, mock_smtp_cls):
        """Verify IMAP append is bypassed when sync_imap=False or username/password is missing."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        # Case 1: sync_imap=False
        self.client.send_mail(
            to="user@brainsos.local",
            subject="No Sync",
            body="Payload",
            sync_imap=False,
        )
        mock_imap_cls.assert_not_called()

        # Case 2: Client without credentials
        unauthed_client = BrainsOSMailClient(
            smtp_host="mail-test.local",
            username=None,
            password=None,
        )
        unauthed_client.send_mail(
            to="user@brainsos.local",
            subject="Unauthenticated",
            body="Payload",
        )
        mock_imap_cls.assert_not_called()

    @patch("imaplib.IMAP4")
    def test_direct_sync_to_sent_folder(self, mock_imap_cls):
        """Verify direct sync_to_sent_folder method execution."""
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        email_msg = EmailMessage()
        email_msg["From"] = "agent@brainsos.local"
        email_msg["To"] = "client@brainsos.local"
        email_msg["Subject"] = "Manual Sync"
        email_msg.set_content("Direct sync payload.")

        success = self.client.sync_to_sent_folder(email_msg, sent_folder="Sent")
        self.assertTrue(success)
        mock_imap.append.assert_called_once()

    @patch("smtplib.SMTP")
    @patch("imaplib.IMAP4")
    def test_send_mail_with_html_body_creates_multipart_alternative(self, mock_imap_cls, mock_smtp_cls):
        """Verify that providing html_body produces a multipart/alternative email with text and HTML."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp
        mock_imap = MagicMock()
        mock_imap.append.return_value = ("OK", [b"Append completed"])
        mock_imap_cls.return_value.__enter__.return_value = mock_imap

        self.client.send_mail(
            to="user@brainsos.local",
            subject="HTML Report",
            body="Plain text report.",
            html_body="<p><strong>HTML</strong> report.</p>",
        )

        sent_msg = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(sent_msg.get_content_type(), "multipart/alternative")
        parts = [p.get_content_type() for p in sent_msg.walk() if not p.is_multipart()]
        self.assertIn("text/plain", parts)
        self.assertIn("text/html", parts)

        # Verify text part content
        plain_part = [p for p in sent_msg.walk() if p.get_content_type() == "text/plain"][0]
        self.assertIn("Plain text report.", plain_part.get_content())

        # Verify html part content
        html_part = [p for p in sent_msg.walk() if p.get_content_type() == "text/html"][0]
        self.assertIn("<strong>HTML</strong>", html_part.get_content())


if __name__ == "__main__":
    unittest.main()
