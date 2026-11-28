#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Mail Infrastructure Provisioning & Account Seeding
# Codifies mail storage scaffolding, credentials, and SnappyMail configuration.
# Rule 8 compliant (Script-Driven Discipline) & Rule 1 compliant (Data Isolation)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
ENV_FILE="${BRAINSOS_ENV_FILE:-$REPO_ROOT/.env}"

# Source host environment if present
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
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
mkdir -p "$VMAIL_DIR" "$CONFIG_DIR" "$SNAPPY_DIR"
chown 5000:5000 "$MAIL_DIR" 2>/dev/null || true
chmod 0750 "$MAIL_DIR" 2>/dev/null || true

# 1. Seed Accounts and Credentials (independent per-account passwords; never fall back to BRAINSOS_ADMIN_PASSWORD or static strings)
is_mail_placeholder() {
    local v="${1:-}"
    [ -z "$v" ] && return 0
    case "$v" in
        *change_me*|*change-me*|brainsos_*_secret*|admin_mail_pass|operator_mail_pass)
            return 0
            ;;
    esac
    return 1
}

resolve_mail_password() {
    local var_name="$1"
    local cur_val=""
    eval "cur_val=\"\${${var_name}:-}\""
    if ! is_mail_placeholder "$cur_val"; then
        printf '%s' "$cur_val"
        return 0
    fi
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "[ERROR] ${var_name} must be set (and ${ENV_FILE} does not exist to persist a generated secret)." >&2
        return 1
    fi
    local new_pw=""
    if command -v openssl >/dev/null 2>&1; then
        new_pw="$(openssl rand -hex 16 2>/dev/null || true)"
    fi
    if [[ -z "$new_pw" ]] && command -v python3 >/dev/null 2>&1; then
        new_pw="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
    fi
    if [[ -z "$new_pw" ]]; then
        echo "[ERROR] Unable to generate random password for ${var_name}." >&2
        return 1
    fi
    if [[ -x "$REPO_ROOT/scripts/control/env-upsert.sh" ]]; then
        "$REPO_ROOT/scripts/control/env-upsert.sh" --file "$ENV_FILE" "${var_name}=${new_pw}" >/dev/null
    else
        MAIL_ENV_FILE="$ENV_FILE" MAIL_VAR_NAME="$var_name" MAIL_VAR_VAL="$new_pw" python3 - << 'PYEOF'
import os, tempfile
env_file = os.environ["MAIL_ENV_FILE"]
key = os.environ["MAIL_VAR_NAME"]
val = os.environ["MAIL_VAR_VAL"]
with open(env_file, "r", encoding="utf-8") as f:
    lines = f.readlines()
out = []
found = False
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={val}\n")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={val}\n")
fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=os.path.dirname(os.path.abspath(env_file)))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(out)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, env_file)
except Exception:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    raise
PYEOF
    fi
    chmod 600 "$ENV_FILE" 2>/dev/null || true
    printf '%s' "$new_pw"
}

ADMIN_PASS="$(resolve_mail_password ADMIN_MAIL_PASSWORD)"
OPERATOR_PASS="$(resolve_mail_password OPERATOR_MAIL_PASSWORD)"
TERRASTELLA_PASS="$(resolve_mail_password TERRASTELLA_MAIL_PASSWORD)"
BAWTFORD_PASS="$(resolve_mail_password BAWTFORD_MAIL_PASSWORD)"
MARVIN_PASS="$(resolve_mail_password MARVIN_MAIL_PASSWORD)"
PING_PASS="$(resolve_mail_password PING_MAIL_PASSWORD)"
CLAUDE_PASS="$(resolve_mail_password CLAUDE_MAIL_PASSWORD)"
GPT_PASS="$(resolve_mail_password GPT_MAIL_PASSWORD)"
export ADMIN_MAIL_PASSWORD="$ADMIN_PASS" OPERATOR_MAIL_PASSWORD="$OPERATOR_PASS" \
    TERRASTELLA_MAIL_PASSWORD="$TERRASTELLA_PASS" BAWTFORD_MAIL_PASSWORD="$BAWTFORD_PASS" \
    MARVIN_MAIL_PASSWORD="$MARVIN_PASS" PING_MAIL_PASSWORD="$PING_PASS" \
    CLAUDE_MAIL_PASSWORD="$CLAUDE_PASS" GPT_MAIL_PASSWORD="$GPT_PASS"

