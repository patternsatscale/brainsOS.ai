#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Mail Infrastructure Provisioning & Account Seeding
# Codifies mail storage scaffolding, credentials, and SnappyMail configuration.
# Rule 8 compliant (Script-Driven Discipline) & Rule 1 compliant (Data Isolation)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source host environment if present
if [[ -f "$REPO_ROOT/.env" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
fi

ACCOUNTS_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --accounts-only)
            ACCOUNTS_ONLY=true
            ;;
    esac
done

echo "[INFO] ======================================================================"
echo "[INFO] brainsOS: Provisioning Internal Email & Webmail Subsystem"
echo "[INFO] ======================================================================"

COMMS_DIR="${BRAINSOS_COMMS_DIR:-${BRAINSOS_DATA_DIR:-$REPO_ROOT/data}/comms}"
MAIL_DIR="$COMMS_DIR/email"
VMAIL_DIR="$MAIL_DIR/vmail"
CONFIG_DIR="$MAIL_DIR/config"
SNAPPY_DIR="$MAIL_DIR/snappymail"

echo "[INFO] Target mail storage root: $MAIL_DIR"
if [ -d "$MAIL_DIR" ]; then
    chmod -R 777 "$MAIL_DIR" 2>/dev/null || true
    if docker image inspect alpine:latest >/dev/null 2>&1; then
        docker run --rm -v "$MAIL_DIR:/mail" alpine chmod -R 777 /mail 2>/dev/null || true
    fi
fi
mkdir -p "$VMAIL_DIR" "$CONFIG_DIR" "$SNAPPY_DIR"

# 1. Seed Accounts and Credentials
ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_terrastella_mail_secret_change_me}}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_bawtford_mail_secret_change_me}}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_marvin_mail_secret_change_me}}"
PING_PASS="${PING_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_ping_mail_secret_change_me}}"
CLAUDE_PASS="${CLAUDE_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_claude_mail_secret_change_me}}"
GPT_PASS="${GPT_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_gpt_mail_secret_change_me}}"

echo "[INFO] Generating account directory in $CONFIG_DIR/users..."
ADMIN_USER="${BRAINSOS_ADMIN_USERNAME:-admin}"
SETUP_DOMAINS=("brainsos.local" "local.brainsos.ai")
if [[ -n "${BRAINSOS_LOCAL_DOMAIN:-}" ]]; then SETUP_DOMAINS+=("${BRAINSOS_LOCAL_DOMAIN}"); fi
if [[ -n "${BRAINSOS_DOMAIN:-}" ]]; then SETUP_DOMAINS+=("${BRAINSOS_DOMAIN}"); fi
if [[ -n "${BRAINSOS_MAIL_DOMAIN:-}" ]]; then SETUP_DOMAINS+=("${BRAINSOS_MAIL_DOMAIN}"); fi
if [[ -n "${BRAINSOS_EMAIL_DOMAIN:-}" ]]; then SETUP_DOMAINS+=("${BRAINSOS_EMAIL_DOMAIN}"); fi

