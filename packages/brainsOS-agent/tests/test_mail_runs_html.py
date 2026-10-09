"""Unit tests for HTML email formatting, Markdown conversion, and email chain preservation (Ticket #295)."""

from __future__ import annotations

import unittest
from brainsos_mail.models import ParsedInboundEmail
from brainsos_agent.mail_runs import (
    compose_reply_body,
    html_to_plain_text,
    is_valid_html,
    markdown_to_clean_html,
)


class TestMailRunsHTMLAndChain(unittest.TestCase):
    def test_is_valid_html_identifies_valid_html_structures(self):
        self.assertTrue(is_valid_html("<p>Hello <b>world</b></p>"))
        self.assertTrue(
            is_valid_html(
                "<!DOCTYPE html><html><head><title>Title</title></head><body><h1>Hi</h1></body></html>"
            )
        )
        self.assertTrue(
            is_valid_html(
                '<table border="1"><tr><th>Header</th></tr><tr><td>Data</td></tr></table>'
            )
        )
        self.assertTrue(
            is_valid_html(
                '<p>Line 1<br>Line 2<img src="pic.png" alt="pic"></p>'
            )
        )
        self.assertTrue(
            is_valid_html("```html\n<div><p>Fenced content</p></div>\n```")
        )

    def test_is_valid_html_rejects_non_html_and_invalid_markup(self):
        self.assertFalse(is_valid_html("# Cluster Status\n\n- item 1\n- item 2"))
        self.assertFalse(is_valid_html("cost < 10 and price > 5"))
        self.assertFalse(is_valid_html("Please contact <support@example.com>"))
        self.assertFalse(is_valid_html("<p>Paragraph <div>nested</p></div>"))
        self.assertFalse(is_valid_html("<div><p>Unclosed"))
        self.assertFalse(is_valid_html("Hello <br> world"))
        self.assertFalse(is_valid_html(""))
        self.assertFalse(is_valid_html("Just plain text without tags."))

    def test_markdown_to_clean_html_preserves_full_html_document(self):
        doc = "<!DOCTYPE html><html><body><h1>Header</h1><p>Body</p></body></html>"
        rendered = markdown_to_clean_html(doc)
        self.assertEqual(rendered, doc)
        self.assertNotIn('<div style="font-family:', rendered)

    def test_markdown_to_clean_html_converts_markdown_elements(self):
        md = (
            "# Cluster Status Report\n\n"
            "All **systems** are operational.\n\n"
            "- Node 1: *Healthy*\n"
            "- Node 2: *Healthy*\n\n"
            "```python\n"
            "def check():\n"
            "    return True\n"
            "```\n\n"
            "Check [Dashboard](https://dash.brainsos.ai) for details."
        )
        rendered = markdown_to_clean_html(md)
        self.assertIn("<h2", rendered)
        self.assertIn("Cluster Status Report", rendered)
        self.assertIn("<strong>systems</strong>", rendered)
        self.assertIn("<em>Healthy</em>", rendered)
        self.assertIn("<ul", rendered)
        self.assertIn("<li", rendered)
        self.assertIn("<pre", rendered)
        self.assertIn("<code", rendered)
        self.assertIn('href="https://dash.brainsos.ai"', rendered)

    def test_markdown_to_clean_html_preserves_existing_html(self):
        raw_html = (
            "<p>Hello, this is already <strong>clean HTML</strong>.</p>\n"
            "<ul>\n"
            "  <li>Item A</li>\n"
            "  <li>Item B</li>\n"
            "</ul>"
        )
        rendered = markdown_to_clean_html(raw_html)
        self.assertIn("<strong>clean HTML</strong>", rendered)
        self.assertIn("<li>Item A</li>", rendered)
        self.assertIn("<div style=", rendered)

    def test_markdown_to_clean_html_strips_code_fence_wrapper(self):
        fenced = (
            "```html\n"
            "<p>Here is the status report.</p>\n"
            "```"
        )
        rendered = markdown_to_clean_html(fenced)
        self.assertNotIn("```", rendered)
        self.assertIn("<p>Here is the status report.</p>", rendered)

    def test_html_to_plain_text_extracts_clean_text(self):
        raw_html = (
            "<div style='font-size:14px;'>"
            "<p>Paragraph 1 with <strong>bold</strong> text.</p>"
            "<br>"
            "<ul>"
            "<li>Item 1</li>"
            "<li>Item 2</li>"
            "</ul>"
            "</div>"
        )
        plain = html_to_plain_text(raw_html)
        self.assertIn("Paragraph 1 with bold text.", plain)
        self.assertIn("- Item 1", plain)
        self.assertIn("- Item 2", plain)
        self.assertNotIn("<p>", plain)
        self.assertNotIn("<ul>", plain)

    def test_compose_reply_body_preserves_email_chain_in_both_formats(self):
        inbound = ParsedInboundEmail(
            message_id="<msg-001@dgx.local.brainsos.ai>",
            thread_id="<msg-001@dgx.local.brainsos.ai>",
            sender="alice@dgx.local.brainsos.ai",
            recipient="bawtford@dgx.local.brainsos.ai",
            subject="Question regarding launch",
            clean_body="Can you confirm if the cluster is ready for launch?",
            body="Can you confirm if the cluster is ready for launch?\n\n-- \nAlice",
            date="Fri, 09 Oct 2026 12:00:00 +0000",
            raw_mime=b"",
        )
        agent_output = "<p>Yes, the cluster is <strong>fully operational</strong>.</p>"

        plain_body, html_body = compose_reply_body(agent_output, inbound)

        # Plain text assertions
        self.assertIn("Yes, the cluster is fully operational.", plain_body)
        self.assertIn("On Fri, 09 Oct 2026 12:00:00 +0000, alice@dgx.local.brainsos.ai wrote:", plain_body)
        self.assertIn("> Can you confirm if the cluster is ready for launch?", plain_body)

        # HTML assertions
        self.assertIn("<strong>fully operational</strong>", html_body)
        self.assertIn("brainsos-quote", html_body)
        self.assertIn("On Fri, 09 Oct 2026 12:00:00 +0000, alice@dgx.local.brainsos.ai wrote:", html_body)
        self.assertIn("Can you confirm if the cluster is ready for launch?", html_body)

    def test_compose_reply_body_handles_raw_html_response_and_inserts_chain_before_body(self):
        inbound = ParsedInboundEmail(
            message_id="<msg-002@dgx.local.brainsos.ai>",
            thread_id="<msg-002@dgx.local.brainsos.ai>",
            sender="bob@dgx.local.brainsos.ai",
            recipient="bawtford@dgx.local.brainsos.ai",
            subject="Full HTML request",
            clean_body="Please send the audit in full HTML format.",
            date="Fri, 09 Oct 2026 12:30:00 +0000",
            raw_mime=b"",
        )
        agent_output = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<body>\n"
            "  <h1>Audit Results</h1>\n"
            "  <p>All checks passed.</p>\n"
            "</body>\n"
            "</html>"
        )
        plain, rich = compose_reply_body(agent_output, inbound)
        self.assertIn("Audit Results", plain)
        self.assertIn("All checks passed.", plain)
        self.assertIn("> Please send the audit in full HTML format.", plain)
        self.assertNotIn("<h1>", plain)

        self.assertIn("<h1>Audit Results</h1>", rich)
        self.assertIn("brainsos-quote", rich)
        self.assertTrue(rich.strip().endswith("</html>"))
        self.assertIn("</body>\n</html>", rich)

    def test_compose_reply_body_without_inbound_email(self):
        agent_output = "Standalone report."
        plain, rich = compose_reply_body(agent_output, None)
        self.assertEqual(plain, "Standalone report.")
        self.assertIn("Standalone report.", rich)
        self.assertNotIn("wrote:", rich)


if __name__ == "__main__":
    unittest.main()
