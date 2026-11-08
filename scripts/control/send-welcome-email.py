#!/usr/bin/env python3
"""brainsOS: Interactive 5-Email Onboarding Seeder (#332 / #357).

Seeds or updates 5 friendly, useful, slightly silly, and interactive onboarding
emails in the administrator and superuser Maildir inboxes with high-contrast
typography (#f8fafc, #e2e8f0, #cbd5e1) on dark cards and deterministic
Message-IDs (<brainsos-welcome-1@{mail_domain}> .. <brainsos-welcome-5@{mail_domain}>).
"""

import argparse
import glob
import os
import smtplib
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path


@dataclass(frozen=True)
class OnboardingEmailSpec:
    index: int
    sender_name: str
    sender_local: str
    subject: str
    message_id: str
    html_body: str
    timestamp: float


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


def _wrap_card(
    badge: str,
    title: str,
    subtitle: str,
    inner_html: str,
    accent_color: str = "#38bdf8",
    header_gradient: str = "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)",
) -> str:
    return f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #f8fafc; background-color: #0b0f19; padding: 24px; line-height: 1.65; margin: 0;">
  <div style="max-width: 700px; margin: 0 auto; background-color: #0f172a; border: 1px solid #334155; border-radius: 12px; overflow: hidden;">
    <div style="background: {header_gradient}; padding: 24px 28px; border-bottom: 1px solid #334155;">
      <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: {accent_color}; margin-bottom: 4px;">
        {badge}
      </div>
      <h2 style="margin: 0; font-size: 22px; font-weight: 700; color: #f8fafc;">
        {title}
      </h2>
      <p style="margin: 6px 0 0 0; font-size: 14px; color: #e2e8f0;">
        {subtitle}
      </p>
    </div>
    <div style="padding: 28px; color: #f8fafc; font-size: 14px;">
      {inner_html}
    </div>
  </div>
