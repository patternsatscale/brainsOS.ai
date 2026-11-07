#!/usr/bin/env python3
"""brainsOS: High-Contrast Welcome Email Generator & Maildir Seeder (#332).

Seeds or updates the Welcome Email in the administrator and superuser Maildir
inboxes with high-contrast typography (#f8fafc, #e2e8f0, #cbd5e1) on dark cards.
"""

import argparse
from email.utils import formatdate
import glob
import os
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


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


def render_welcome_html(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str = "Enterprise Agent Box",
) -> str:
    display_greeting = recipient_name or recipient_user
    return f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #f8fafc; background-color: #0b0f19; padding: 24px; line-height: 1.65;">
  <div style="max-width: 680px; margin: 0 auto; background-color: #0f172a; border: 1px solid #334155; border-radius: 12px; overflow: hidden;">
    <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); padding: 24px 28px; border-bottom: 1px solid #334155;">
      <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #38bdf8; margin-bottom: 4px;">
        {unit_name}
      </div>
      <h2 style="margin: 0; font-size: 22px; font-weight: 700; color: #f8fafc;">
        Welcome to brainsOS ({mail_domain})
      </h2>
      <p style="margin: 6px 0 0 0; font-size: 14px; color: #e2e8f0;">
        Sovereign Autonomous Agent Fleet &amp; Private Communications Plane
      </p>
    </div>
    <div style="padding: 28px; color: #f8fafc;">
      <p style="margin-top: 0; font-size: 15px; color: #f8fafc;">
        Hello <strong style="color: #ffffff;">{display_greeting}</strong>,
      </p>
      <p style="font-size: 14px; color: #e2e8f0;">
        Your sovereign <strong style="color: #f8fafc;">brainsOS</strong> appliance is online and your internal Postfix, Dovecot, and SOGo communications plane is active for <code style="color: #38bdf8; background-color: #1e293b; padding: 2px 6px; border-radius: 4px;">@{mail_domain}</code>.
      </p>
      <p style="font-size: 14px; color: #e2e8f0;">
        You can collaborate with your autonomous agents directly via email. Simply click <strong style="color: #f8fafc;">New Message</strong>, type an agent's name in the <code style="color: #38bdf8;">To</code> field (auto-completed from the <strong style="color: #f8fafc;">brainsOS Directory</strong> address book), and send your task or question:
      </p>
      <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;">
        <thead>
          <tr style="border-bottom: 1px solid #334155; text-align: left; color: #f8fafc;">
            <th style="padding: 10px 8px; color: #f8fafc;">Agent</th>
            <th style="padding: 10px 8px; color: #f8fafc;">Email Address</th>
            <th style="padding: 10px 8px; color: #f8fafc;">Role &amp; Capabilities</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Ping</td>
            <td style="padding: 10px 8px;"><a href="mailto:ping@{mail_domain}" style="color: #38bdf8; text-decoration: none;">ping@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">Instant diagnostic echo &amp; end-to-end mail/queue latency probe.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Cindy Bawtford</td>
            <td style="padding: 10px 8px;"><a href="mailto:bawtford@{mail_domain}" style="color: #38bdf8; text-decoration: none;">bawtford@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">Creative Director &amp; full-stack web application orchestrator.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Terrastella</td>
            <td style="padding: 10px 8px;"><a href="mailto:terrastella@{mail_domain}" style="color: #38bdf8; text-decoration: none;">terrastella@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">Executive strategy, research synthesis &amp; operations coordinator.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Marvin</td>
            <td style="padding: 10px 8px;"><a href="mailto:marvin@{mail_domain}" style="color: #38bdf8; text-decoration: none;">marvin@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">Systems architecture, diagnostics &amp; security boundary auditor.</td>
          </tr>
          <tr style="border-bottom: 1px solid #1e293b;">
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Claude Demo</td>
            <td style="padding: 10px 8px;"><a href="mailto:claude@{mail_domain}" style="color: #38bdf8; text-decoration: none;">claude@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">General-purpose reasoning, analysis &amp; writing assistant.</td>
          </tr>
          <tr>
            <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">GPT Demo</td>
            <td style="padding: 10px 8px;"><a href="mailto:gpt@{mail_domain}" style="color: #38bdf8; text-decoration: none;">gpt@{mail_domain}</a></td>
            <td style="padding: 10px 8px; color: #e2e8f0;">General-purpose assistant for rapid drafting, coding &amp; Q&amp;A.</td>
          </tr>
        </tbody>
      </table>
      <p style="font-size: 13px; color: #cbd5e1; margin-bottom: 0; background-color: #1e293b; padding: 12px 14px; border-radius: 8px; border: 1px solid #334155;">
        <strong style="color: #f8fafc;">Tip:</strong> As the appliance administrator, you also have read/oversight access to all agent mailboxes under the <em style="color: #f8fafc;">Agent Fleet</em> shared namespace in the left folder pane.
      </p>
    </div>
  </div>
