#!/bin/bash
set -e

echo "[BRAINSOS-MAIL] Initializing brainsOS Mail Server (Postfix + Dovecot)..."

# Ensure directories exist
mkdir -p /var/mail/vmail /etc/mail-brainsos /var/run/dovecot /var/spool/postfix /var/spool/brainsos/inbound
touch /var/mail/vmail/shared-mailboxes.db
chown -R vmail:vmail /var/spool/brainsos 2>/dev/null || true
chmod -R 775 /var/spool/brainsos 2>/dev/null || true

# Ensure vmail user & group exist
addgroup -g 5000 vmail 2>/dev/null || true
adduser -D -u 5000 -G vmail -h /var/mail/vmail vmail 2>/dev/null || true
addgroup dovecot vmail 2>/dev/null || true
addgroup postfix vmail 2>/dev/null || true

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_mail_secret_change_me}}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_operator_mail_secret_change_me}}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-brainsos_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-brainsos_marvin_mail_secret_change_me}"
PING_PASS="${PING_MAIL_PASSWORD:-brainsos_ping_mail_secret_change_me}"
CLAUDE_PASS="${CLAUDE_MAIL_PASSWORD:-brainsos_claude_mail_secret_change_me}"
GPT_PASS="${GPT_MAIL_PASSWORD:-brainsos_gpt_mail_secret_change_me}"

# Collect and deduplicate domains
ADMIN_USER="${BRAINSOS_ADMIN_USERNAME:-admin}"
PRIMARY_LOCAL_DOMAIN="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-local.brainsos.ai}}"
RAW_DOMAINS=("brainsos.local" "local.brainsos.ai")
if [ -n "${BRAINSOS_LOCAL_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_LOCAL_DOMAIN}"); fi
if [ -n "${BRAINSOS_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_DOMAIN}"); fi
if [ -n "${BRAINSOS_MAIL_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_MAIL_DOMAIN}"); fi
if [ -n "${BRAINSOS_EMAIL_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_EMAIL_DOMAIN}"); fi

UNIQUE_DOMAINS=()
for d in "${RAW_DOMAINS[@]}"; do
    skip=0
    for u in "${UNIQUE_DOMAINS[@]}"; do
        if [ "$d" = "$u" ]; then
            skip=1
            break
        fi
    done
    if [ "$skip" -eq 0 ]; then
        UNIQUE_DOMAINS+=("$d")
    fi
done

# Provision configuration files in mounted volume
echo "[BRAINSOS-MAIL] Provisioning accounts in /etc/mail-brainsos/users..."
> /etc/mail-brainsos/users
> /etc/mail-brainsos/vmailbox
> /etc/mail-brainsos/virtual

for d in "${UNIQUE_DOMAINS[@]}"; do
cat << EOF >> /etc/mail-brainsos/users
admin@${d}:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::
operator@${d}:{PLAIN}${OPERATOR_PASS}:5000:5000::/var/mail/vmail/operator::
akadmin@${d}:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::
terrastella@${d}:{PLAIN}${TERRASTELLA_PASS}:5000:5000::/var/mail/vmail/terrastella::
bawtford@${d}:{PLAIN}${BAWTFORD_PASS}:5000:5000::/var/mail/vmail/bawtford::
marvin@${d}:{PLAIN}${MARVIN_PASS}:5000:5000::/var/mail/vmail/marvin::
ping@${d}:{PLAIN}${PING_PASS}:5000:5000::/var/mail/vmail/ping::
claude@${d}:{PLAIN}${CLAUDE_PASS}:5000:5000::/var/mail/vmail/claude::
gpt@${d}:{PLAIN}${GPT_PASS}:5000:5000::/var/mail/vmail/gpt::
EOF

cat << EOF >> /etc/mail-brainsos/vmailbox
admin@${d} admin
operator@${d} operator
akadmin@${d} admin
terrastella@${d} terrastella
bawtford@${d} bawtford
marvin@${d} marvin
ping@${d} ping
claude@${d} claude
gpt@${d} gpt
EOF

cat << EOF >> /etc/mail-brainsos/virtual
postmaster@${d} admin@${d}
root@${d} admin@${d}
akadmin@${d} admin@${d}
cindy@${d} bawtford@${d}
EOF
if [ -n "${ADMIN_USER}" ] && [ "${ADMIN_USER}" != "admin" ] && [ "${ADMIN_USER}" != "akadmin" ]; then
    echo "${ADMIN_USER}@${d}:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::" >> /etc/mail-brainsos/users
    echo "${ADMIN_USER}@${d} admin" >> /etc/mail-brainsos/vmailbox
fi
done

