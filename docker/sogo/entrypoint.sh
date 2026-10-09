#!/usr/bin/env bash
# ==============================================================================
# brainsOS: SOGo Groupware Daemon & Alarm Dispatcher Entrypoint
# Initializes isolated database, seeds users, starts memcached, launches the
# 1-minute alarm notification loop, and starts sogod.
# ==============================================================================
set -euo pipefail

echo "[BRAINSOS-SOGO] Initializing SOGo Groupware Stack..."

# Ensure spool, log, and run directories exist and are owned by sogo user
mkdir -p /var/spool/sogo /var/log/sogo /var/run/sogo /etc/sogo
chown -R sogo:sogo /var/spool/sogo /var/log/sogo /var/run/sogo /etc/sogo 2>/dev/null || true
chmod 775 /var/spool/sogo 2>/dev/null || true

DB_HOST="${SOGO_DB_HOST:-brainsos-sogo-db}"
DB_PORT="${SOGO_DB_PORT:-5432}"
DB_USER="${SOGO_DB_USER:-sogo}"
DB_PASS="${SOGO_DB_PASSWORD:-sogo_secret_pass}"
DB_NAME="${SOGO_DB_NAME:-sogo}"

export PGPASSWORD="${DB_PASS}"

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_mail_secret_change_me}}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_operator_mail_secret_change_me}}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-brainsos_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-brainsos_marvin_mail_secret_change_me}"
PING_PASS="${PING_MAIL_PASSWORD:-brainsos_ping_mail_secret_change_me}"

# 1. Wait for isolated SOGo database host to become available
echo "[BRAINSOS-SOGO] Waiting for database ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" >/dev/null 2>&1; do
    sleep 1
done
echo "[BRAINSOS-SOGO] Database server reachable. Ensuring database '${DB_NAME}' exists..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" 2>/dev/null | grep -q 1 || \
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null || true

MAIL_DOMAIN="${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-brainsos.local}}"

# 2. Initialize sogo_users table and seed fleet accounts if missing
echo "[BRAINSOS-SOGO] Ensuring sogo_users schema and seeding accounts..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<-EOSQL
    CREATE TABLE IF NOT EXISTS sogo_users (
        c_uid VARCHAR(128) PRIMARY KEY,
        c_name VARCHAR(128) NOT NULL,
        c_password VARCHAR(128) NOT NULL,
        c_cn VARCHAR(128) NOT NULL,
        mail VARCHAR(128) NOT NULL
    );

    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
        ('admin@brainsos.local', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@brainsos.local'),
        ('operator@brainsos.local', 'operator', '${OPERATOR_PASS}', 'Human Operator', 'operator@brainsos.local'),
        ('terrastella@brainsos.local', 'terrastella', '${TERRASTELLA_PASS}', 'Terrastella Agent', 'terrastella@brainsos.local'),
        ('bawtford@brainsos.local', 'bawtford', '${BAWTFORD_PASS}', 'Bawtford Agent', 'bawtford@brainsos.local'),
        ('marvin@brainsos.local', 'marvin', '${MARVIN_PASS}', 'Marvin Agent', 'marvin@brainsos.local'),
        ('ping@brainsos.local', 'ping', '${PING_PASS}', 'Ping Autoresponder Agent', 'ping@brainsos.local'),
        ('admin@${MAIL_DOMAIN}', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@${MAIL_DOMAIN}'),
        ('operator@${MAIL_DOMAIN}', 'operator', '${OPERATOR_PASS}', 'Human Operator', 'operator@${MAIL_DOMAIN}'),
        ('terrastella@${MAIL_DOMAIN}', 'terrastella', '${TERRASTELLA_PASS}', 'Terrastella Agent', 'terrastella@${MAIL_DOMAIN}'),
        ('bawtford@${MAIL_DOMAIN}', 'bawtford', '${BAWTFORD_PASS}', 'Bawtford Agent', 'bawtford@${MAIL_DOMAIN}'),
        ('marvin@${MAIL_DOMAIN}', 'marvin', '${MARVIN_PASS}', 'Marvin Agent', 'marvin@${MAIL_DOMAIN}'),
        ('ping@${MAIL_DOMAIN}', 'ping', '${PING_PASS}', 'Ping Autoresponder Agent', 'ping@${MAIL_DOMAIN}'),
        ('admin', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@${MAIL_DOMAIN}'),
        ('akadmin', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@${MAIL_DOMAIN}'),
        ('akadmin@${MAIL_DOMAIN}', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@${MAIL_DOMAIN}'),
        ('operator', 'operator', '${OPERATOR_PASS}', 'Human Operator', 'operator@${MAIL_DOMAIN}'),
        ('terrastella', 'terrastella', '${TERRASTELLA_PASS}', 'Terrastella Agent', 'terrastella@${MAIL_DOMAIN}'),
        ('bawtford', 'bawtford', '${BAWTFORD_PASS}', 'Bawtford Agent', 'bawtford@${MAIL_DOMAIN}'),
        ('marvin', 'marvin', '${MARVIN_PASS}', 'Marvin Agent', 'marvin@${MAIL_DOMAIN}'),
        ('ping', 'ping', '${PING_PASS}', 'Ping Autoresponder Agent', 'ping@${MAIL_DOMAIN}')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;
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

# 5. Start nginx web server for WebServerResources static assets & reverse proxy
echo "[BRAINSOS-SOGO] Starting in-container nginx dispatcher on port 20000..."
service nginx start

# 5b. Render dynamic sogo.conf with live credentials if template exists
if [ -f /etc/sogo/sogo.conf.template ]; then
    echo "[BRAINSOS-SOGO] Generating /etc/sogo/sogo.conf from template..."
    sed -e "s|sogo_secret_pass|${DB_PASS}|g" \
        -e "s|brainsos.local|${MAIL_DOMAIN}|g" \
        /etc/sogo/sogo.conf.template > /etc/sogo/sogo.conf
    chown sogo:sogo /etc/sogo/sogo.conf
    chmod 600 /etc/sogo/sogo.conf
fi

# 6. Start main sogod process in foreground on loopback port 20001
echo "[BRAINSOS-SOGO] Starting sogod daemon on loopback port 20001..."
exec gosu sogo /usr/sbin/sogod -WONoDetach YES -WOUseWatchDog NO -WONoDebugMode YES -WOLogFile -
