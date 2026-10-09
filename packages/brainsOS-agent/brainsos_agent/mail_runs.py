"""Shared primitives for the email -> Hermes run -> reply pipeline (Ticket #295).

* ``canonical_session_id`` — the single session key used for one agent's email thread across
  Hermes (``/v1/runs`` ``session_id``), Hermes Langfuse traces, LiteLLM Langfuse traces and the
  worker's own ``email-run`` trace.
* ``failure_email_body`` — the plain-language failure reply sent to the sender when a run does
  not complete. Raw errors and stack traces are never included (they go to logs/Langfuse only).
"""

from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import re
from typing import Any

# Terminal outcomes produced by the adapter / worker.
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"
RUN_INTERRUPTED = "interrupted"
RUN_TIMEOUT = "timeout"
RUN_REJECTED = "rejected"
RUN_EMPTY = "empty"
RUN_UNREACHABLE = "unreachable"

_MAX_SESSION_LEN = 160


def canonical_session_id(agent_id: str, thread_id: str) -> str:
    """Return the canonical session key ``mail-<agent>-<thread>`` (``[A-Za-z0-9_-]`` only).

    The key is scoped per agent so two agents on the same email thread never share a session.
    Long thread ids are truncated and suffixed with a short stable hash.
    """
    agent = re.sub(r"[^A-Za-z0-9_-]", "_", (agent_id or "agent").strip()) or "agent"
    thread = re.sub(r"[^A-Za-z0-9_-]", "_", (thread_id or "").strip().strip("<>").strip()) or "no-thread"
    session = f"mail-{agent}-{thread}"
    if len(session) > _MAX_SESSION_LEN:
        digest = hashlib.sha256(thread.encode("utf-8")).hexdigest()[:12]
        session = f"{session[: _MAX_SESSION_LEN - 13]}-{digest}"
    return session


def idempotency_key_for(message_id: str | None, fallback: str) -> str:
    """Hermes ``Idempotency-Key``: 1-255 visible ASCII characters derived from the Message-ID."""
    raw = (message_id or "").strip().strip("<>").strip() or fallback
    key = "".join(ch for ch in raw if 33 <= ord(ch) <= 126)
    if not key:
        key = hashlib.sha256(fallback.encode("utf-8")).hexdigest()
    if len(key) > 200:
        key = f"{key[:180]}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"
    return f"mail:{key}"


_EXPLANATIONS: dict[str, str] = {
    RUN_FAILED: "I ran into a problem while working on your request and could not finish it.",
    RUN_CANCELLED: "Your request was stopped before it finished.",
    RUN_INTERRUPTED: "The agent service restarted while I was working on your request, so the work did not finish.",
    RUN_TIMEOUT: "Your request ran longer than the maximum time allowed for a single run ({budget}) and was stopped.",
    RUN_REJECTED: "I could not start working on your request because of a configuration problem on our side.",
    RUN_EMPTY: "I finished working on your request but did not produce a reply.",
    RUN_UNREACHABLE: "I could not reach the agent service to work on your request.",
}


def _format_budget(seconds: float | None) -> str:
    if not seconds:
        return "the configured limit"
    seconds = int(seconds)
    if seconds >= 3600:
        hours = seconds / 3600
        return f"{hours:g} hour" + ("" if hours == 1 else "s")
    minutes = max(1, seconds // 60)
    return f"{minutes} minute" + ("" if minutes == 1 else "s")


def failure_email_body(
    status: str,
    *,
    agent_name: str,
    reference: str | None = None,
    budget_sec: float | None = None,
) -> str:
    """Builds the plain-language failure reply (explanation + recommendations, no raw errors)."""
    explanation = _EXPLANATIONS.get(status, _EXPLANATIONS[RUN_FAILED]).format(budget=_format_budget(budget_sec))

    recommendations = [
        "Reply to this email to try again. Your original message is kept in this thread's history.",
    ]
    if status == RUN_TIMEOUT:
        recommendations.append(
            "Large jobs work best in stages: ask for a first milestone (for example an outline or a "
            "single page) and build on it in follow-up emails."
        )
    elif status in (RUN_FAILED, RUN_EMPTY):
        recommendations.append(
            "If the request is large or has several parts, try splitting it into smaller, specific steps."
        )
    elif status in (RUN_INTERRUPTED, RUN_UNREACHABLE):
        recommendations.append("This is usually temporary. Waiting a few minutes before retrying often helps.")
    recommendations.append(
        "If it keeps happening, contact the system operator"
        + (f" and quote reference {reference}." if reference else ".")
    )

    lines = [
        "Hello,",
        "",
        explanation,
        "",
        "What you can do:",
        *[f"- {item}" for item in recommendations],
        "",
        f"— {agent_name}",
    ]
    return "\n".join(lines)


def _format_inline_markdown(text: str) -> str:
    """Formats inline Markdown (bold, italic, code, links) to safe HTML."""
    safe = html.escape(text)

    # Inline code: `code`
    safe = re.sub(
        r"`([^`]+)`",
        r'<code style="background-color: #f3f4f6; padding: 2px 4px; border-radius: 4px; font-family: monospace; font-size: 13px;">\1</code>',
        safe,
    )
    # Bold: **text** or __text__
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", safe)
    # Italic: *text* or _text_
    safe = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", safe)
    safe = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", safe)
    # Links: [text](url)
    safe = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color: #2563eb; text-decoration: underline;">\1</a>',
        safe,
    )
    return safe