# Configure Postfix hostname, domain & virtual mailbox domains
DOMAINS_STR=$(IFS=', '; echo "${UNIQUE_DOMAINS[*]}")
postconf -e "myhostname = ${PRIMARY_LOCAL_DOMAIN}"
postconf -e "mydomain = ${PRIMARY_LOCAL_DOMAIN}"
postconf -e "virtual_mailbox_domains = ${DOMAINS_STR}"

# Compile Postfix lookup databases
postmap lmdb:/etc/mail-brainsos/vmailbox
postmap lmdb:/etc/mail-brainsos/virtual
newaliases

# Clean up any stale lock files from previous unclean shutdowns
find /var/mail/vmail -name "*.lock" -delete 2>/dev/null || true

# Enforce secure permissions
chown -R vmail:vmail /var/mail/vmail
chmod -R 770 /var/mail/vmail

# Scaffold mailbox folders for all users
for user in $(cut -d: -f1 /etc/mail-brainsos/users); do
    name=$(echo "$user" | cut -d@ -f1)
    mkdir -p "/var/mail/vmail/$name/Maildir/new" \
             "/var/mail/vmail/$name/Maildir/cur" \
             "/var/mail/vmail/$name/Maildir/tmp"
    chown -R vmail:vmail "/var/mail/vmail/$name"
    chmod -R 770 "/var/mail/vmail/$name"
done

# Seed / update Welcome Email in administrator mailbox(es) with active local domain
WELCOME_DATE="$(date -R 2>/dev/null || echo "Fri, 06 Nov 2026 12:00:00 +0000")"
ADMIN_TARGETS=("admin")
if [ -n "${ADMIN_USER}" ] && [ "${ADMIN_USER}" != "admin" ] && [ "${ADMIN_USER}" != "akadmin" ]; then
    ADMIN_TARGETS+=("${ADMIN_USER}")
fi
for target_box in "${ADMIN_TARGETS[@]}"; do
    EXISTING_CUR="$(find "/var/mail/vmail/$target_box/Maildir/cur" -maxdepth 1 -name "1730937600.M000001P1.brainsos*" 2>/dev/null | head -n 1 || true)"
    if [ -n "${EXISTING_CUR}" ]; then
        WELCOME_PATH="${EXISTING_CUR}"
        rm -f "/var/mail/vmail/$target_box/Maildir/new/1730937600.M000001P1.brainsos"* 2>/dev/null || true
    else
        WELCOME_PATH="/var/mail/vmail/$target_box/Maildir/new/1730937600.M000001P1.brainsos"
    fi
    cat <<EOF > "${WELCOME_PATH}"
From: "brainsOS Appliance" <ping@${PRIMARY_LOCAL_DOMAIN}>
To: "${ADMIN_USER}" <${ADMIN_USER}@${PRIMARY_LOCAL_DOMAIN}>
Subject: Welcome to brainsOS — Your Autonomous Agent Fleet Directory
Date: ${WELCOME_DATE}
Message-ID: <welcome-fleet-directory@${PRIMARY_LOCAL_DOMAIN}>
MIME-Version: 1.0
Content-Type: text/html; charset=UTF-8