UNIQUE_SETUP_DOMAINS=()
for d in "${SETUP_DOMAINS[@]}"; do
    skip=0
    if [ ${#UNIQUE_SETUP_DOMAINS[@]} -gt 0 ]; then
        for u in "${UNIQUE_SETUP_DOMAINS[@]}"; do
            if [[ "$d" == "$u" ]]; then
                skip=1
                break
            fi
        done
    fi
    if [[ $skip -eq 0 ]]; then
        UNIQUE_SETUP_DOMAINS+=("$d")
    fi
done

> "$CONFIG_DIR/users"
> "$CONFIG_DIR/vmailbox"
> "$CONFIG_DIR/virtual"

for d in "${UNIQUE_SETUP_DOMAINS[@]}"; do
cat << EOF >> "$CONFIG_DIR/users"
admin@${d}:{PLAIN}$ADMIN_PASS:5000:5000::/var/mail/vmail/admin::
operator@${d}:{PLAIN}$OPERATOR_PASS:5000:5000::/var/mail/vmail/operator::
akadmin@${d}:{PLAIN}$ADMIN_PASS:5000:5000::/var/mail/vmail/admin::
terrastella@${d}:{PLAIN}$TERRASTELLA_PASS:5000:5000::/var/mail/vmail/terrastella::
bawtford@${d}:{PLAIN}$BAWTFORD_PASS:5000:5000::/var/mail/vmail/bawtford::
marvin@${d}:{PLAIN}$MARVIN_PASS:5000:5000::/var/mail/vmail/marvin::
ping@${d}:{PLAIN}$PING_PASS:5000:5000::/var/mail/vmail/ping::
claude@${d}:{PLAIN}$CLAUDE_PASS:5000:5000::/var/mail/vmail/claude::
gpt@${d}:{PLAIN}$GPT_PASS:5000:5000::/var/mail/vmail/gpt::
EOF

cat << EOF >> "$CONFIG_DIR/vmailbox"
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

cat << EOF >> "$CONFIG_DIR/virtual"
postmaster@${d} admin@${d}
root@${d} admin@${d}
akadmin@${d} admin@${d}
cindy@${d} bawtford@${d}
EOF
if [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "admin" ]]; then
    echo "${ADMIN_USER}@${d}:{PLAIN}$ADMIN_PASS:5000:5000::/var/mail/vmail/admin::" >> "$CONFIG_DIR/users"
    echo "${ADMIN_USER}@${d} admin" >> "$CONFIG_DIR/vmailbox"
fi
done

# Scaffold mailbox folders for all accounts
MAIL_USERS=(admin operator terrastella bawtford marvin ping claude gpt)
if [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "admin" ]]; then
    MAIL_USERS+=("${ADMIN_USER}")
fi
for user in "${MAIL_USERS[@]}"; do
    mkdir -p "$VMAIL_DIR/$user/Maildir/new" \
             "$VMAIL_DIR/$user/Maildir/cur" \
             "$VMAIL_DIR/$user/Maildir/tmp"
done
touch "$VMAIL_DIR/shared-mailboxes.db"

# Seed / update Welcome Email in administrator mailbox(es) with active local domain
PRIMARY_MAIL_DOMAIN="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}}"
WELCOME_DATE="$(date -R 2>/dev/null || echo "Fri, 06 Nov 2026 12:00:00 +0000")"
ADMIN_TARGETS=("admin")
if [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "admin" ]]; then
    ADMIN_TARGETS+=("${ADMIN_USER}")
fi

for target_box in "${ADMIN_TARGETS[@]}"; do
    rm -f "$VMAIL_DIR/$target_box/Maildir/cur/1730937600.M000001P1.brainsos"* "$VMAIL_DIR/$target_box/Maildir/new/1730937600.M000001P1.brainsos"* 2>/dev/null || true
    EXISTING_CUR="$(find "$VMAIL_DIR/$target_box/Maildir/cur" -maxdepth 1 -name "1794074500.M000001P1.brainsos*" 2>/dev/null | head -n 1 || true)"
    if [[ -n "${EXISTING_CUR}" ]]; then
        WELCOME_PATH="${EXISTING_CUR}"
        rm -f "$VMAIL_DIR/$target_box/Maildir/new/1794074500.M000001P1.brainsos"* 2>/dev/null || true
    else
        WELCOME_PATH="$VMAIL_DIR/$target_box/Maildir/new/1794074500.M000001P1.brainsos"
    fi
    cat <<EOF > "${WELCOME_PATH}"
From: "brainsOS Appliance" <ping@${PRIMARY_MAIL_DOMAIN}>
To: "${ADMIN_USER}" <${ADMIN_USER}@${PRIMARY_MAIL_DOMAIN}>
Subject: Welcome to brainsOS — Your Autonomous Agent Fleet Directory
Date: ${WELCOME_DATE}
Message-ID: <welcome-fleet-directory@${PRIMARY_MAIL_DOMAIN}>
MIME-Version: 1.0
Content-Type: text/html; charset=UTF-8

