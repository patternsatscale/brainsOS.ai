#!/usr/bin/env python3
"""brainsOS: Editable Markdown 5-Email Onboarding Seeder (#332 / #357 / #359).

Loads onboarding email templates from Markdown files (`config/default_emails/*.md`
or live overrides in `${BRAINSOS_DATA_DIR}/settings/emails/*.md` /
`BRAINSOS_EMAIL_TEMPLATES_DIR`), renders both clean plain-text and high-contrast
dark-mode HTML bodies, and seeds them into the administrator and superuser
Maildir inboxes with deterministic Message-IDs
(<brainsos-welcome-1@{mail_domain}> .. <brainsos-welcome-5@{mail_domain}>).
"""

import argparse
import glob
import html
import os
import re
import smtplib
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OnboardingEmailSpec:
    index: int
    id: str
    sender_name: str
    sender_local: str
    reply_to_user: str
    subject: str
    preheader: str
    badge: str
    accent: str
    footer: str
    age_minutes: int
    message_id: str
    text_body: str
    html_body: str
    timestamp: float

    @property
    def from_name(self) -> str:
        return self.sender_name

    @property
    def from_user(self) -> str:
        return self.sender_local

    @property
    def text(self) -> str:
        return self.text_body

    @property
    def html(self) -> str:
        return self.html_body

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "id": self.id,
            "from_name": self.sender_name,
            "from_user": self.sender_local,
            "sender_name": self.sender_name,
            "sender_local": self.sender_local,
            "reply_to_user": self.reply_to_user,
            "subject": self.subject,
            "preheader": self.preheader,
            "badge": self.badge,
            "accent": self.accent,
            "footer": self.footer,
            "age_minutes": self.age_minutes,
            "message_id": self.message_id,
            "text": self.text_body,
            "text_body": self.text_body,
            "html": self.html_body,
            "html_body": self.html_body,
            "timestamp": self.timestamp,
        }

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.to_dict()

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()