<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #e2e8f0; background-color: #0b0f19; padding: 24px; line-height: 1.6;">
  <div style="max-width: 680px; margin: 0 auto; background-color: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 28px;">
    <h2 style="margin-top: 0; color: #38bdf8;">Welcome to brainsOS (${PRIMARY_LOCAL_DOMAIN})</h2>
    <p>Hello <strong>${ADMIN_USER}</strong>,</p>
    <p>
      Your sovereign <strong>brainsOS</strong> appliance is online and your internal Postfix, Dovecot, and SOGo communications plane is active for <code>@${PRIMARY_LOCAL_DOMAIN}</code>.
    </p>
    <p>
      You can collaborate with your autonomous agents directly via email. Simply click <strong>New Message</strong>, type an agent's name in the <code>To</code> field (auto-completed from the <strong>brainsOS Directory</strong> address book), and send your task or question:
    </p>
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;">
      <thead>
        <tr style="border-bottom: 1px solid #374151; text-align: left; color: #94a3b8;">
          <th style="padding: 10px 8px;">Agent</th>
          <th style="padding: 10px 8px;">Email Address</th>
          <th style="padding: 10px 8px;">Role &amp; Capabilities</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Ping</td>
          <td style="padding: 10px 8px;"><a href="mailto:ping@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">ping@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">Instant diagnostic echo &amp; end-to-end mail/queue latency probe.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Cindy Bawtford</td>
          <td style="padding: 10px 8px;"><a href="mailto:bawtford@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">bawtford@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">Creative Director &amp; full-stack web application orchestrator.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Terrastella</td>
          <td style="padding: 10px 8px;"><a href="mailto:terrastella@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">terrastella@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">Executive strategy, research synthesis &amp; operations coordinator.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Marvin</td>
          <td style="padding: 10px 8px;"><a href="mailto:marvin@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">marvin@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">Systems architecture, diagnostics &amp; security boundary auditor.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">Claude Demo</td>
          <td style="padding: 10px 8px;"><a href="mailto:claude@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">claude@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">General-purpose reasoning, analysis &amp; writing assistant.</td>
        </tr>
        <tr>
          <td style="padding: 10px 8px; font-weight: 600; color: #f8fafc;">GPT Demo</td>
          <td style="padding: 10px 8px;"><a href="mailto:gpt@${PRIMARY_LOCAL_DOMAIN}" style="color: #38bdf8;">gpt@${PRIMARY_LOCAL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #cbd5e1;">General-purpose assistant for rapid drafting, coding &amp; Q&amp;A.</td>
        </tr>
      </tbody>
    </table>
    <p style="font-size: 13px; color: #94a3b8; margin-bottom: 0;">
      <strong>Tip:</strong> As the appliance administrator, you also have read/oversight access to all agent mailboxes under the <em>Agent Fleet</em> shared namespace in the left folder pane.
    </p>
  </div>
</body>
</html>
EOF
    chown vmail:vmail "${WELCOME_PATH}" 2>/dev/null || true
    chmod 660 "${WELCOME_PATH}" 2>/dev/null || true
done

# Compile default Sieve script and ensure webhook dispatcher permissions
if [ -f /etc/dovecot/sieve/default.sieve ]; then
    sievec /etc/dovecot/sieve/default.sieve /etc/dovecot/sieve/default.svbin 2>/dev/null || true
    chmod 644 /etc/dovecot/sieve/default.* 2>/dev/null || true
    chown -R vmail:vmail /etc/dovecot/sieve 2>/dev/null || true
fi
if [ -f /usr/lib/dovecot/sieve-pipe/agent-webhook.sh ]; then
    chmod 755 /usr/lib/dovecot/sieve-pipe/agent-webhook.sh 2>/dev/null || true
fi

# Initialize Dovecot log file
touch /var/log/dovecot.log
chown dovecot:dovecot /var/log/dovecot.log 2>/dev/null || true
tail -n 0 -F /var/log/dovecot.log &

# Export environment variables for Dovecot Sieve child scripts
env | grep -E '^(HERMES_API_|BRAINSOS_AGENT_|BRAINSOS_INGRESS_URL|BRAINSOS_SPOOL_DIR)' > /etc/environment || true
chmod 644 /etc/environment

# Start Dovecot
echo "[BRAINSOS-MAIL] Starting Dovecot daemon..."
/usr/sbin/dovecot
sleep 1

# Register ACLs via doveadm:
# 1. Agent owners get read, write, seen, insert, and post rights — but CANNOT delete, expunge, or modify ACLs
# 2. Administrator gets full management access (including write-deleted and expunge)
for user in $(cut -d: -f1 /etc/mail-brainsos/users); do
    base_user=$(echo "$user" | cut -d@ -f1)
    if [ "$base_user" != "admin" ] && [ "$base_user" != "${ADMIN_USER}" ]; then
        # Restrict agent owner: no write-deleted (t), no expunge (e), no admin (a)
        doveadm acl set -u "$user" INBOX owner lookup read write write-seen insert post 2>/dev/null || true
        # Grant admin full oversight & expunge capabilities across all domains
        for d in "${UNIQUE_DOMAINS[@]}"; do
            doveadm acl set -u "$user" INBOX user=admin@${d} lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
            if [ -n "${ADMIN_USER}" ] && [ "${ADMIN_USER}" != "admin" ]; then
                doveadm acl set -u "$user" INBOX user=${ADMIN_USER}@${d} lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
            fi
        done
    fi
done

# Start Postfix
echo "[BRAINSOS-MAIL] Starting Postfix daemon..."
/usr/sbin/postfix start

echo "[BRAINSOS-MAIL] Mail server running and ready for traffic (SMTP :25/:587, IMAP :143)."

# Signal handler for graceful shutdown
shutdown() {
    echo "[BRAINSOS-MAIL] Shutting down Postfix and Dovecot..."
    /usr/sbin/postfix stop 2>/dev/null || true
    if [ -f /var/run/dovecot/master.pid ]; then
        kill -TERM $(cat /var/run/dovecot/master.pid 2>/dev/null) 2>/dev/null || true
    fi
    exit 0
}

trap shutdown SIGTERM SIGINT

# Keep container alive while monitoring daemons
while true; do
    if [ ! -f /var/run/dovecot/master.pid ] || ! kill -0 $(cat /var/run/dovecot/master.pid 2>/dev/null) 2>/dev/null; then
        echo "[BRAINSOS-MAIL] Dovecot process died!"
        exit 1
    fi
    if ! /usr/sbin/postfix status >/dev/null 2>&1; then
        echo "[BRAINSOS-MAIL] Postfix process died!"
        exit 1
    fi
    sleep 5
done
