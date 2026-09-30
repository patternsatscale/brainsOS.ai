"""Unit and integration tests for brainsos_mail package."""

import os
import unittest

from brainsos_mail.client import BrainsOSMailClient


class TestBrainsOSMailClient(unittest.TestCase):
    """Test suite for BrainsOSMailClient."""

    def setUp(self):
        # Read .env if present
        env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v

        self.smtp_host = os.getenv("TEST_MAIL_HOST", "127.0.0.1")
        self.smtp_port = int(os.getenv("TEST_MAIL_SMTP_PORT", "10025"))
        self.imap_port = int(os.getenv("TEST_MAIL_IMAP_PORT", "10143"))
        self.admin_pass = os.getenv("ADMIN_MAIL_PASSWORD", "brainsos_admin_mail_secret_change_me")
        self.agent_pass = os.getenv("TERRASTELLA_MAIL_PASSWORD", "brainsos_terrastella_mail_secret_change_me")

    def test_client_init_and_env(self):
        """Verify client instantiation from parameters and environment."""
        client = BrainsOSMailClient(
            smtp_host="localhost",
            smtp_port=2525,
            imap_host="localhost",
            imap_port=1143,
            username="test@brainsos.local",
            password="secretpassword",
        )
        self.assertEqual(client.smtp_host, "localhost")
        self.assertEqual(client.smtp_port, 2525)
        self.assertEqual(client.username, "test@brainsos.local")

    def test_live_smtp_and_imap_shared_roundtrip(self):
        """End-to-end integration test across SMTP submission and IMAP shared folder read."""
        import socket

        try:
            with socket.create_connection((self.smtp_host, self.smtp_port), timeout=0.5):
                pass
        except OSError:
            self.skipTest(f"Live mail server not reachable on {self.smtp_host}:{self.smtp_port}")

        # 1. Initialize agent client
        agent_client = BrainsOSMailClient(
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
            imap_host=self.smtp_host,
            imap_port=self.imap_port,
            username="terrastella@brainsos.local",
            password=self.agent_pass,
        )

        # 2. Agent sends email to admin
        subject = "Unit Test: Status Ping"
        body = "Automated unit test validating RFC threading and shared mailbox access."
        msg_id = agent_client.send_mail(
            to="admin@brainsos.local",
            subject=subject,
            body=body,
        )
        domain = os.getenv("BRAINSOS_DOMAIN", "brainsos.local")
        self.assertTrue(
            msg_id.startswith("<") and (msg_id.endswith(f"@{domain}>") or msg_id.endswith("@brainsos.local>"))
        )

        # Wait a moment for LMTP local delivery
        import time

        time.sleep(1.5)

        # 3. Admin client reads message
        admin_client = BrainsOSMailClient(
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
            imap_host=self.smtp_host,
            imap_port=self.imap_port,
            username="admin@brainsos.local",
            password=self.admin_pass,
        )

        messages = admin_client.fetch_messages(folder="INBOX", limit=5)
        matching = [m for m in messages if m["subject"] == subject]
        self.assertTrue(len(matching) >= 1)
        self.assertEqual(matching[-1]["from"], "terrastella@brainsos.local")
        self.assertIn("Automated unit test validating", matching[-1]["body"])

        # 4. Admin verifies shared folders list
        folders = admin_client.list_folders()
        self.assertTrue(any("Agent Fleet" in f for f in folders))
        self.assertTrue(any("terrastella" in f for f in folders))

        # 5. Search messages by subject and keyword
        searched = admin_client.search_messages(subject="Status Ping")
        self.assertTrue(len(searched) >= 1)
        self.assertEqual(searched[-1]["subject"], subject)

        body_searched = admin_client.search_messages(query="RFC threading")
        self.assertTrue(len(body_searched) >= 1)

        # 6. Read specific message by Message-ID using read_message()
        single_msg = admin_client.read_message(message_id=msg_id)
        self.assertIsNotNone(single_msg)
        self.assertEqual(single_msg["message_id"], msg_id)
        self.assertEqual(single_msg["subject"], subject)

        # 7. Reply with RFC threading headers (In-Reply-To, References)
        reply_subject = f"Re: {subject}"
        reply_body = "Directive confirmed. Executing instructions."
        reply_msg_id = admin_client.send_mail(
            to="terrastella@brainsos.local",
            subject=reply_subject,
            body=reply_body,
            in_reply_to=msg_id,
            references=msg_id,
        )
        self.assertTrue(
            reply_msg_id.startswith("<")
            and (reply_msg_id.endswith(f"@{domain}>") or reply_msg_id.endswith("@brainsos.local>"))
        )

        time.sleep(1.5)

        # Agent reads reply and verifies threading headers
        agent_msgs = agent_client.fetch_messages(folder="INBOX", limit=5)
        reply_matches = [m for m in agent_msgs if m["subject"] == reply_subject]
        self.assertTrue(len(reply_matches) >= 1)
        self.assertEqual(reply_matches[-1]["in_reply_to"], msg_id)
        self.assertEqual(reply_matches[-1]["references"], msg_id)


if __name__ == "__main__":
    unittest.main()
