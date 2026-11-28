#!/usr/bin/env bash
# ==============================================================================
# brainsOS: SOGo Groupware Daemon & Alarm Dispatcher Entrypoint
# Initializes isolated database, seeds users, starts memcached, launches the
# 1-minute alarm notification loop, and starts sogod.
# ==============================================================================
set -euo pipefail

render_sogo_nginx_conf() {
    local template_arg="${1:-}"
    local output_path="${2:-${SOGO_NGINX_OUTPUT_PATH:-/etc/nginx/sites-enabled/default}}"
    local template_path="${template_arg:-${SOGO_NGINX_TEMPLATE_PATH:-/etc/nginx/sites-available/default.template}}"
    local tmp_path="${output_path}.tmp"

    if [ -z "${template_arg}" ] && [ -z "${SOGO_NGINX_TEMPLATE_PATH:-}" ] && [ ! -f "${template_path}" ]; then
        template_path="/etc/nginx/sites-available/default"
    fi
    if [ ! -f "${template_path}" ]; then
        echo "[BRAINSOS-SOGO] ERROR: nginx template not found: ${template_path}" >&2
        return 1
    fi

    local effective_caddy_token="${CADDY_INGRESS_TOKEN:-}"
    if [ -z "${effective_caddy_token}" ] \
       || [[ ! "${effective_caddy_token}" =~ ^[A-Za-z0-9._-]{16,256}$ ]] \
       || [[ "${effective_caddy_token}" == *__CADDY_INGRESS_TOKEN__* ]]; then
        echo "[BRAINSOS-SOGO] WARNING: CADDY_INGRESS_TOKEN unset or invalid; failing closed (403)." >&2
        effective_caddy_token="failclosed-$(openssl rand -hex 32)"
    fi

    mkdir -p "$(dirname "${output_path}")"
    CADDY_INGRESS_TOKEN_RENDER="${effective_caddy_token}" awk '
      BEGIN {
        tok = ENVIRON["CADDY_INGRESS_TOKEN_RENDER"]
        ph = "__CADDY_INGRESS_TOKEN__"
        ph_len = length(ph)
      }
      {
        out = ""
        rest = $0
        idx = index(rest, ph)
        while (idx > 0) {
          out = out substr(rest, 1, idx - 1) tok
          rest = substr(rest, idx + ph_len)
          idx = index(rest, ph)
        }
        print out rest
      }
    ' "${template_path}" > "${tmp_path}"

    if [ "$(id -u)" -eq 0 ]; then
        chown root:root "${tmp_path}"
    fi
    chmod 600 "${tmp_path}"
    mv -f "${tmp_path}" "${output_path}"
}

if [ "${1:-}" = "--render-nginx-only" ]; then
    render_sogo_nginx_conf "${2:-}" "${3:-}"
    exit 0
fi

echo "[BRAINSOS-SOGO] Initializing SOGo Groupware Stack..."

# Ensure spool, log, and run directories exist and are owned by sogo user
mkdir -p /var/spool/sogo /var/log/sogo /var/run/sogo /etc/sogo
chown -R sogo:sogo /var/spool/sogo /var/log/sogo /var/run/sogo /etc/sogo 2>/dev/null || true
chmod 775 /var/spool/sogo 2>/dev/null || true

DB_HOST="${SOGO_DB_HOST:-brainsos-sogo-db}"
DB_PORT="${SOGO_DB_PORT:-5432}"
DB_USER="${SOGO_DB_USER:-sogo}"
DB_PASS="${SOGO_DB_PASSWORD:?SOGO_DB_PASSWORD must be set}"
DB_NAME="${SOGO_DB_NAME:-sogo}"

export PGPASSWORD="${DB_PASS}"

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:?ADMIN_MAIL_PASSWORD must be set}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:?OPERATOR_MAIL_PASSWORD must be set}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:?TERRASTELLA_MAIL_PASSWORD must be set}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:?BAWTFORD_MAIL_PASSWORD must be set}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:?MARVIN_MAIL_PASSWORD must be set}"
PING_PASS="${PING_MAIL_PASSWORD:?PING_MAIL_PASSWORD must be set}"
CLAUDE_PASS="${CLAUDE_MAIL_PASSWORD:?CLAUDE_MAIL_PASSWORD must be set}"
GPT_PASS="${GPT_MAIL_PASSWORD:?GPT_MAIL_PASSWORD must be set}"