<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #f8fafc; background-color: #0b0f19; padding: 24px; line-height: 1.65;">
  <div style="max-width: 680px; margin: 0 auto; background-color: #111827; border: 1px solid #334155; border-radius: 12px; padding: 28px; color: #f8fafc;">
    <h2 style="margin-top: 0; color: #38bdf8;">Welcome to brainsOS (${PRIMARY_MAIL_DOMAIN})</h2>
    <p style="color: #f8fafc; font-size: 15px; margin: 0 0 14px 0;">Hello <strong style="color: #ffffff;">${ADMIN_USER}</strong>,</p>
    <p style="color: #f1f5f9; font-size: 14px; margin: 0 0 14px 0;">
      Your sovereign <strong style="color: #ffffff;">brainsOS</strong> appliance is online and your internal Postfix, Dovecot, and SOGo communications plane is active for <code style="color: #7dd3fc; background-color: #1e293b; padding: 2px 6px; border-radius: 4px;">@${PRIMARY_MAIL_DOMAIN}</code>.
    </p>
    <p style="color: #f1f5f9; font-size: 14px; margin: 0 0 16px 0;">
      You can collaborate with your autonomous agents directly via email. Simply click <strong style="color: #ffffff;">New Message</strong>, type an agent's name in the <code style="color: #7dd3fc; background-color: #1e293b; padding: 2px 6px; border-radius: 4px;">To</code> field (auto-completed from the <strong style="color: #ffffff;">brainsOS Directory</strong> address book), and send your task or question:
    </p>
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; color: #f8fafc;">
      <thead>
        <tr style="border-bottom: 1px solid #475569; text-align: left; color: #f8fafc;">
          <th style="padding: 10px 8px; color: #f8fafc;">Agent</th>
          <th style="padding: 10px 8px; color: #f8fafc;">Email Address</th>
          <th style="padding: 10px 8px; color: #f8fafc;">Role &amp; Capabilities</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">Ping</td>
          <td style="padding: 10px 8px;"><a href="mailto:ping@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">ping@${PRIMARY_MAIL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">Instant diagnostic echo &amp; end-to-end mail/queue latency probe.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">Cindy Bawtford</td>
          <td style="padding: 10px 8px;"><a href="mailto:bawtford@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">bawtford@${PRIMARY_MAIL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">Creative Director &amp; full-stack web application orchestrator.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">Terrastella</td>
          <td style="padding: 10px 8px;"><a href="mailto:terrastella@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">terrastella@${PRIMARY_MAIL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">Executive strategy, research synthesis &amp; operations coordinator.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">Marvin</td>
          <td style="padding: 10px 8px;"><a href="mailto:marvin@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">marvin@${PRIMARY_LOCAL_DOMAIN:-${PRIMARY_MAIL_DOMAIN}}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">Systems architecture, diagnostics &amp; security boundary auditor.</td>
        </tr>
        <tr style="border-bottom: 1px solid #1f2937;">
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">Claude Demo</td>
          <td style="padding: 10px 8px;"><a href="mailto:claude@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">claude@${PRIMARY_MAIL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">General-purpose reasoning, analysis &amp; writing assistant.</td>
        </tr>
        <tr>
          <td style="padding: 10px 8px; font-weight: 600; color: #ffffff;">GPT Demo</td>
          <td style="padding: 10px 8px;"><a href="mailto:gpt@${PRIMARY_MAIL_DOMAIN}" style="color: #38bdf8;">gpt@${PRIMARY_MAIL_DOMAIN}</a></td>
          <td style="padding: 10px 8px; color: #f1f5f9;">General-purpose assistant for rapid drafting, coding &amp; Q&amp;A.</td>
        </tr>
      </tbody>
    </table>
    <p style="font-size: 13px; color: #e2e8f0; margin-bottom: 0;">
      <strong style="color: #ffffff;">Tip:</strong> As the appliance administrator, you also have read/oversight access to all agent mailboxes under the <em style="color: #ffffff;">Agent Fleet</em> shared namespace in the left folder pane.
    </p>
  </div>
</body>
</html>
EOF
    rm -f "$VMAIL_DIR/$target_box/Maildir/dovecot.index.cache" 2>/dev/null || true
done

# 2. Pre-configure SnappyMail domain configurations for zero-click login
DOMAINS_DIR="$SNAPPY_DIR/_data_/_default_/domains"
mkdir -p "$DOMAINS_DIR"
rm -f "$DOMAINS_DIR"/*.json

DOMAIN_JSON_CONTENT='{
    "IMAP": {
        "host": "mail-server",
        "port": 143,
        "type": 0,
        "timeout": 300,
        "shortLogin": false,
        "lowerLogin": true,
        "sasl": ["PLAIN", "LOGIN"],
        "ssl": {
            "verify_peer": false,
            "verify_peer_name": false,
            "allow_self_signed": true,
            "SNI_enabled": false
        }
    },
    "SMTP": {
        "host": "mail-server",
        "port": 25,
        "type": 0,
        "timeout": 60,
        "shortLogin": false,
        "lowerLogin": true,
        "sasl": ["PLAIN", "LOGIN"],
        "ssl": {
            "verify_peer": false,
            "verify_peer_name": false,
            "allow_self_signed": true,
            "SNI_enabled": false
        },
        "useAuth": false
    },
    "Sieve": {
        "host": "mail-server",
        "port": 4190,
        "type": 0,
        "timeout": 10,
        "shortLogin": false,
        "lowerLogin": true,
        "sasl": ["PLAIN", "LOGIN"],
        "ssl": {
            "verify_peer": false,
            "verify_peer_name": false,
            "allow_self_signed": true,
            "SNI_enabled": false
        },
        "enabled": false
    },
    "whiteList": ""
}'

echo "$DOMAIN_JSON_CONTENT" > "$DOMAINS_DIR/brainsos.local.json"
echo "$DOMAIN_JSON_CONTENT" > "$DOMAINS_DIR/default.json"

# 3. Ensure Container Permissions
# Postfix/Dovecot container runs as UID 5000; SnappyMail runs as www-data (UID 82 on Alpine)
chmod -R 777 "$MAIL_DIR" 2>/dev/null || true
if docker image inspect alpine:latest >/dev/null 2>&1; then
    docker run --rm -v "$MAIL_DIR:/mail" alpine sh -c "chmod -R 777 /mail && chown -R 82:82 /mail/snappymail" 2>/dev/null || true
fi

# 4. Build Mail Server Image (skipped during fast --accounts-only credential sync if image exists)
if [ "$ACCOUNTS_ONLY" = false ] || ! docker image inspect brainsos-mail-server:latest >/dev/null 2>&1; then
    echo "[INFO] Building brainsos-mail-server container image..."
    docker build -t brainsos-mail-server:latest "$REPO_ROOT/docker/mail"
fi

# 5. External Email Ingress Daemon (Optional)
if [[ -n "${INGRESS_QUEUE_URL:-}" ]]; then
    echo "[INFO] INGRESS_QUEUE_URL is configured. Starting external mail-ingress..."
    docker compose --profile mail-ingress up -d mail-ingress
else
    echo "[INFO] External email ingress (mail-ingress) is not configured (INGRESS_QUEUE_URL is unset). Service remains dormant."
fi

echo "[SUCCESS] Mail infrastructure setup complete!"
echo "[INFO] Accounts provisioned:"
echo "       - admin@brainsos.local (Full shared access over all agent mailboxes)"
echo "       - operator@brainsos.local"
echo "       - terrastella@brainsos.local"
echo "       - bawtford@brainsos.local"
echo "       - marvin@brainsos.local"
