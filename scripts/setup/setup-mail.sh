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
    docker run --rm -v "$MAIL_DIR:/mail" alpine chmod -R 777 /mail 2>/dev/null || chmod -R 777 "$MAIL_DIR" 2>/dev/null || true
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
SETUP_DOMAINS=("brainsos.local" "local.brainsos.ai")
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
done

# Scaffold mailbox folders for all accounts
for user in admin operator terrastella bawtford marvin ping claude gpt; do
    mkdir -p "$VMAIL_DIR/$user/Maildir/new" \
             "$VMAIL_DIR/$user/Maildir/cur" \
             "$VMAIL_DIR/$user/Maildir/tmp"
done
touch "$VMAIL_DIR/shared-mailboxes.db"

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
docker run --rm -v "$MAIL_DIR:/mail" alpine sh -c "chmod -R 777 /mail && chown -R 82:82 /mail/snappymail" 2>/dev/null || true

# 4. Build Mail Server Image
echo "[INFO] Building brainsos-mail-server container image..."
docker build -t brainsos-mail-server:latest "$REPO_ROOT/docker/mail"

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