_STANDARD_HTML_TAGS = {
    "a", "abbr", "address", "area", "article", "aside", "audio", "b", "base",
    "bdi", "bdo", "blockquote", "body", "br", "button", "canvas", "caption",
    "cite", "code", "col", "colgroup", "data", "datalist", "dd", "del",
    "details", "dfn", "dialog", "div", "dl", "dt", "em", "embed", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "head", "header", "hgroup", "hr", "html", "i", "iframe", "img",
    "input", "ins", "kbd", "label", "legend", "li", "link", "main", "map",
    "mark", "meta", "meter", "nav", "noscript", "object", "ol", "optgroup",
    "option", "output", "p", "param", "picture", "pre", "progress", "q", "rp",
    "rt", "ruby", "s", "samp", "script", "section", "select", "small",
    "source", "span", "strong", "style", "sub", "summary", "sup", "table",
    "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time",
    "title", "tr", "track", "u", "ul", "var", "video", "wbr",
}

_VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}

_BLOCK_OR_STRUCTURAL_TAGS = {
    "html", "body", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "table", "tr", "td", "th", "blockquote", "pre",
    "section", "article", "header", "footer", "main", "nav",
}


class _HTMLValidator(HTMLParser):
    """Checks whether a string forms well-structured, valid HTML tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.stack: list[str] = []
        self.has_block_tags: bool = False
        self.invalid_tags: list[str] = []
        self.mismatched: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in _STANDARD_HTML_TAGS:
            self.tags.append(tag_lower)
            if tag_lower in _BLOCK_OR_STRUCTURAL_TAGS:
                self.has_block_tags = True
            # HTML5 implicit closes for list items and table cells
            if tag_lower in ("li", "dt", "dd") and self.stack and self.stack[-1] == tag_lower:
                self.stack.pop()
            if tag_lower in ("td", "th") and self.stack and self.stack[-1] in ("td", "th"):
                self.stack.pop()
            if tag_lower == "tr" and self.stack and self.stack[-1] == "tr":
                self.stack.pop()
            if tag_lower not in _VOID_HTML_TAGS:
                self.stack.append(tag_lower)
        else:
            self.invalid_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in _STANDARD_HTML_TAGS:
            self.tags.append(tag_lower)
            if tag_lower in _BLOCK_OR_STRUCTURAL_TAGS:
                self.has_block_tags = True
        else:
            self.invalid_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in _STANDARD_HTML_TAGS:
            if tag_lower in _VOID_HTML_TAGS:
                return
            # Implicit closing of inner items on parent close
            if tag_lower in ("ul", "ol") and self.stack and self.stack[-1] == "li":
                self.stack.pop()
            if tag_lower == "table" and self.stack and self.stack[-1] in ("tr", "td", "th", "tbody"):
                while self.stack and self.stack[-1] in ("tr", "td", "th", "tbody"):
                    self.stack.pop()
            if self.stack and self.stack[-1] == tag_lower:
                self.stack.pop()
            elif tag_lower in self.stack:
                while self.stack and self.stack[-1] != tag_lower:
                    self.stack.pop()
                if self.stack and self.stack[-1] == tag_lower:
                    self.stack.pop()
            else:
                self.mismatched = True
        else:
            self.invalid_tags.append(tag)


def is_valid_html(text: str) -> bool:
    """Returns True if the text is already well-formed HTML (fragment or document).

    Distinguishes genuine HTML from plain text, Markdown, mathematical inequalities
    (e.g., '5 < 10'), and email addresses in angle brackets (e.g., '<user@domain>').
    """
    if not text or not isinstance(text, str):
        return False
    raw = text.strip()
    # Strip optional outer code block wrapper
    fence_match = re.match(r"^\s*```(?:html)?\s*\n(.*?)\n\s*```\s*$", raw, re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    if not ("<" in raw and ">" in raw):
        return False

    validator = _HTMLValidator()
    try:
        validator.feed(raw)
        validator.close()
    except Exception:
        return False

    if validator.invalid_tags:
        return False
    if not validator.tags:
        return False
    if validator.mismatched:
        return False
    if validator.stack:
        return False
    # Must have structural block elements OR balanced standard inline tags
    if not validator.has_block_tags and not any(
        t in ("a", "span", "b", "strong", "em", "i", "code") for t in validator.tags
    ):
        return False

    return True


def markdown_to_clean_html(text: str) -> str:
    """Converts Markdown or raw text into clean, modern email-safe HTML.

    If the payload is already valid HTML, it is preserved directly without
    Markdown conversion, only ensuring proper container styling if needed.
    """
    raw = (text or "").strip()
    if not raw:
        return ""

    # Strip code block wrappers if the model wrapped the entire response
    fence_match = re.match(r"^\s*```(?:html|markdown)?\s*\n(.*?)\n\s*```\s*$", raw, re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()

    # Pre-check: If already valid HTML, preserve it directly!
    if is_valid_html(raw):
        lower_raw = raw.lower()
        if "<!doctype" in lower_raw or "<html" in lower_raw or "<body" in lower_raw:
            return raw

        if raw.startswith("<div") and "font-family" in lower_raw:
            return raw

        return (
            f'<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; '
            f'font-size: 14px; line-height: 1.6; color: #111827;">\n{raw}\n</div>'
        )

    # Convert Markdown to HTML
    lines = raw.split("\n")
    html_pieces: list[str] = []
    in_code_block = False
    code_block_lines: list[str] = []
    in_list = False
    list_type = "ul"
    in_blockquote = False
    blockquote_lines: list[str] = []

    def close_list():
        nonlocal in_list, list_type
        if in_list:
            html_pieces.append(f"</{list_type}>")
            in_list = False

    def close_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            quote_content = "<br>".join(blockquote_lines)
            html_pieces.append(
                f'<blockquote style="margin: 8px 0; padding-left: 10px; border-left: 3px solid #d1d5db; color: #4b5563;">'
                f'{quote_content}</blockquote>'
            )
            in_blockquote = False
            blockquote_lines = []

    for line in lines:
        stripped = line.strip()

        # Code block fence
        if stripped.startswith("```"):
            if in_code_block:
                code_content = html.escape("\n".join(code_block_lines))
                html_pieces.append(
                    f'<pre style="background-color: #f3f4f6; padding: 10px; border-radius: 6px; overflow-x: auto; '
                    f'font-family: monospace; font-size: 13px;"><code>{code_content}</code></pre>'
                )
                in_code_block = False
                code_block_lines = []
            else:
                close_list()
                close_blockquote()
                in_code_block = True
                code_block_lines = []
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Blockquote
        if stripped.startswith(">"):
            close_list()
            in_blockquote = True
            bq_text = _format_inline_markdown(stripped[1:].strip())
            blockquote_lines.append(bq_text)
            continue
        elif in_blockquote and not stripped:
            close_blockquote()
            continue

        # Blank line
        if not stripped:
            close_list()
            close_blockquote()
            continue

        # Headings
        header_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if header_match:
            close_list()
            close_blockquote()
            level = len(header_match.group(1))
            tag_level = min(6, level + 1)
            h_text = _format_inline_markdown(header_match.group(2).strip())
            html_pieces.append(
                f'<h{tag_level} style="margin: 16px 0 8px 0; color: #111827; font-weight: 600;">{h_text}</h{tag_level}>'
            )
            continue

        # Unordered list: - item or * item
        ul_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if ul_match:
            close_blockquote()
            if not in_list or list_type != "ul":
                close_list()
                html_pieces.append('<ul style="margin: 8px 0; padding-left: 20px;">')
                in_list = True
                list_type = "ul"
            item_text = _format_inline_markdown(ul_match.group(1).strip())
            html_pieces.append(f'<li style="margin: 4px 0;">{item_text}</li>')
            continue

        # Ordered list: 1. item
        ol_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ol_match:
            close_blockquote()
            if not in_list or list_type != "ol":
                close_list()
                html_pieces.append('<ol style="margin: 8px 0; padding-left: 20px;">')
                in_list = True
                list_type = "ol"
            item_text = _format_inline_markdown(ol_match.group(1).strip())
            html_pieces.append(f'<li style="margin: 4px 0;">{item_text}</li>')
            continue

        # Normal paragraph
        close_list()
        close_blockquote()
        p_text = _format_inline_markdown(stripped)
        html_pieces.append(f'<p style="margin: 8px 0;">{p_text}</p>')

    close_list()
    close_blockquote()
    if in_code_block and code_block_lines:
        code_content = html.escape("\n".join(code_block_lines))
        html_pieces.append(f'<pre style="background-color: #f3f4f6; padding: 10px;"><code>{code_content}</code></pre>')

    inner_html = "\n".join(html_pieces)
    return (
        f'<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; '
        f'font-size: 14px; line-height: 1.6; color: #111827;">\n{inner_html}\n</div>'
    )


def html_to_plain_text(html_text: str) -> str:
    """Extracts human-readable plain text from HTML, preserving line breaks."""
    if not html_text:
        return ""
    text = html_text.strip()
    # Strip optional outer code block wrapper
    fence_match = re.match(r"^\s*```(?:html)?\s*\n(.*?)\n\s*```\s*$", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    # Code blocks
    text = re.sub(r"<pre[^>]*><code[^>]*>(.*?)</code></pre>", r"\n\1\n", text, flags=re.DOTALL | re.IGNORECASE)
    # Line breaks and paragraphs
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</blockquote>", "\n\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compose_reply_body(
    agent_output: str,
    inbound_email: Any | None = None,
) -> tuple[str, str]:
    """Composes (plain_text_with_chain, html_with_chain) for an agent email reply.

    Ensures the agent reply is formatted in clean HTML and quotes the previous
    email chain below it so email conversations maintain full context.
    """
    raw_output = (agent_output or "").strip()
    fence_match = re.match(r"^\s*```(?:html)?\s*\n(.*?)\n\s*```\s*$", raw_output, re.DOTALL | re.IGNORECASE)
    unfenced_output = fence_match.group(1).strip() if fence_match else raw_output

    if is_valid_html(raw_output):
        agent_html = markdown_to_clean_html(raw_output)
        agent_text = html_to_plain_text(unfenced_output)
    else:
        agent_text = raw_output
        agent_html = markdown_to_clean_html(raw_output)

    if not inbound_email:
        return agent_text, agent_html

    # Extract inbound email content for chain quotation
    sender = getattr(inbound_email, "sender", "user")
    date_str = getattr(inbound_email, "date", "") or ""
    header_line = f"On {date_str}, {sender} wrote:" if date_str else f"{sender} wrote:"

    inbound_text = (
        getattr(inbound_email, "body", "")
        or getattr(inbound_email, "clean_body", "")
        or ""
    ).strip()

    if not inbound_text:
        return agent_text, agent_html

    # Plain text quoted chain: prefix lines with '> '
    quoted_lines = [f"> {line}" if line else ">" for line in inbound_text.split("\n")]
    plain_chain = f"\n\n{header_line}\n" + "\n".join(quoted_lines)
    full_plain_text = f"{agent_text}{plain_chain}".strip()

    # HTML quoted chain: blockquote
    inbound_html = getattr(inbound_email, "html_body", None)
    if not inbound_html and inbound_text:
        inbound_html = "<br>".join(html.escape(line) for line in inbound_text.split("\n"))

    quoted_html_content = inbound_html or html.escape(inbound_text)
    html_chain = (
        f'<br><br>\n'
        f'<div class="brainsos-quote" style="border-left: 2px solid #d1d5db; padding-left: 12px; margin-left: 0; color: #4b5563;">\n'
        f'  <p style="color: #6b7280; margin: 0 0 8px 0; font-size: 13px;">{html.escape(header_line)}</p>\n'
        f'  <div style="font-size: 13px; line-height: 1.5;">\n{quoted_html_content}\n  </div>\n'
        f'</div>'
    )

    if "</body>" in agent_html.lower():
        idx = agent_html.lower().rfind("</body>")
        full_html = agent_html[:idx] + f"\n{html_chain}\n" + agent_html[idx:]
    else:
        full_html = f"{agent_html}{html_chain}"

    return full_plain_text, full_html