def parse_env(env_path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    if not env_path.is_file():
        return vals
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def discover_email_markdown_files(
    repo_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> list[Path]:
    """Discover onboarding Markdown files from override dirs or config/default_emails/."""
    resolved_root = repo_root or Path(__file__).resolve().parents[2]
    resolved_env = env if env is not None else parse_env(resolved_root / ".env")

    candidates: list[Path] = []

    custom_dir = os.environ.get("BRAINSOS_EMAIL_TEMPLATES_DIR") or resolved_env.get(
        "BRAINSOS_EMAIL_TEMPLATES_DIR"
    )
    if custom_dir:
        candidates.append(
            Path(custom_dir)
            if os.path.isabs(custom_dir)
            else (resolved_root / custom_dir)
        )

    data_dir_raw = (
        os.environ.get("BRAINSOS_DATA_DIR")
        or resolved_env.get("BRAINSOS_DATA_DIR")
        or str(resolved_root / "data")
    )
    data_dir = (
        Path(data_dir_raw)
        if os.path.isabs(data_dir_raw)
        else (resolved_root / data_dir_raw)
    )
    candidates.append(data_dir / "settings" / "emails")
    candidates.append(resolved_root / "config" / "default_emails")

    for directory in candidates:
        if directory.is_dir():
            md_files = sorted(p for p in directory.glob("*.md") if p.is_file())
            if md_files:
                return md_files

    return []


def parse_markdown_email(raw_text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter between `---` lines and return (meta, markdown_body)."""
    lines = raw_text.splitlines()
    meta: dict[str, str] = {}
    body_start = 0

    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                body_start = idx + 1
                break
            line = lines[idx].strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")

    body = "\n".join(lines[body_start:]).strip()
    return meta, body


_PLACEHOLDER_RE = re.compile(
    r"\{(domain|local_domain|user|base_url|unit_name|portal_domain|mail_domain|recipient_name|recipient_user)\}"
)


def _substitute_placeholders(text: str, context: dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: context.get(m.group(1), m.group(0)), text)


def _header_gradient_for_accent(accent_color: str) -> str:
    accent = accent_color.strip().lower()
    gradients = {
        "#a855f7": "linear-gradient(135deg, #4c1d95 0%, #0f172a 100%)",
        "#ec4899": "linear-gradient(135deg, #831843 0%, #0f172a 100%)",
        "#10b981": "linear-gradient(135deg, #064e3b 0%, #0f172a 100%)",
        "#f97316": "linear-gradient(135deg, #7c2d12 0%, #0f172a 100%)",
        "#38bdf8": "linear-gradient(135deg, #0f766e 0%, #0f172a 100%)",
        "#00f2fe": "linear-gradient(135deg, #0f766e 0%, #0f172a 100%)",
    }
    return gradients.get(accent, "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)")


def _wrap_email_html(
    badge: str,
    title: str,
    subtitle: str,
    inner_html: str,
    accent_color: str = "#38bdf8",
    header_gradient: str | None = None,
    preheader: str = "",
    footer: str = "",
) -> str:
    resolved_gradient = header_gradient or _header_gradient_for_accent(accent_color)
    preheader_html = ""
    if preheader:
        escaped_pre = html.escape(preheader)
        preheader_html = (
            f'<div style="display:none;font-size:1px;color:#0b0f19;line-height:1px;'
            f'max-height:0px;max-width:0px;opacity:0;overflow:hidden;">{escaped_pre}</div>'
        )
    footer_html = ""
    if footer:
        escaped_footer = html.escape(footer)
        footer_html = (
            f'<div style="padding: 14px 28px; background-color: #090d16; '
            f'border-top: 1px solid #1e293b; color: #94a3b8; font-size: 12px; text-align: center;">'
            f"{escaped_footer}</div>"
        )
    return f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #f8fafc; background-color: #0b0f19; padding: 24px; line-height: 1.65; margin: 0;">
  {preheader_html}
  <div style="max-width: 700px; margin: 0 auto; background-color: #0f172a; border: 1px solid #334155; border-radius: 12px; overflow: hidden;">
    <div style="background: {resolved_gradient}; padding: 24px 28px; border-bottom: 1px solid #334155;">
      <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: {html.escape(accent_color)}; margin-bottom: 4px;">
        {html.escape(badge)}
      </div>
      <h1 style="margin: 0; font-size: 22px; font-weight: 700; color: #f8fafc;">
        {title}
      </h1>
      <p style="margin: 6px 0 0 0; font-size: 14px; color: #e2e8f0;">
        {html.escape(subtitle)}
      </p>
    </div>
    <div style="padding: 28px; color: #f8fafc; font-size: 14px;">
      {inner_html}
    </div>
    {footer_html}
  </div>
</body>
</html>
"""


def _wrap_card(
    badge: str,
    title: str,
    subtitle: str,
    inner_html: str,
    accent_color: str = "#38bdf8",
    header_gradient: str = "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)",
) -> str:
    """Backward-compatible wrapper around _wrap_email_html."""
    return _wrap_email_html(
        badge=badge,
        title=title,
        subtitle=subtitle,
        inner_html=inner_html,
        accent_color=accent_color,
        header_gradient=header_gradient,
    )


_CODE_SPAN_STYLE = (
    "color: #38bdf8; background-color: #1e293b; padding: 2px 6px; "
    "border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 13px;"
)


def _render_inline_markdown_html(text: str, accent_color: str = "#38bdf8") -> str:
    """Render inline Markdown (`code`, [link](url), **bold**, *italic*) safely to HTML."""
    tokens: list[str] = []

    def _stash(fragment: str) -> str:
        idx = len(tokens)
        tokens.append(fragment)
        return f"\x00TOK{idx}\x00"

    # 1. Inline code: `...`
    def _repl_code(m: re.Match[str]) -> str:
        code_txt = html.escape(m.group(1))
        return _stash(f'<code style="{_CODE_SPAN_STYLE}">{code_txt}</code>')

    text = re.sub(r"`([^`]+)`", _repl_code, text)

    # 2. Links: [label](url)
    def _repl_link(m: re.Match[str]) -> str:
        label_raw = m.group(1)
        url_raw = html.escape(m.group(2), quote=True)
        label_html = _render_inline_markdown_html(label_raw, accent_color=accent_color)
        return _stash(
            f'<a href="{url_raw}" style="color: #38bdf8; font-weight: 600; text-decoration: none;">{label_html}</a>'
        )

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _repl_link, text)

    # 3. Escape remaining HTML characters
    escaped = html.escape(text)

    # 4. Bold: **...**
    escaped = re.sub(
        r"\*\*([^*]+)\*\*",
        r'<strong style="color: #ffffff;">\1</strong>',
        escaped,
    )

    # 5. Italic: *...*
    escaped = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)",
        r'<em style="color: #f8fafc;">\1</em>',
        escaped,
    )

    # Restore stashed tokens
    for idx, tok in enumerate(tokens):
        escaped = escaped.replace(f"\x00TOK{idx}\x00", tok)

    return escaped