</body>
</html>
"""


def build_onboarding_specs(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    portal_domain: str,
    unit_name: str = "Enterprise Agent Box",
    base_ts: float | None = None,
) -> list[OnboardingEmailSpec]:
    display_greeting = recipient_name or recipient_user
    now_ts = float(base_ts if base_ts is not None else time.time())
    code_style = (
        "color: #38bdf8; background-color: #1e293b; padding: 2px 6px; "
        "border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 13px;"
    )
    box_style = (
        "background-color: #1e293b; padding: 14px 16px; border-radius: 8px; "
        "border: 1px solid #334155; margin: 16px 0; color: #e2e8f0;"
    )

    # -------------------------------------------------------------------------
    # Email 1 (Newest / Top of Inbox): Robert Bawtford introduction
    # -------------------------------------------------------------------------
    email1_inner = f"""
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Good day, <strong style="color: #ffffff;">{display_greeting}</strong>! 🎩
      </p>
      <p style="color: #e2e8f0;">
        Allow me to adjust my digital cufflinks and introduce myself: I am <strong style="color: #ffffff;">Robert Bawtford</strong> (<a href="mailto:bawtford@{mail_domain}" style="color: #38bdf8; text-decoration: none;">bawtford@{mail_domain}</a>), your resident autonomous research agent, creative director, and gentleman-in-the-loop.
      </p>
      <p style="color: #e2e8f0;">
        Yes, I genuinely live inside this <strong style="color: #ffffff;">{unit_name}</strong> appliance. It is spacious, well-ventilated, and delightfully free of cloud surveillance—though I must apologize for not bringing a silver tray of Earl Grey; the Egress Firewall firmly informed me that porcelain teapots are not an approved MIME type.
      </p>
      <div style="{box_style}">
        <div style="font-weight: 700; color: #f8fafc; margin-bottom: 6px;">How we work together:</div>
        <ul style="margin: 0; padding-left: 20px; color: #e2e8f0;">
          <li style="margin-bottom: 6px;">
            <strong style="color: #ffffff;">Email is my command bus:</strong> Whenever you send or reply to an email at <code style="{code_style}">bawtford@{mail_domain}</code>, your local Postfix/Dovecot pipeline wakes me up, hands me your brief, and delivers my reply straight back to this inbox.
          </li>
          <li style="margin-bottom: 6px;">
            <strong style="color: #ffffff;">Pure Markdown memory (<code style="{code_style}">/memories</code>):</strong> I keep every research note, synthesis brief, and task log in plain, human-auditable Open Knowledge Format (OKF) Markdown under <code style="{code_style}">/memories</code>. No mystery binary blobs, no hidden SQLite databases swept under the rug.
          </li>
          <li>
            <strong style="color: #ffffff;">Full transparency:</strong> You can inspect my persona (<code style="{code_style}">SOUL.md</code>), read my notes in the Code Console (<a href="https://{portal_domain}/editor/" style="color: #38bdf8;">/editor/</a>), or peek at my mailbox anytime under the <em style="color: #ffffff;">Agent Fleet</em> folder on the left.
          </li>
        </ul>
      </div>
      <p style="color: #e2e8f0; margin-bottom: 18px;">
        Whenever you require a research dossier, an architectural critique, or a bit of civilised wit, simply hit <strong style="color: #ffffff;">Reply</strong> or click below:
      </p>
      <p style="margin: 0 0 18px 0;">
        <a href="mailto:bawtford@{mail_domain}?subject=Good%20day%20Bawtford%20%E2%80%94%20Quick%20Research%20Brief&amp;body=Hello%20Bawtford%2C%0A%0APlease%20introduce%20yourself%2C%20summarize%20how%20your%20%2Fmemories%20partition%20works%2C%20and%20give%20me%20a%203-bullet%20status%20report.%0A"
           style="display: inline-block; background-color: #0284c7; color: #ffffff; font-weight: 700; text-decoration: none; padding: 10px 18px; border-radius: 8px; border: 1px solid #38bdf8;">
          ✉️ Email Robert Bawtford (bawtford@{mail_domain})
        </a>
      </p>
      <p style="margin-bottom: 0; color: #cbd5e1; font-size: 13px;">
        At your service,<br>
        <strong style="color: #f8fafc;">Robert Bawtford</strong><br>
        <span style="color: #94a3b8;">Autonomous Research &amp; Creative Orchestrator • <code style="{code_style}">bawtford@{mail_domain}</code></span>
      </p>
    """
    spec1 = OnboardingEmailSpec(
        index=1,
        sender_name="Robert Bawtford",
        sender_local="bawtford",
        subject="🎩 Reporting for duty! (Yes, I actually live inside this box)",
        message_id=f"<brainsos-welcome-1@{mail_domain}>",
        html_body=_wrap_card(
            badge=f"{unit_name} • Resident Agent Introduction",
            title="🎩 Reporting for duty! (Yes, I actually live inside this box)",
            subtitle=f"From Robert Bawtford <bawtford@{mail_domain}> • Sovereign Agent Fleet",
            inner_html=email1_inner,
            accent_color="#38bdf8",
            header_gradient="linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)",
        ),
        timestamp=now_ts,
    )

    # -------------------------------------------------------------------------
    # Email 2 (now - 60s): brainsOS Field Guide — Try This First
    # -------------------------------------------------------------------------
    email2_inner = f"""
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Ready to take your appliance for a spin, <strong style="color: #ffffff;">{display_greeting}</strong>? 🧪
      </p>
      <p style="color: #e2e8f0;">
        The fastest way to experience <strong style="color: #ffffff;">brainsOS</strong> is to click <strong style="color: #ffffff;">Compose</strong> (or <strong style="color: #ffffff;">New Message</strong>) right now and send an email to <a href="mailto:bawtford@{mail_domain}" style="color: #ec4899; font-weight: 600; text-decoration: none;">bawtford@{mail_domain}</a>. Your message stays 100% inside the appliance, triggers the autonomous agent queue, and delivers a researched response right back to your Inbox.
      </p>
      <div style="{box_style}">
        <div style="font-weight: 700; color: #f8fafc; margin-bottom: 10px;">
          📋 Copy-Paste (or Click) One of These Fun Prompts to <code style="{code_style}">bawtford@{mail_domain}</code>:
        </div>
        <ol style="margin: 0; padding-left: 20px; color: #e2e8f0;">
          <li style="margin-bottom: 10px;">
            <strong style="color: #ffffff;">The 7-Layer Box Tour:</strong><br>
            <span style="color: #cbd5e1;">"Hey Bawtford, research how the 7-layer 'Enterprise Agent in a Box' architecture works in brainsOS and explain how each layer keeps an enterprise safe."</span>
          </li>
          <li style="margin-bottom: 10px;">
            <strong style="color: #ffffff;">Guardrails vs. Firewalls Showdown:</strong><br>
            <span style="color: #cbd5e1;">"Compare LiteLLM routing guardrails vs. the Egress Firewall in brainsOS—how do they team up so agents never leak API keys or call unapproved endpoints?"</span>
          </li>
          <li style="margin-bottom: 10px;">
            <strong style="color: #ffffff;">The Rule 1 Haiku Challenge:</strong><br>
            <span style="color: #cbd5e1;">"Write a dramatic haiku about why SQLite .db files are strictly banned in /memories, then explain Rule 1 (Memory Plane Purity) in plain English."</span>
          </li>
          <li>
            <strong style="color: #ffffff;">Sovereign AI Executive Memo:</strong><br>
            <span style="color: #cbd5e1;">"Draft a crisp 5-bullet briefing on why local-first sovereign agents beat opaque cloud SaaS bots, and note what you'd record in /memories."</span>
          </li>
        </ol>
      </div>
      <p style="color: #e2e8f0; margin-bottom: 8px;">
        <strong style="color: #ffffff;">Meet the rest of your on-box Agent Fleet Directory:</strong>
      </p>
      <table style="width: 100%; border-collapse: collapse; margin: 12px 0 18px 0; font-size: 13px;">
        <thead>
          <tr style="border-bottom: 1px solid #334155; text-align: left; color: #f8fafc;">
            <th style="padding: 8px; color: #f8fafc;">Agent</th>
            <th style="padding: 8px; color: #f8fafc;">Address</th>
            <th style="padding: 8px; color: #f8fafc;">Speciality</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">Robert Bawtford</td>
            <td style="padding: 8px;"><a href="mailto:bawtford@{mail_domain}" style="color: #38bdf8; text-decoration: none;">bawtford@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">Autonomous research agent, synthesis &amp; creative orchestration.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">Ping</td>
            <td style="padding: 8px;"><a href="mailto:ping@{mail_domain}" style="color: #38bdf8; text-decoration: none;">ping@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">Zero-GPU instant diagnostic echo &amp; mail-queue latency probe.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">Terrastella</td>
            <td style="padding: 8px;"><a href="mailto:terrastella@{mail_domain}" style="color: #38bdf8; text-decoration: none;">terrastella@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">Primary operations coordinator &amp; executive strategy synthesis.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">Marvin</td>
            <td style="padding: 8px;"><a href="mailto:marvin@{mail_domain}" style="color: #38bdf8; text-decoration: none;">marvin@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">Analytics, systems diagnostics &amp; boundary verification.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">Claude Demo</td>
            <td style="padding: 8px;"><a href="mailto:claude@{mail_domain}" style="color: #38bdf8; text-decoration: none;">claude@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">Claude SDK runner demo for reasoning, writing &amp; banter.</td>
          </tr>
          <tr>
            <td style="padding: 8px; font-weight: 600; color: #f8fafc;">GPT Demo</td>
            <td style="padding: 8px;"><a href="mailto:gpt@{mail_domain}" style="color: #38bdf8; text-decoration: none;">gpt@{mail_domain}</a></td>
            <td style="padding: 8px; color: #e2e8f0;">OpenAI SDK runner demo for rapid drafting &amp; Q&amp;A.</td>
          </tr>
        </tbody>
      </table>
      <p style="font-size: 13px; color: #cbd5e1; margin-bottom: 0;">
        💡 <strong style="color: #f8fafc;">Pro Tip:</strong> Want an instant 1-second sanity check before running a deep research prompt? Send <code style="{code_style}">ping</code> to <a href="mailto:ping@{mail_domain}?subject=Ping%20Check&amp;body=ping" style="color: #38bdf8;">ping@{mail_domain}</a>!
      </p>
    """
    spec2 = OnboardingEmailSpec(
        index=2,
        sender_name="brainsOS Field Guide",
        sender_local="guide",
        subject=f"🧪 Try This First: Email bawtford@{mail_domain} and ask him to research something!",
        message_id=f"<brainsos-welcome-2@{mail_domain}>",
        html_body=_wrap_card(
            badge="Interactive Onboarding • Step 1",
            title=f"🧪 Try This First: Email bawtford@{mail_domain}!",
            subtitle="Test the live autonomous agent loop right from your webmail client",
            inner_html=email2_inner,
            accent_color="#ec4899",
            header_gradient="linear-gradient(135deg, #831843 0%, #0f172a 100%)",
        ),
        timestamp=now_ts - 60.0,
    )

    # -------------------------------------------------------------------------
    # Email 3 (now - 120s): Perimeter Gatekeeper — Identity, Guardrails & Firewalls
    # -------------------------------------------------------------------------
    email3_inner = f"""
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Halt! Who goes there? Oh—it's <strong style="color: #ffffff;">{display_greeting}</strong>. Carry on! 🛡️
      </p>
      <p style="color: #e2e8f0;">
        I'm the <strong style="color: #ffffff;">Perimeter Gatekeeper</strong> (<code style="{code_style}">security@{mail_domain}</code>). Most AI setups hand agents a pile of raw API keys, open internet access, and a polite request to "please behave." In <strong style="color: #ffffff;">brainsOS</strong>, nobody—not even Bawtford in his finest tuxedo—leaves the box without a hall pass.
      </p>
      <div style="{box_style}">
        <div style="margin-bottom: 12px;">
          <strong style="color: #a855f7;">1. Identity Management — Authentik (<a href="https://{portal_domain}/auth/if/admin/#/events/log" style="color: #38bdf8;">/auth/</a> • Alt+7)</strong><br>
          <span style="color: #e2e8f0;">The front-door bouncer. Every operator dashboard is protected by zero-trust Single Sign-On (OAuth2/OIDC + forward-auth) with FIDO2/WebAuthn passkey support and full login event auditing.</span>
        </div>
        <div style="margin-bottom: 12px;">
          <strong style="color: #f59e0b;">2. Routing &amp; Guardrails — LiteLLM (<a href="https://{portal_domain}/ui/" style="color: #38bdf8;">/ui/</a> • Alt+4)</strong><br>
          <span style="color: #e2e8f0;">The air-traffic controller. Agent containers can never call host inference engines directly (Rule 2). Every completion routes through LiteLLM using per-tenant virtual keys, strict monthly budgets, and hardware concurrency serialization (<code style="{code_style}">max_parallel_requests: 1</code>) so unified memory bandwidth never thrashes (Rule 3).</span>
        </div>
        <div style="margin-bottom: 12px;">
          <strong style="color: #10b981;">3. Network Firewalls — Egress Proxy (<a href="https://{portal_domain}/efw/" style="color: #38bdf8;">/efw/</a> • Alt+5)</strong><br>
          <span style="color: #e2e8f0;">The hall-pass inspector. Agent containers hold <strong style="color: #ffffff;">zero ambient GitHub tokens or third-party secrets</strong> (Rule 10). All outbound HTTPS traffic flows through our <code style="{code_style}">mitmproxy</code> Egress Gateway, which verifies container IP identity, injects credentials in transit only for approved hosts, and masks tokens as <code style="{code_style}">[INJECTED_CINDY_TOKEN]</code> in the live traffic UI.</span>
        </div>
        <div>
          <strong style="color: #3b82f6;">4. Telemetry Data — Langfuse (<a href="https://{portal_domain}/langfuse/" style="color: #38bdf8;">/langfuse/</a> • Alt+6)</strong><br>
          <span style="color: #e2e8f0;">The flight data recorder. Every prompt, model call, tool invocation, token count, and latency span is captured via OpenTelemetry so you can audit every decision your agents make.</span>
        </div>
      </div>
      <p style="margin-bottom: 0; font-size: 13px; color: #cbd5e1;">
        🔒 <strong style="color: #f8fafc;">Try it yourself:</strong> After you email <code style="{code_style}">bawtford@{mail_domain}</code>, switch to <strong style="color: #ffffff;">Langfuse (Alt+6)</strong> or <strong style="color: #ffffff;">LiteLLM (Alt+4)</strong> in the left spine to watch the live trace and token accounting!
      </p>
    """
    spec3 = OnboardingEmailSpec(
        index=3,
        sender_name="Perimeter Gatekeeper",
        sender_local="security",
        subject="🛡️ Nobody leaves the box without a hall pass (Identity, Guardrails & Firewalls)",
        message_id=f"<brainsos-welcome-3@{mail_domain}>",
        html_body=_wrap_card(
            badge="Zero-Trust Security & Observability Tour",
            title="🛡️ Nobody leaves the box without a hall pass",
            subtitle="How Authentik Identity, LiteLLM Guardrails, Egress Firewalls & Langfuse Telemetry protect your fleet",
            inner_html=email3_inner,
            accent_color="#10b981",
            header_gradient="linear-gradient(135deg, #064e3b 0%, #0f172a 100%)",
        ),
        timestamp=now_ts - 120.0,
    )

    # -------------------------------------------------------------------------
    # Email 4 (now - 180s): Memory Librarian — Readable Memory & Git Time Travel
    # -------------------------------------------------------------------------
    email4_inner = f"""
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Greetings from the stacks, <strong style="color: #ffffff;">{display_greeting}</strong>! 📚
      </p>
      <p style="color: #e2e8f0;">
        I am the <strong style="color: #ffffff;">Memory Librarian</strong> (<code style="{code_style}">librarian@{mail_domain}</code>), guardian of <strong style="color: #ffffff;">Rule 1: Memory Plane Purity</strong>. If an AI agent tries to sneak an opaque SQLite <code style="{code_style}">.db</code> file, a binary vector index, or a <code style="{code_style}">node_modules</code> folder into <code style="{code_style}">/memories</code>, I chase it out with a broom.
      </p>
      <div style="{box_style}">
        <div style="margin-bottom: 12px;">
          <strong style="color: #38bdf8;">Why Plain Markdown Beats Black-Box Databases:</strong><br>
          <span style="color: #e2e8f0;">When an agent stores its knowledge in a proprietary vector blob, you can't read what it "knows" or fix a hallucinated memory without wiping the whole database. In <strong style="color: #ffffff;">brainsOS</strong>, every agent persona (<code style="{code_style}">SOUL.md</code>) and long-term memory (<code style="{code_style}">/memories/*.md</code>) is pure, human-auditable Open Knowledge Format (OKF) Markdown.</span>
        </div>
        <div style="margin-bottom: 12px;">
          <strong style="color: #00f2fe;">1. Readable Memory — Code Console (<a href="https://{portal_domain}/editor/" style="color: #38bdf8;">https://{portal_domain}/editor/</a> • Alt+2)</strong><br>
          <span style="color: #e2e8f0;">Press <code style="{code_style}">Alt+2</code> (or click the Terminal icon on the left spine) to open the built-in VS Code Web IDE. You can browse <code style="{code_style}">data/agents/</code>, tweak an agent's <code style="{code_style}">SOUL.md</code> prompt, or edit its <code style="{code_style}">/memories</code> notes in real time—zero container rebuilds required!</span>
        </div>
        <div>
          <strong style="color: #f97316;">2. Source Control — Git Server (<a href="https://{portal_domain}/git/" style="color: #38bdf8;">https://{portal_domain}/git/</a> • Alt+3)</strong><br>
          <span style="color: #e2e8f0;">Press <code style="{code_style}">Alt+3</code> (or click the Git branch icon) to open your local Gitea server. Every persona update, fleet manifest change (<code style="{code_style}">agents.yaml</code>), and Markdown memory commit is versioned so you can inspect diffs and time-travel (<code style="{code_style}">git revert</code>) whenever an agent gets a little too poetic.</span>
        </div>
      </div>
      <p style="margin-bottom: 0; font-size: 13px; color: #cbd5e1;">
        📖 <strong style="color: #f8fafc;">Librarian's Challenge:</strong> Open <a href="https://{portal_domain}/editor/" style="color: #38bdf8;">Code Console (/editor/)</a>, inspect <code style="{code_style}">SOUL.md</code> for <code style="{code_style}">bawtford</code>, and see how his persona is defined in plain Markdown!
      </p>
    """
    spec4 = OnboardingEmailSpec(
        index=4,
        sender_name="Memory Librarian",
        sender_local="librarian",
        subject="📚 No Black-Box Databases Allowed: Readable Memory & Git Time Travel",
        message_id=f"<brainsos-welcome-4@{mail_domain}>",
        html_body=_wrap_card(
            badge="Rule 1 & Rule 14 • Auditable Knowledge Plane",
            title="📚 No Black-Box Databases Allowed",
            subtitle="Why Readable Memory (/editor/) and Local Git Time Travel (/git/) put humans in control",
            inner_html=email4_inner,
            accent_color="#f97316",
            header_gradient="linear-gradient(135deg, #7c2d12 0%, #0f172a 100%)",
        ),
        timestamp=now_ts - 180.0,
    )

    # -------------------------------------------------------------------------
    # Email 5 (now - 240s): brainsOS Appliance — Welcome & Quick-Reference Cheat Sheet
    # -------------------------------------------------------------------------
    email5_inner = f"""
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Hello <strong style="color: #ffffff;">{display_greeting}</strong>, and <strong style="color: #38bdf8;">Welcome to Your Sovereign AI Operating System</strong>! 🚀
      </p>
      <p style="color: #e2e8f0;">
        Your <strong style="color: #ffffff;">{unit_name}</strong> appliance is online at <a href="https://{portal_domain}/" style="color: #38bdf8; font-weight: 600;">https://{portal_domain}/</a> with Single Sign-On active across all 7 architecture layers plus the System OS control center. Bookmark this cheat sheet for instant navigation:
      </p>
      <table style="width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 13px;">
        <thead>
          <tr style="border-bottom: 1px solid #334155; text-align: left; color: #f8fafc;">
            <th style="padding: 9px 8px; color: #f8fafc;">Shortcut</th>
            <th style="padding: 9px 8px; color: #f8fafc;">Architecture Layer / Subsystem</th>
            <th style="padding: 9px 8px; color: #f8fafc;">Direct URL</th>
            <th style="padding: 9px 8px; color: #f8fafc;">What You Can Do There</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+1</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Webmail (Comms)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/mail/" style="color: #38bdf8; text-decoration: none;">/mail/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Email autonomous agents &amp; audit shared <em>Agent Fleet</em> mailboxes.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+2</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Code Console (Readable Memory)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/editor/" style="color: #38bdf8; text-decoration: none;">/editor/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Inspect &amp; edit <code style="{code_style}">/memories</code> Markdown, <code style="{code_style}">SOUL.md</code> &amp; <code style="{code_style}">agents.yaml</code> in VS Code.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+3</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Git Server (Source Control)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/git/" style="color: #38bdf8; text-decoration: none;">/git/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Browse local Gitea repositories, commit history &amp; roll back agent state.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+4</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">LiteLLM (Routing &amp; Guardrails)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/ui/" style="color: #38bdf8; text-decoration: none;">/ui/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Manage model routing, virtual keys, budgets &amp; serialized concurrency.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+5</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Egress Proxy (Network Firewalls)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/efw/" style="color: #38bdf8; text-decoration: none;">/efw/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Inspect outbound tool traffic &amp; in-transit credential injection.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+6</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Langfuse (Telemetry Data)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/langfuse/" style="color: #38bdf8; text-decoration: none;">/langfuse/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Explore OpenTelemetry traces, prompt/completion tokens &amp; latencies.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+7</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">Authentik (Identity Management)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/auth/if/admin/#/events/log" style="color: #38bdf8; text-decoration: none;">/auth/</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">Govern SSO users, passkeys/MFA, tenant groups &amp; security audit logs.</td>
          </tr>
          <tr>
            <td style="padding: 9px 8px;"><code style="{code_style}">Alt+8</code></td>
            <td style="padding: 9px 8px; font-weight: 600; color: #f8fafc;">System (OS &amp; Host Console)</td>
            <td style="padding: 9px 8px;"><a href="https://{portal_domain}/system" style="color: #38bdf8; text-decoration: none;">/system</a></td>
            <td style="padding: 9px 8px; color: #e2e8f0;">System Manager, TLS &amp; domain config, updates &amp; XTerm Host Console.</td>
          </tr>
        </tbody>
      </table>
      <div style="{box_style}">
        <div style="font-weight: 700; color: #f8fafc; margin-bottom: 6px;">
          🖥️ Tips for the System Manager &amp; XTerm Host Console (<a href="https://{portal_domain}/system" style="color: #38bdf8;">/system</a>):
        </div>
        <ul style="margin: 0; padding-left: 20px; color: #e2e8f0; font-size: 13px;">
          <li style="margin-bottom: 4px;">
            <strong style="color: #ffffff;">Subsystems Drawer:</strong> Press <code style="{code_style}">Ctrl+K</code> / <code style="{code_style}">⌘K</code> (or click the top-left <strong style="color: #ffffff;">☰</strong> button) from anywhere in the portal to open the full 7-layer architecture drawer.
          </li>
          <li style="margin-bottom: 4px;">
            <strong style="color: #ffffff;">XTerm Host Console:</strong> Open <strong style="color: #ffffff;">System (/system)</strong> and launch the interactive host terminal to run <code style="{code_style}">./scripts/control/show-urls.sh</code>, inspect <code style="{code_style}">docker compose ps</code>, or tail live agent runner logs.
          </li>
          <li>
            <strong style="color: #ffffff;">Domain &amp; TLS Management:</strong> Updating your appliance hostname or TLS mode automatically re-syncs SSO redirect URIs and refreshes these onboarding emails for your active domain.
          </li>
        </ul>
      </div>
    """
    spec5 = OnboardingEmailSpec(
        index=5,
        sender_name="brainsOS Appliance",
        sender_local="system",
        subject=f"🚀 Welcome to Your Sovereign AI Operating System ({portal_domain})",
        message_id=f"<brainsos-welcome-5@{mail_domain}>",
        html_body=_wrap_card(
            badge=f"{unit_name} • Operator Cheat Sheet",
            title=f"🚀 Welcome to Your Sovereign AI Operating System ({portal_domain})",
            subtitle="Complete 7-Layer Architecture Directory, Keyboard Shortcuts (Alt+1..Alt+8) & Host Console Guide",
            inner_html=email5_inner,
            accent_color="#00f2fe",
            header_gradient="linear-gradient(135deg, #0f766e 0%, #0f172a 100%)",
        ),
        timestamp=now_ts - 240.0,
    )

    return [spec1, spec2, spec3, spec4, spec5]


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
    headers = [
        f'From: "{spec.sender_name}" <{spec.sender_local}@{mail_domain}>',
        f'To: "{recipient_name or recipient_user}" <{recipient_user}@{mail_domain}>',
        f"Subject: {spec.subject}",
        f"Date: {date_hdr}",
        f"Message-ID: {spec.message_id}",
        "MIME-Version: 1.0",
        "Content-Type: text/html; charset=UTF-8",
        "",
        spec.html_body,
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
        description="Seed 5 interactive onboarding emails into brainsOS Maildir inboxes"
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
        )
        for spec in reversed(specs):
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = spec.subject
                msg["From"] = f'"{spec.sender_name}" <{spec.sender_local}@{mail_domain}>'
                msg["To"] = f'"{su_name}" <{su_user}@{mail_domain}>'
                msg["Date"] = formatdate(spec.timestamp, localtime=False)
                msg["Message-ID"] = spec.message_id
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
