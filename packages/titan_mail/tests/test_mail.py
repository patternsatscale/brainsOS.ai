"""Unit and integration tests for titan_mail package."""

import os
import unittest
from titan_mail.client import TitanMailClient


class TestTitanMailClient(unittest.TestCase):
    """Test suite for TitanMailClient."""

    def setUp(self):
        self.smtp_host = os.getenv("TEST_MAIL_HOST", "127.0.0.1")
        self.smtp_port = int(os.getenv("TEST_MAIL_SMTP_PORT", "10025"))
        self.imap_port = int(os.getenv("TEST_MAIL_IMAP_PORT", "10143"))
        self.admin_pass = os.getenv("ADMIN_MAIL_PASSWORD", "titan_admin_mail_secret_change_me")
        self.agent_pass = os.getenv("TERRASTELLA_MAIL_PASSWORD", "titan_terrastella_mail_secret_change_me")

    def test_client_init_and_env(self):
        """Verify client instantiation from parameters and environment."""
        client = TitanMailClient(
            smtp_host="localhost",
            smtp_port=2525,
            imap_host="localhost",
            imap_port=1143,
            username="test@titan.local",
            password="secretpassword",
        )
        self.assertEqual(client.smtp_host, "localhost")
        self.assertEqual(client.smtp_port, 2525)
        self.assertEqual(client.username, "test@titan.local")

    def test_live_smtp_and_imap_shared_roundtrip(self):
        """End-to-end integration test across SMTP submission and IMAP shared folder read."""
        # 1. Initialize agent client
        agent_client = TitanMailClient(
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
            imap_host=self.smtp_host,
            imap_port=self.imap_port,
            username="terrastella@titan.local",
            password=self.agent_pass,
        )

        # 2. Agent sends email to admin
        subject = "Unit Test: Status Ping"
        body = "Automated unit test validating RFC threading and shared mailbox access."
        msg_id = agent_client.send_mail(
            to="admin@titan.local",
            subject=subject,
            body=body,
        )
        self.assertTrue(msg_id.startswith("<") and msg_id.endswith("@titan.local>"))

        # Wait a moment for LMTP local delivery
        import time
        time.sleep(1.5)

        # 3. Admin client reads message

        admin_client = TitanMailClient(
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
            imap_host=self.smtp_host,
            imap_port=self.imap_port,
            username="admin@titan.local",
            password=self.admin_pass,
        )

        messages = admin_client.fetch_messages(folder="INBOX", limit=5)
        matching = [m for m in messages if m["subject"] == subject]
        self.assertTrue(len(matching) >= 1)
        self.assertEqual(matching[-1]["from"], "terrastella@titan.local")
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


if __name__ == "__main__":
    unittest.main()