def _render_inline_markdown_text(text: str) -> str:
    """Convert inline Markdown into clean readable plain text."""
    # Convert [label](url) -> label (url) unless label already contains url or mailto:
    def _repl_link(m: re.Match[str]) -> str:
        label = m.group(1).strip()
        url = m.group(2).strip()
        clean_url = url[7:] if url.startswith("mailto:") else url
        if clean_url in label or label in clean_url:
            return label
        return f"{label} ({clean_url})"

    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _repl_link, text)
    out = re.sub(r"`([^`]+)`", r"\1", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", out)
    return out


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_divider(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(bool(re.match(r"^:?-{2,}:?$", c)) for c in cells)


def render_markdown_to_html(
    md_body: str,
    accent_color: str = "#38bdf8",
) -> tuple[str, str]:
    """Convert Markdown body to (hero_title_html, inner_body_html)."""
    lines = md_body.splitlines()
    hero_title = ""
    blocks: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        raw_line = lines[i]
        stripped = raw_line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block: ```lang ... ```
        if stripped.startswith("```"):
            fence_lang = stripped[3:].strip().lower()
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1  # skip closing ```
            code_escaped = html.escape("\n".join(code_lines))
            if fence_lang == "prompt":
                blocks.append(
                    f'<div style="background-color: #1e293b; border: 1px solid {html.escape(accent_color)}; '
                    f'border-radius: 8px; padding: 14px 16px; margin: 16px 0;">'
                    f'<div style="font-size: 11px; font-weight: 700; text-transform: uppercase; '
                    f'letter-spacing: 0.08em; color: {html.escape(accent_color)}; margin-bottom: 8px;">'
                    f"📋 Copy-Paste Prompt</div>"
                    f'<pre style="margin: 0; white-space: pre-wrap; word-break: break-word; '
                    f"font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #f8fafc; "
                    f'line-height: 1.55;">{code_escaped}</pre>'
                    f"</div>"
                )
            else:
                blocks.append(
                    f'<pre style="background-color: #1e293b; border: 1px solid #334155; '
                    f"border-radius: 8px; padding: 14px 16px; margin: 16px 0; overflow-x: auto; "
                    f"font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #e2e8f0; "
                    f'line-height: 1.55;"><code>{code_escaped}</code></pre>'
                )
            continue

        # Heading 1: # Title
        if stripped.startswith("# ") and not stripped.startswith("## "):
            h1_text = stripped[2:].strip()
            rendered_h1 = _render_inline_markdown_html(h1_text, accent_color=accent_color)
            if not hero_title:
                hero_title = rendered_h1
            else:
                blocks.append(
                    f'<h2 style="margin: 20px 0 10px 0; font-size: 18px; font-weight: 700; color: #f8fafc;">'
                    f"{rendered_h1}</h2>"
                )
            i += 1
            continue

        # Heading 2: ## Section
        if stripped.startswith("## ") and not stripped.startswith("### "):
            h2_text = stripped[3:].strip()
            rendered_h2 = _render_inline_markdown_html(h2_text, accent_color=accent_color)
            blocks.append(
                f'<h3 style="margin: 22px 0 10px 0; font-size: 16px; font-weight: 700; '
                f'color: #f8fafc; border-bottom: 1px solid #1e293b; padding-bottom: 6px;">'
                f"{rendered_h2}</h3>"
            )
            i += 1
            continue

        # Heading 3: ### Subsection
        if stripped.startswith("### "):
            h3_text = stripped[4:].strip()
            rendered_h3 = _render_inline_markdown_html(h3_text, accent_color=accent_color)
            blocks.append(
                f'<h4 style="margin: 18px 0 8px 0; font-size: 14px; font-weight: 700; color: #f8fafc;">'
                f"{rendered_h3}</h4>"
            )
            i += 1
            continue

        # Blockquote / Callout: > ...
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                q_line = re.sub(r"^>\s?", "", lines[i].strip())
                quote_lines.append(q_line)
                i += 1

            callout_title = ""
            if quote_lines:
                m_alert = re.match(
                    r"^\[!(TIP|NOTE|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$",
                    quote_lines[0],
                    flags=re.IGNORECASE,
                )
                if m_alert:
                    kind = m_alert.group(1).upper()
                    custom_title = m_alert.group(2).strip()
                    icon_map = {
                        "TIP": "💡",
                        "NOTE": "ℹ️",
                        "IMPORTANT": "⚡",
                        "WARNING": "⚠️",
                        "CAUTION": "🛑",
                    }
                    icon = icon_map.get(kind, "💡")
                    callout_title = f"{icon} {custom_title or kind.title()}"
                    quote_lines = quote_lines[1:]

            body_html = "<br>".join(
                _render_inline_markdown_html(ql, accent_color=accent_color)
                for ql in quote_lines
                if ql.strip()
            )
            title_html = (
                f'<div style="font-weight: 700; color: #f8fafc; margin-bottom: 6px;">'
                f"{_render_inline_markdown_html(callout_title, accent_color=accent_color)}</div>"
                if callout_title
                else ""
            )
            blocks.append(
                f'<div style="background-color: #1e293b; padding: 14px 16px; border-radius: 8px; '
                f"border: 1px solid #334155; border-left: 4px solid {html.escape(accent_color)}; "
                f'margin: 16px 0; color: #e2e8f0;">{title_html}<div>{body_html}</div></div>'
            )
            continue

        # Markdown Table: | Col 1 | Col 2 |
        if (
            "|" in stripped
            and stripped.startswith("|")
            and (i + 1) < n
            and _is_table_divider(lines[i + 1])
        ):
            headers = _split_table_row(lines[i])
            i += 2  # skip header + divider
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_table_row(lines[i]))
                i += 1

            th_html = "".join(
                f'<th style="padding: 9px 8px; color: #f8fafc; font-weight: 700;">'
                f"{_render_inline_markdown_html(h, accent_color=accent_color)}</th>"
                for h in headers
            )
            trs_html: list[str] = []
            for r_idx, row in enumerate(rows):
                border_style = (
                    "border-bottom: 1px solid #1e293b;"
                    if r_idx < len(rows) - 1
                    else ""
                )
                tds = "".join(
                    f'<td style="padding: 9px 8px; color: #e2e8f0;">'
                    f"{_render_inline_markdown_html(cell, accent_color=accent_color)}</td>"
                    for cell in row
                )
                trs_html.append(f'<tr style="{border_style}">{tds}</tr>')

            blocks.append(
                f'<table style="width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px;">'
                f'<thead><tr style="border-bottom: 1px solid #334155; text-align: left; color: #f8fafc;">'
                f"{th_html}</tr></thead>"
                f'<tbody>{"".join(trs_html)}</tbody></table>'
            )
            continue

        # Unordered list: - item or * item
        if re.match(r"^[-*]\s+", stripped):
            items: list[str] = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                item_txt = re.sub(r"^[-*]\s+", "", lines[i].strip())
                items.append(
                    f'<li style="margin-bottom: 6px;">'
                    f"{_render_inline_markdown_html(item_txt, accent_color=accent_color)}</li>"
                )
                i += 1
            blocks.append(
                f'<ul style="margin: 12px 0; padding-left: 20px; color: #e2e8f0;">'
                f'{"".join(items)}</ul>'
            )
            continue

        # Ordered list: 1. item
        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                item_txt = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append(
                    f'<li style="margin-bottom: 8px;">'
                    f"{_render_inline_markdown_html(item_txt, accent_color=accent_color)}</li>"
                )
                i += 1
            blocks.append(
                f'<ol style="margin: 12px 0; padding-left: 20px; color: #e2e8f0;">'
                f'{"".join(items)}</ol>'
            )
            continue

        # Standard paragraph (merge consecutive plain lines)
        para_lines: list[str] = []
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", ">", "```", "|"))
            and not re.match(r"^([-*]|\d+\.)\s+", lines[i].strip())
        ):
            para_lines.append(lines[i].strip())
            i += 1
        para_html = "<br>".join(
            _render_inline_markdown_html(pl, accent_color=accent_color)
            for pl in para_lines
        )
        blocks.append(f'<p style="color: #e2e8f0; margin: 0 0 14px 0;">{para_html}</p>')

    return hero_title, "\n".join(blocks)


def render_markdown_to_text(md_body: str) -> str:
    """Convert Markdown body into a clean, human-readable plain-text representation."""
    lines = md_body.splitlines()
    out_blocks: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append("  " + lines[i])
                i += 1
            if i < n:
                i += 1
            out_blocks.append("\n".join(code_lines))
            continue

        # Headings
        if stripped.startswith("#"):
            heading_txt = _render_inline_markdown_text(re.sub(r"^#+\s*", "", stripped))
            out_blocks.append(heading_txt)
            i += 1
            continue

        # Blockquote / Callout
        if stripped.startswith(">"):
            q_lines: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                ql = re.sub(r"^>\s?", "", lines[i].strip())
                m_alert = re.match(
                    r"^\[!(TIP|NOTE|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$",
                    ql,
                    flags=re.IGNORECASE,
                )
                if m_alert:
                    kind = m_alert.group(1).upper()
                    title = m_alert.group(2).strip() or kind
                    q_lines.append(f"[{kind}] {title}")
                else:
                    q_lines.append(_render_inline_markdown_text(ql))
                i += 1
            out_blocks.append("\n".join(f"  | {ql}" for ql in q_lines if ql))
            continue

        # Markdown Table
        if (
            "|" in stripped
            and stripped.startswith("|")
            and (i + 1) < n
            and _is_table_divider(lines[i + 1])
        ):
            headers = [
                _render_inline_markdown_text(c) for c in _split_table_row(lines[i])
            ]
            i += 2
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(
                    [
                        _render_inline_markdown_text(c)
                        for c in _split_table_row(lines[i])
                    ]
                )
                i += 1
            col_count = max([len(headers)] + [len(r) for r in rows])
            widths = [0] * col_count
            for r in [headers] + rows:
                for c_idx, cell in enumerate(r):
                    widths[c_idx] = max(widths[c_idx], len(cell))
            fmt_row = lambda r: "  | ".join(
                (r[c_idx] if c_idx < len(r) else "").ljust(widths[c_idx])
                for c_idx in range(col_count)
            ).rstrip()
            table_lines = [
                fmt_row(headers),
                "-+-".join("-" * w for w in widths),
            ] + [fmt_row(r) for r in rows]
            out_blocks.append("\n".join(table_lines))
            continue

        # Lists
        if re.match(r"^([-*]|\d+\.)\s+", stripped):
            list_lines: list[str] = []
            while i < n and re.match(r"^([-*]|\d+\.)\s+", lines[i].strip()):
                list_lines.append(_render_inline_markdown_text(lines[i].strip()))
                i += 1
            out_blocks.append("\n".join(list_lines))
            continue

        # Paragraph
        para_lines: list[str] = []
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", ">", "```", "|"))
            and not re.match(r"^([-*]|\d+\.)\s+", lines[i].strip())
        ):
            para_lines.append(_render_inline_markdown_text(lines[i].strip()))
            i += 1
        out_blocks.append("\n".join(para_lines))

    return "\n\n".join(out_blocks).strip() + "\n"


