#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Mail Infrastructure Provisioning & Account Seeding
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
echo "[INFO] Project Titan: Provisioning Internal Email & Webmail Subsystem"
echo "[INFO] ======================================================================"

COMMS_DIR="${TITAN_COMMS_DIR:-$REPO_ROOT/data/comms}"
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
ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-titan_admin_mail_secret_change_me}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-titan_operator_mail_secret_change_me}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-titan_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-titan_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-titan_marvin_mail_secret_change_me}"

echo "[INFO] Generating account directory in $CONFIG_DIR/users..."
cat << EOF > "$CONFIG_DIR/users"
admin@titan.local:{PLAIN}$ADMIN_PASS:5000:5000::/var/mail/vmail/admin::
operator@titan.local:{PLAIN}$OPERATOR_PASS:5000:5000::/var/mail/vmail/operator::
terrastella@titan.local:{PLAIN}$TERRASTELLA_PASS:5000:5000::/var/mail/vmail/terrastella::
bawtford@titan.local:{PLAIN}$BAWTFORD_PASS:5000:5000::/var/mail/vmail/bawtford::
marvin@titan.local:{PLAIN}$MARVIN_PASS:5000:5000::/var/mail/vmail/marvin::
EOF

cat << 'EOF' > "$CONFIG_DIR/vmailbox"
admin@titan.local admin
operator@titan.local operator
terrastella@titan.local terrastella
bawtford@titan.local bawtford
marvin@titan.local marvin
EOF

cat << 'EOF' > "$CONFIG_DIR/virtual"
postmaster@titan.local admin@titan.local
root@titan.local admin@titan.local
EOF

# Scaffold mailbox folders for all accounts
for user in admin operator terrastella bawtford marvin; do
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

echo "$DOMAIN_JSON_CONTENT" > "$DOMAINS_DIR/titan.local.json"
echo "$DOMAIN_JSON_CONTENT" > "$DOMAINS_DIR/default.json"

# 3. Ensure Container Permissions
# Postfix/Dovecot container runs as UID 5000; SnappyMail runs as www-data (UID 82 on Alpine)
docker run --rm -v "$MAIL_DIR:/mail" alpine sh -c "chmod -R 777 /mail && chown -R 82:82 /mail/snappymail" 2>/dev/null || true

# 4. Build Mail Server Image
echo "[INFO] Building titan-mail-server container image..."
docker build -t titan-mail-server:latest "$REPO_ROOT/docker/mail"

echo "[SUCCESS] Mail infrastructure setup complete!"
echo "[INFO] Accounts provisioned:"
echo "       - admin@titan.local (Full shared access over all agent mailboxes)"
echo "       - operator@titan.local"
echo "       - terrastella@titan.local"
echo "       - bawtford@titan.local"
echo "       - marvin@titan.local"