# Hash SOGo mailbox credentials using SHA512-CRYPT instead of plaintext (#388)
sogo_hash_pw() {
    local raw_pw="$1"
    local hashed=""
    if command -v openssl >/dev/null 2>&1; then
        local digest
        digest="$(printf '%s' "${raw_pw}" | openssl passwd -6 -stdin 2>/dev/null || true)"
        if [[ "${digest}" == \$6\$* ]]; then
            hashed="{SHA512-CRYPT}${digest}"
        fi
    fi
    if { [ -z "${hashed}" ] || [ "${hashed}" = "{SHA512-CRYPT}" ]; } && command -v python3 >/dev/null 2>&1; then
        hashed="$(RAW_PW="${raw_pw}" python3 -c "import os, crypt; print('{SHA512-CRYPT}' + crypt.crypt(os.environ['RAW_PW'], crypt.mksalt(crypt.METHOD_SHA512)))" 2>/dev/null || true)"
    fi
    if [ -z "${hashed}" ] || [ "${hashed}" = "{SHA512-CRYPT}" ]; then
        echo "[BRAINSOS-SOGO] ERROR: unable to generate SHA512-CRYPT password hash" >&2
        exit 1
    fi
    printf '%s' "${hashed}"
}

ADMIN_PASS="$(sogo_hash_pw "${ADMIN_PASS}")"
OPERATOR_PASS="$(sogo_hash_pw "${OPERATOR_PASS}")"
TERRASTELLA_PASS="$(sogo_hash_pw "${TERRASTELLA_PASS}")"
BAWTFORD_PASS="$(sogo_hash_pw "${BAWTFORD_PASS}")"
MARVIN_PASS="$(sogo_hash_pw "${MARVIN_PASS}")"
PING_PASS="$(sogo_hash_pw "${PING_PASS}")"
CLAUDE_PASS="$(sogo_hash_pw "${CLAUDE_PASS}")"
GPT_PASS="$(sogo_hash_pw "${GPT_PASS}")"

# 1. Wait for isolated SOGo database host to become available and accept authentication
echo "[BRAINSOS-SOGO] Waiting for database ${DB_HOST}:${DB_PORT} and validating credentials..."
AUTH_READY=false
for i in $(seq 1 30); do
    if pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" >/dev/null 2>&1; then
        if psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "SELECT 1" >/dev/null 2>&1; then
            AUTH_READY=true
            break
        fi
    fi
    sleep 1
done

if [ "${AUTH_READY}" != "true" ]; then
    echo "[BRAINSOS-SOGO] WARNING: Authentication to ${DB_HOST} not established after 30s. Attempting to proceed..."
fi

echo "[BRAINSOS-SOGO] Database server reachable and authenticated. Ensuring database '${DB_NAME}' exists..."
if ! psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -tA \
    -v db_name="${DB_NAME}" <<'EOSQL' 2>/dev/null | grep -qx '1'; then
SELECT 1 FROM pg_database WHERE datname = :'db_name';
EOSQL
    psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres \
        -v db_name="${DB_NAME}" -v db_user="${DB_USER}" <<'EOSQL' >/dev/null 2>&1 || true
CREATE DATABASE :"db_name" OWNER :"db_user";
EOSQL
fi

MAIL_DOMAIN="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-brainsos.local}}}"
ADMIN_USER="${BRAINSOS_ADMIN_USERNAME:-admin}"
ADMIN_EMAIL="${ADMIN_USER}@${MAIL_DOMAIN}"
OP_EMAIL="operator@${MAIL_DOMAIN}"
ADMIN_DOM_UID="admin@${MAIL_DOMAIN}"
AKADMIN_DOM_UID="akadmin@${MAIL_DOMAIN}"
SU_LEGACY_UID="${ADMIN_USER}@brainsos.local"
SU_DOM_UID="${ADMIN_USER}@${MAIL_DOMAIN}"