def build_onboarding_messages(
    domain: str = "localhost",
    local_domain: str = "brainsos.local",
    user: str = "admin",
    *,
    recipient_name: str | None = None,
    unit_name: str = "Enterprise Agent Box",
    repo_root: Path | None = None,
    base_ts: float | None = None,
) -> list[OnboardingEmailSpec]:
    """Load and render the 5 Markdown onboarding emails for the given domain and user."""
    portal_domain = domain[5:] if domain.startswith("mail.") else domain
    mail_domain = local_domain[5:] if local_domain.startswith("mail.") else local_domain
    if portal_domain.startswith(("http://", "https://")):
        base_url = portal_domain.rstrip("/")
        clean_domain = re.sub(r"^https?://", "", base_url)
    else:
        clean_domain = portal_domain.rstrip("/")
        base_url = f"https://{clean_domain}"

    display_user = recipient_name or user
    now_ts = float(base_ts if base_ts is not None else time.time())

    context = {
        "domain": clean_domain,
        "local_domain": mail_domain,
        "user": display_user,
        "base_url": base_url,
        "unit_name": unit_name,
        "portal_domain": clean_domain,
        "mail_domain": mail_domain,
        "recipient_name": display_user,
        "recipient_user": user,
    }

    md_files = discover_email_markdown_files(repo_root=repo_root)
    specs: list[OnboardingEmailSpec] = []

    for idx, md_path in enumerate(md_files, start=1):
        raw_content = md_path.read_text(encoding="utf-8")
        meta, raw_body = parse_markdown_email(raw_content)

        sub_meta = {k: _substitute_placeholders(v, context) for k, v in meta.items()}
        sub_body = _substitute_placeholders(raw_body, context)

        email_id = sub_meta.get("id") or md_path.stem
        sender_name = sub_meta.get("from_name") or "brainsOS"
        sender_local = sub_meta.get("from_user") or "system"
        reply_to_user = sub_meta.get("reply_to_user") or sender_local
        subject = sub_meta.get("subject") or f"brainsOS Onboarding #{idx}"
        preheader = sub_meta.get("preheader") or ""
        badge = sub_meta.get("badge") or f"{unit_name} • Onboarding"
        accent = sub_meta.get("accent") or "#38bdf8"
        footer = (
            sub_meta.get("footer")
            or f"Sent by {sender_name} ({sender_local}@{mail_domain})"
        )
        try:
            age_minutes = int(sub_meta.get("age_minutes", str((idx - 1) * 4)))
        except ValueError:
            age_minutes = (idx - 1) * 4

        hero_title, inner_html = render_markdown_to_html(sub_body, accent_color=accent)
        card_title = hero_title or html.escape(subject)
        subtitle = preheader or f"From {sender_name} <{sender_local}@{mail_domain}>"

        full_html = _wrap_email_html(
            badge=badge,
            title=card_title,
            subtitle=subtitle,
            inner_html=inner_html,
            accent_color=accent,
            preheader=preheader,
            footer=footer,
        )
        plain_text = render_markdown_to_text(sub_body)
        if footer:
            plain_text = f"{plain_text}\n--\n{footer}\n"

        specs.append(
            OnboardingEmailSpec(
                index=idx,
                id=email_id,
                sender_name=sender_name,
                sender_local=sender_local,
                reply_to_user=reply_to_user,
                subject=subject,
                preheader=preheader,
                badge=badge,
                accent=accent,
                footer=footer,
                age_minutes=age_minutes,
                message_id=f"<brainsos-welcome-{idx}@{mail_domain}>",
                text_body=plain_text,
                html_body=full_html,
                timestamp=now_ts - (age_minutes * 60.0),
            )
        )

    return specs