hash_mail_password() {
    local raw_pw="$1"
    local hashed=""
    if command -v openssl >/dev/null 2>&1; then
        local digest
        digest="$(printf '%s' "${raw_pw}" | openssl passwd -6 -stdin 2>/dev/null || true)"
        if [[ "${digest}" == \$6\$* ]]; then
            hashed="{SHA512-CRYPT}${digest}"
        fi
    fi
    if [ -z "${hashed}" ] && command -v python3 >/dev/null 2>&1; then
        hashed="$(RAW_PW="${raw_pw}" python3 -c "import os, crypt; print('{SHA512-CRYPT}' + crypt.crypt(os.environ['RAW_PW'], crypt.mksalt(crypt.METHOD_SHA512)))" 2>/dev/null || true)"
    fi
    if [ -z "${hashed}" ]; then
        local mail_c
        mail_c="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-(app-|net-)?mail-server$' | head -n 1 || true)"
        if [ -n "${mail_c}" ]; then
            hashed="$(printf '%s\n%s\n' "${raw_pw}" "${raw_pw}" | docker exec -i "${mail_c}" doveadm pw -s SHA512-CRYPT 2>/dev/null || true)"
        fi
    fi
    if [ -z "${hashed}" ] || [ "${hashed}" = "{SHA512-CRYPT}" ]; then
        echo "[ERROR] Unable to generate {SHA512-CRYPT} password hash" >&2
        exit 1
    fi
    printf '%s' "${hashed}"
}

ADMIN_HASH="$(hash_mail_password "${ADMIN_PASS}")"
OPERATOR_HASH="$(hash_mail_password "${OPERATOR_PASS}")"
TERRASTELLA_HASH="$(hash_mail_password "${TERRASTELLA_PASS}")"
BAWTFORD_HASH="$(hash_mail_password "${BAWTFORD_PASS}")"
MARVIN_HASH="$(hash_mail_password "${MARVIN_PASS}")"
PING_HASH="$(hash_mail_password "${PING_PASS}")"
CLAUDE_HASH="$(hash_mail_password "${CLAUDE_PASS}")"
GPT_HASH="$(hash_mail_password "${GPT_PASS}")"

echo "[INFO] Generating hashed account directory in $CONFIG_DIR/users..."
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
admin@${d}:${ADMIN_HASH}:5000:5000::/var/mail/vmail/admin::
operator@${d}:${OPERATOR_HASH}:5000:5000::/var/mail/vmail/operator::
akadmin@${d}:${ADMIN_HASH}:5000:5000::/var/mail/vmail/admin::
terrastella@${d}:${TERRASTELLA_HASH}:5000:5000::/var/mail/vmail/terrastella::
bawtford@${d}:${BAWTFORD_HASH}:5000:5000::/var/mail/vmail/bawtford::
marvin@${d}:${MARVIN_HASH}:5000:5000::/var/mail/vmail/marvin::
ping@${d}:${PING_HASH}:5000:5000::/var/mail/vmail/ping::
claude@${d}:${CLAUDE_HASH}:5000:5000::/var/mail/vmail/claude::
gpt@${d}:${GPT_HASH}:5000:5000::/var/mail/vmail/gpt::
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
guide@${d} bawtford@${d}
security@${d} bawtford@${d}
librarian@${d} bawtford@${d}
system@${d} bawtford@${d}
EOF
if [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "admin" ]]; then
    echo "${ADMIN_USER}@${d}:${ADMIN_HASH}:5000:5000::/var/mail/vmail/admin::" >> "$CONFIG_DIR/users"
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

# Seed / update the 5 interactive onboarding emails in administrator & superuser Maildirs (#357)
if [[ -f "$REPO_ROOT/scripts/control/send-welcome-email.py" ]]; then
    echo "[INFO] Seeding 5 interactive onboarding emails into $VMAIL_DIR..."
    python3 "$REPO_ROOT/scripts/control/send-welcome-email.py" \
        --repo-root "$REPO_ROOT" \
        --vmail-dir "$VMAIL_DIR" || true
fi

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
# Postfix/Dovecot container runs as UID/GID 5000:5000; SnappyMail runs as www-data (UID 82 on Alpine)
chown 5000:5000 "$MAIL_DIR" 2>/dev/null || true
chmod 0750 "$MAIL_DIR" 2>/dev/null || true
chown -R 5000:5000 "$VMAIL_DIR" "$CONFIG_DIR" 2>/dev/null || true
find "$VMAIL_DIR" "$CONFIG_DIR" -type d -exec chmod 0750 {} + 2>/dev/null || true
find "$VMAIL_DIR" "$CONFIG_DIR" -type f -exec chmod 0640 {} + 2>/dev/null || true
chown -R 82:82 "$SNAPPY_DIR" 2>/dev/null || true
find "$SNAPPY_DIR" -type d -exec chmod 0750 {} + 2>/dev/null || true
find "$SNAPPY_DIR" -type f -exec chmod 0640 {} + 2>/dev/null || true
if docker image inspect alpine:latest >/dev/null 2>&1; then
    docker run --rm -v "$MAIL_DIR:/mail" alpine sh -c "chown 5000:5000 /mail && chmod 0750 /mail && chown -R 5000:5000 /mail/vmail /mail/config && find /mail/vmail /mail/config -type d -exec chmod 0750 {} + && find /mail/vmail /mail/config -type f -exec chmod 0640 {} + && chown -R 82:82 /mail/snappymail && find /mail/snappymail -type d -exec chmod 0750 {} + && find /mail/snappymail -type f -exec chmod 0640 {} +" 2>/dev/null || true
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