# 2. Initialize sogo_users table and seed fleet accounts if missing
echo "[BRAINSOS-SOGO] Ensuring sogo_users schema and seeding accounts..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
    -v admin_pass="${ADMIN_PASS}" \
    -v operator_pass="${OPERATOR_PASS}" \
    -v terrastella_pass="${TERRASTELLA_PASS}" \
    -v bawtford_pass="${BAWTFORD_PASS}" \
    -v marvin_pass="${MARVIN_PASS}" \
    -v ping_pass="${PING_PASS}" \
    -v claude_pass="${CLAUDE_PASS}" \
    -v gpt_pass="${GPT_PASS}" \
    -v admin_user="${ADMIN_USER}" \
    -v mail_domain="${MAIL_DOMAIN}" \
    -v admin_email="${ADMIN_EMAIL}" \
    -v op_email="${OP_EMAIL}" <<'EOSQL' || echo "[BRAINSOS-SOGO] WARNING: Primary sogo_users seed returned non-zero; continuing..."
    CREATE TABLE IF NOT EXISTS sogo_users (
        c_uid VARCHAR(128) PRIMARY KEY,
        c_name VARCHAR(128) NOT NULL,
        c_password VARCHAR(128) NOT NULL,
        c_cn VARCHAR(128) NOT NULL,
        mail VARCHAR(128) NOT NULL
    );

    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
        ('admin@brainsos.local', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
        ('operator@brainsos.local', 'operator', :'operator_pass', 'Human Operator', :'op_email'),
        ('terrastella@brainsos.local', 'terrastella', :'terrastella_pass', 'Terrastella Agent', 'terrastella@' || :'mail_domain'),
        ('bawtford@brainsos.local', 'bawtford', :'bawtford_pass', 'Bawtford Agent', 'bawtford@' || :'mail_domain'),
        ('marvin@brainsos.local', 'marvin', :'marvin_pass', 'Marvin Agent', 'marvin@' || :'mail_domain'),
        ('ping@brainsos.local', 'ping', :'ping_pass', 'Ping Autoresponder Agent', 'ping@' || :'mail_domain'),
        ('claude@brainsos.local', 'claude', :'claude_pass', 'Claude Demo Agent', 'claude@' || :'mail_domain'),
        ('gpt@brainsos.local', 'gpt', :'gpt_pass', 'GPT Demo Agent', 'gpt@' || :'mail_domain'),
        ('akadmin@brainsos.local', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
        ('admin', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
        ('akadmin', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
        ('operator', 'operator', :'operator_pass', 'Human Operator', :'op_email'),
        ('terrastella', 'terrastella', :'terrastella_pass', 'Terrastella Agent', 'terrastella@' || :'mail_domain'),
        ('bawtford', 'bawtford', :'bawtford_pass', 'Bawtford Agent', 'bawtford@' || :'mail_domain'),
        ('marvin', 'marvin', :'marvin_pass', 'Marvin Agent', 'marvin@' || :'mail_domain'),
        ('ping', 'ping', :'ping_pass', 'Ping Autoresponder Agent', 'ping@' || :'mail_domain'),
        ('claude', 'claude', :'claude_pass', 'Claude Demo Agent', 'claude@' || :'mail_domain'),
        ('gpt', 'gpt', :'gpt_pass', 'GPT Demo Agent', 'gpt@' || :'mail_domain')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;

    UPDATE sogo_users SET mail = :'admin_email' WHERE c_name = 'admin';
    UPDATE sogo_users SET mail = c_name || '@' || :'mail_domain' WHERE c_name IN ('operator', 'terrastella', 'bawtford', 'marvin', 'ping', 'claude', 'gpt');
EOSQL

if [ -n "${ADMIN_USER}" ] && [ "${ADMIN_USER}" != "admin" ] && [ "${ADMIN_USER}" != "akadmin" ]; then
    psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -v admin_user="${ADMIN_USER}" \
        -v su_legacy_uid="${SU_LEGACY_UID}" \
        -v admin_pass="${ADMIN_PASS}" \
        -v admin_email="${ADMIN_EMAIL}" <<'EOSQL' || true
        INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
            (:'admin_user', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
            (:'su_legacy_uid', 'admin', :'admin_pass', 'System Administrator', :'admin_email')
        ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;
EOSQL
fi

if [ "${MAIL_DOMAIN}" != "brainsos.local" ]; then
    psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        -v admin_dom_uid="${ADMIN_DOM_UID}" \
        -v op_email="${OP_EMAIL}" \
        -v akadmin_dom_uid="${AKADMIN_DOM_UID}" \
        -v admin_pass="${ADMIN_PASS}" \
        -v operator_pass="${OPERATOR_PASS}" \
        -v terrastella_pass="${TERRASTELLA_PASS}" \
        -v bawtford_pass="${BAWTFORD_PASS}" \
        -v marvin_pass="${MARVIN_PASS}" \
        -v ping_pass="${PING_PASS}" \
        -v claude_pass="${CLAUDE_PASS}" \
        -v gpt_pass="${GPT_PASS}" \
        -v mail_domain="${MAIL_DOMAIN}" \
        -v admin_email="${ADMIN_EMAIL}" <<'EOSQL' || true
        INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
            (:'admin_dom_uid', 'admin', :'admin_pass', 'System Administrator', :'admin_email'),
            (:'op_email', 'operator', :'operator_pass', 'Human Operator', :'op_email'),
            ('terrastella@' || :'mail_domain', 'terrastella', :'terrastella_pass', 'Terrastella Agent', 'terrastella@' || :'mail_domain'),
            ('bawtford@' || :'mail_domain', 'bawtford', :'bawtford_pass', 'Bawtford Agent', 'bawtford@' || :'mail_domain'),
            ('marvin@' || :'mail_domain', 'marvin', :'marvin_pass', 'Marvin Agent', 'marvin@' || :'mail_domain'),
            ('ping@' || :'mail_domain', 'ping', :'ping_pass', 'Ping Autoresponder Agent', 'ping@' || :'mail_domain'),
            ('claude@' || :'mail_domain', 'claude', :'claude_pass', 'Claude Demo Agent', 'claude@' || :'mail_domain'),
            ('gpt@' || :'mail_domain', 'gpt', :'gpt_pass', 'GPT Demo Agent', 'gpt@' || :'mail_domain'),
            (:'akadmin_dom_uid', 'admin', :'admin_pass', 'System Administrator', :'admin_email')
        ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;
EOSQL
    if [ -n "${ADMIN_USER}" ] && [ "${ADMIN_USER}" != "admin" ] && [ "${ADMIN_USER}" != "akadmin" ]; then
        psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
            -v su_dom_uid="${SU_DOM_UID}" \
            -v admin_pass="${ADMIN_PASS}" \
            -v admin_email="${ADMIN_EMAIL}" <<'EOSQL' || true
            INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
                (:'su_dom_uid', 'admin', :'admin_pass', 'System Administrator', :'admin_email')
            ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;
EOSQL
    fi
fi

psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
    -v admin_user="${ADMIN_USER}" <<'EOSQL' || true
    CREATE OR REPLACE VIEW sogo_addressbook AS
    SELECT c_uid, c_name, c_cn, mail
    FROM sogo_users
    WHERE c_uid IN (:'admin_user', 'operator', 'terrastella', 'bawtford', 'marvin', 'ping', 'claude', 'gpt');
EOSQL
echo "[BRAINSOS-SOGO] sogo_users verification complete."

# 3. Start local memcached daemon
echo "[BRAINSOS-SOGO] Starting in-container memcached..."
memcached -u sogo -d -p 11211 -m 64
sleep 1

# 4. Start sogo-ealarms-notify background cron loop (1-minute interval)
echo "[BRAINSOS-SOGO] Spawning background sogo-ealarms-notify daemon (60s cycle)..."
(
    while true; do
        sleep 60
        gosu sogo /usr/sbin/sogo-ealarms-notify 2>&1 || true
    done
) &

# 5. Render nginx config with X-Caddy-Ingress-Token and start nginx dispatcher on port 20000
echo "[BRAINSOS-SOGO] Patching SOGo strict-mode mailto handler and starting nginx dispatcher on port 20000..."
sed -i 's/delete e\.target\.attributes\.target/e.target.removeAttribute("target")/g' /usr/lib/GNUstep/SOGo/WebServerResources/js/Mailer.services.js 2>/dev/null || true
sed -i 's/delete \$event\.target\.attributes\.target/$event.target.removeAttribute("target")/g' /usr/lib/GNUstep/SOGo/WebServerResources/js/Mailer/MessageController.js 2>/dev/null || true

render_sogo_nginx_conf
nginx -t
service nginx start

# 5b. Render dynamic sogo.conf with live credentials atomically via Python (no sed)
if [ -f /etc/sogo/sogo.conf.template ]; then
    echo "[BRAINSOS-SOGO] Generating /etc/sogo/sogo.conf from template..."
    SOGO_CONF_TEMPLATE="/etc/sogo/sogo.conf.template" \
    SOGO_CONF_OUT="/etc/sogo/sogo.conf" \
    SOGO_RENDER_HOST="${DB_HOST}" \
    SOGO_RENDER_PORT="${DB_PORT}" \
    SOGO_RENDER_USER="${DB_USER}" \
    SOGO_RENDER_PASS="${DB_PASS}" \
    SOGO_RENDER_NAME="${DB_NAME}" \
    SOGO_RENDER_DOMAIN="${MAIL_DOMAIN}" \
    python3 - << 'PYEOF'
import os
import pwd
import re
import tempfile
import urllib.parse

template_path = os.environ["SOGO_CONF_TEMPLATE"]
output_path = os.environ["SOGO_CONF_OUT"]
db_host = os.environ["SOGO_RENDER_HOST"]
db_port = os.environ["SOGO_RENDER_PORT"]
db_user = urllib.parse.quote(os.environ["SOGO_RENDER_USER"], safe="")
db_pass = urllib.parse.quote(os.environ["SOGO_RENDER_PASS"], safe="")
db_name = urllib.parse.quote(os.environ["SOGO_RENDER_NAME"], safe="")
mail_domain = os.environ["SOGO_RENDER_DOMAIN"].strip()
if not re.fullmatch(r"[A-Za-z0-9.-]+", mail_domain):
    raise ValueError(f"Invalid SOGO mail domain: {mail_domain!r}")

with open(template_path, "r", encoding="utf-8") as f:
    rendered = f.read()

replacements = {
    "__SOGO_DB_USER__": db_user,
    "__SOGO_DB_PASSWORD__": db_pass,
    "__SOGO_DB_HOST__": db_host,
    "__SOGO_DB_PORT__": db_port,
    "__SOGO_DB_NAME__": db_name,
    "__SOGO_MAIL_DOMAIN__": mail_domain,
}
for ph, val in replacements.items():
    rendered = rendered.replace(ph, val)

out_dir = os.path.dirname(output_path)
fd, tmp_path = tempfile.mkstemp(prefix=".sogo.conf.", dir=out_dir)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.chmod(tmp_path, 0o600)
    if os.geteuid() == 0:
        try:
            pw = pwd.getpwnam("sogo")
            os.chown(tmp_path, pw.pw_uid, pw.pw_gid)
        except KeyError:
            pass
    os.replace(tmp_path, output_path)
except Exception:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    raise
PYEOF
fi

# 6. Start main sogod process in foreground on loopback port 20001
echo "[BRAINSOS-SOGO] Starting sogod daemon on loopback port 20001..."
exec gosu sogo /usr/sbin/sogod -WONoDetach YES -WOUseWatchDog NO -WONoDebugMode YES -WOLogFile -