def build_onboarding_specs(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    portal_domain: str,
    unit_name: str = "Enterprise Agent Box",
    base_ts: float | None = None,
    repo_root: Path | None = None,
) -> list[OnboardingEmailSpec]:
    """Backward-compatible wrapper around build_onboarding_messages."""
    return build_onboarding_messages(
        domain=portal_domain,
        local_domain=mail_domain,
        user=recipient_user,
        recipient_name=recipient_name or recipient_user,
        unit_name=unit_name,
        repo_root=repo_root,
        base_ts=base_ts,
    )


def render_welcome_html(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str = "Enterprise Agent Box",
) -> str:
    """Backward-compatible helper returning the primary Welcome OS cheat-sheet HTML."""
    portal_domain = mail_domain[5:] if mail_domain.startswith("mail.") else mail_domain
    specs = build_onboarding_specs(
        recipient_user=recipient_user,
        recipient_name=recipient_name,
        mail_domain=mail_domain,
        portal_domain=portal_domain,
        unit_name=unit_name,
    )
    return specs[-1].html_body


def format_rfc822_from_spec(
    spec: OnboardingEmailSpec,
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
) -> str:
    date_hdr = formatdate(spec.timestamp, localtime=False)
    boundary = f"===============brainsos-welcome-{spec.index}=="
    headers = [
        f'From: "{spec.sender_name}" <{spec.sender_local}@{mail_domain}>',
        f'Reply-To: "{spec.sender_name}" <{spec.reply_to_user}@{mail_domain}>',
        f'To: "{recipient_name or recipient_user}" <{recipient_user}@{mail_domain}>',
        f"Subject: {spec.subject}",
        f"Date: {date_hdr}",
        f"Message-ID: {spec.message_id}",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/alternative; boundary="{boundary}"',
        "",
        f"--{boundary}",
        'Content-Type: text/plain; charset="utf-8"',
        "Content-Transfer-Encoding: 8bit",
        "",
        spec.text_body,
        f"--{boundary}",
        'Content-Type: text/html; charset="utf-8"',
        "Content-Transfer-Encoding: 8bit",
        "",
        spec.html_body,
        f"--{boundary}--",
        "",
    ]
    return "\n".join(headers)