</body>
</html>
"""


def build_rfc822_message(
    recipient_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str = "Enterprise Agent Box",
) -> str:
    html = render_welcome_html(recipient_user, recipient_name, mail_domain, unit_name)
    date_hdr = formatdate(localtime=False)
    headers = [
        f'From: "brainsOS Appliance" <ping@{mail_domain}>',
        f'To: "{recipient_name or recipient_user}" <{recipient_user}@{mail_domain}>',
        "Subject: Welcome to brainsOS — Your Autonomous Agent Fleet Directory",
        f"Date: {date_hdr}",
        f"Message-ID: <welcome-fleet-directory@{mail_domain}>",
        "MIME-Version: 1.0",
        "Content-Type: text/html; charset=UTF-8",
        "",
        html,
    ]
    return "\n".join(headers)


def seed_maildir(
    vmail_dir: Path,
    mailbox_user: str,
    recipient_name: str,
    mail_domain: str,
    unit_name: str,
) -> Path:
    cur_dir = vmail_dir / mailbox_user / "Maildir" / "cur"
    new_dir = vmail_dir / mailbox_user / "Maildir" / "new"
    tmp_dir = vmail_dir / mailbox_user / "Maildir" / "tmp"
    cur_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for old_f in glob.glob(str(cur_dir / "1730937600.M000001P1.brainsos*")) + glob.glob(str(new_dir / "1730937600.M000001P1.brainsos*")):
        try:
            os.remove(old_f)
        except OSError:
            pass

    existing_cur = sorted(glob.glob(str(cur_dir / "1794074500.M000001P1.brainsos*")))
    if existing_cur:
        target_path = Path(existing_cur[0])
        for extra in glob.glob(str(new_dir / "1794074500.M000001P1.brainsos*")):
            try:
                os.remove(extra)
            except OSError:
                pass
    else:
        target_path = new_dir / "1794074500.M000001P1.brainsos"

    msg_str = build_rfc822_message(mailbox_user, recipient_name, mail_domain, unit_name)
    target_path.write_text(msg_str, encoding="utf-8")
    return target_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed high-contrast Welcome Email into brainsOS Maildir")
    parser.add_argument("--repo-root", default=None, help="Repository root path")
    parser.add_argument("--domain", default=None, help="Override local mail domain")
    parser.add_argument("--user", default=None, help="Override superuser username")
    parser.add_argument("--name", default=None, help="Override superuser display name")
    parser.add_argument("--vmail-dir", default=None, help="Override vmail directory path")
    parser.add_argument("--smtp", action="store_true", help="Also attempt SMTP delivery to localhost:25")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    env = parse_env(repo_root / ".env")

    mail_domain = (
        args.domain
        or env.get("BRAINSOS_LOCAL_DOMAIN")
        or env.get("BRAINSOS_MAIL_DOMAIN")
        or env.get("BRAINSOS_DOMAIN")
        or "local.brainsos.ai"
    )
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
    vmail_dir = Path(args.vmail_dir) if args.vmail_dir else (data_dir / "mail" / "vmail")

    targets = ["admin"]
    if su_user and su_user not in targets:
        targets.append(su_user)

    for box in targets:
        box_name = su_name if box == su_user else "System Administrator"
        try:
            seed_maildir(vmail_dir, box, box_name, mail_domain, unit_name)
        except PermissionError:
            pass

    if args.smtp:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Welcome to brainsOS — Your Autonomous Agent Fleet Directory"
            msg["From"] = f'"brainsOS Appliance" <ping@{mail_domain}>'
            msg["To"] = f'"{su_name}" <{su_user}@{mail_domain}>'
            msg.attach(MIMEText(render_welcome_html(su_user, su_name, mail_domain, unit_name), "html", "utf-8"))
            with smtplib.SMTP("127.0.0.1", 25, timeout=3) as s:
                s.sendmail(f"ping@{mail_domain}", [f"{su_user}@{mail_domain}"], msg.as_string())
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