def build_rfc822_message(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str = "Enterprise Agent Box",
) -> str:
    """Backward-compatible helper returning the primary Welcome OS RFC822 message."""
    portal_domain = mail_domain[5:] if mail_domain.startswith("mail.") else mail_domain
    specs = build_onboarding_specs(
        recipient_user=recipient_user,
        recipient_name=recipient_name,
        mail_domain=mail_domain,
        portal_domain=portal_domain,
        unit_name=unit_name,
    )
    return format_rfc822_from_spec(specs[-1], recipient_user, recipient_name, mail_domain)


def _find_matching_messages(
    directory: Path,
    file_prefix: str,
    msg_id_token: str,
) -> list[Path]:
    matches: list[Path] = []
    for p in sorted(directory.glob(f"{file_prefix}*")):
        if p.is_file():
            matches.append(p)
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p in matches:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:2048]
        except OSError:
            continue
        if msg_id_token in head:
            matches.append(p)
    return matches


def seed_maildir(
    vmail_dir: Path,
    mailbox_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str,
    portal_domain: str | None = None,
    repo_root: Path | None = None,
) -> list[Path]:
    resolved_portal_domain = portal_domain or (
        mail_domain[5:] if mail_domain.startswith("mail.") else mail_domain
    )
    maildir_root = vmail_dir / mailbox_user / "Maildir"
    cur_dir = maildir_root / "cur"
    new_dir = maildir_root / "new"
    tmp_dir = maildir_root / "tmp"
    cur_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Remove legacy single-welcome-email files so there are no stale duplicates
    legacy_patterns = [
        "1730937600.M000001P1.brainsos*",
        "1794074500.M000001P1.brainsos*",
    ]
    for pat in legacy_patterns:
        for old_f in glob.glob(str(cur_dir / pat)) + glob.glob(str(new_dir / pat)):
            try:
                os.remove(old_f)
            except OSError:
                pass

    specs = build_onboarding_specs(
        recipient_user=mailbox_user,
        recipient_name=recipient_name,
        mail_domain=mail_domain,
        portal_domain=resolved_portal_domain,
        unit_name=unit_name,
        repo_root=repo_root,
    )

    written_paths: list[Path] = []
    for spec in specs:
        # Reverse-order filename prefix (1794074505 down to 1794074501) so lexical,
        # mtime, and Date header sorting all place Email #1 first in the inbox.
        seq_epoch = 1794074506 - spec.index
        file_prefix = f"{seq_epoch}.M00000{spec.index}P1.brainsos"
        msg_id_token = f"<brainsos-welcome-{spec.index}@"

        cur_matches = _find_matching_messages(cur_dir, file_prefix, msg_id_token)
        new_matches = _find_matching_messages(new_dir, file_prefix, msg_id_token)

        if cur_matches:
            target_path = cur_matches[0]
            extras = cur_matches[1:] + new_matches
        else:
            target_path = new_dir / file_prefix
            extras = [p for p in new_matches if p != target_path]

        for extra in extras:
            try:
                os.remove(extra)
            except OSError:
                pass

        msg_str = format_rfc822_from_spec(spec, mailbox_user, recipient_name, mail_domain)
        target_path.write_text(msg_str, encoding="utf-8")
        try:
            os.utime(target_path, (spec.timestamp, spec.timestamp))
        except OSError:
            pass
        written_paths.append(target_path)

    # Clear Dovecot index cache if permitted so updated subjects/bodies appear immediately
    cache_file = maildir_root / "dovecot.index.cache"
    if cache_file.exists():
        try:
            cache_file.unlink()
        except OSError:
            pass

    return written_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed 5 editable Markdown onboarding emails into brainsOS Maildir inboxes"
    )
    parser.add_argument("--repo-root", default=None, help="Repository root path")
    parser.add_argument("--domain", default=None, help="Override local mail/portal domain")
    parser.add_argument("--user", default=None, help="Override superuser username")
    parser.add_argument("--name", default=None, help="Override superuser display name")
    parser.add_argument("--vmail-dir", default=None, help="Override vmail directory path")
    parser.add_argument("--smtp", action="store_true", help="Also attempt SMTP delivery to localhost:25")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    env = parse_env(repo_root / ".env")

    raw_domain = (
        args.domain
        or env.get("BRAINSOS_LOCAL_DOMAIN")
        or env.get("BRAINSOS_DOMAIN")
        or env.get("BRAINSOS_MAIL_DOMAIN")
        or "local.brainsos.ai"
    )
    mail_domain = raw_domain[5:] if raw_domain.startswith("mail.") else raw_domain
    portal_domain = (
        args.domain
        or env.get("BRAINSOS_DOMAIN")
        or env.get("BRAINSOS_LOCAL_DOMAIN")
        or mail_domain
    )
    if portal_domain.startswith("mail."):
        portal_domain = portal_domain[5:]

    unit_name = env.get("BRAINSOS_UNIT_NAME") or "Enterprise Agent Box"
    su_user = (
        args.user
        or env.get("BRAINSOS_SUPERUSER_USERNAME")
        or env.get("BRAINSOS_ADMIN_USERNAME")
        or "admin"
    )
    su_name = args.name or env.get("BRAINSOS_SUPERUSER_NAME") or "System Administrator"

    data_dir_raw = env.get("BRAINSOS_DATA_DIR") or str(repo_root / "data")
    data_dir = Path(data_dir_raw) if os.path.isabs(data_dir_raw) else (repo_root / data_dir_raw)

    comms_dir_raw = env.get("BRAINSOS_COMMS_DIR") or str(data_dir / "comms")
    comms_dir = Path(comms_dir_raw) if os.path.isabs(comms_dir_raw) else (repo_root / comms_dir_raw)

    if args.vmail_dir:
        vmail_dirs = [Path(args.vmail_dir)]
    else:
        vmail_dirs = [comms_dir / "email" / "vmail"]
        legacy_vmail = data_dir / "mail" / "vmail"
        if legacy_vmail.exists() and legacy_vmail not in vmail_dirs:
            vmail_dirs.append(legacy_vmail)

    targets = ["admin"]
    if su_user and su_user not in targets:
        targets.append(su_user)

    for vmail_dir in vmail_dirs:
        for box in targets:
            box_name = su_name if box == su_user else "System Administrator"
            try:
                seed_maildir(
                    vmail_dir=vmail_dir,
                    mailbox_user=box,
                    recipient_name=box_name,
                    mail_domain=mail_domain,
                    unit_name=unit_name,
                    portal_domain=portal_domain,
                    repo_root=repo_root,
                )
            except PermissionError:
                pass

    if args.smtp:
        specs = build_onboarding_specs(
            recipient_user=su_user,
            recipient_name=su_name,
            mail_domain=mail_domain,
            portal_domain=portal_domain,
            unit_name=unit_name,
            repo_root=repo_root,
        )
        for spec in reversed(specs):
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = spec.subject
                msg["From"] = f'"{spec.sender_name}" <{spec.sender_local}@{mail_domain}>'
                msg["Reply-To"] = f'"{spec.sender_name}" <{spec.reply_to_user}@{mail_domain}>'
                msg["To"] = f'"{su_name}" <{su_user}@{mail_domain}>'
                msg["Date"] = formatdate(spec.timestamp, localtime=False)
                msg["Message-ID"] = spec.message_id
                msg.attach(MIMEText(spec.text_body, "plain", "utf-8"))
                msg.attach(MIMEText(spec.html_body, "html", "utf-8"))
                with smtplib.SMTP("127.0.0.1", 25, timeout=3) as s:
                    s.sendmail(
                        f"{spec.sender_local}@{mail_domain}",
                        [f"{su_user}@{mail_domain}"],
                        msg.as_string(),
                    )
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
