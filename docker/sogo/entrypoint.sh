#!/usr/bin/env bash
# ==============================================================================
# Project Titan: SOGo Groupware Daemon & Alarm Dispatcher Entrypoint
# Initializes isolated database, seeds users, starts memcached, launches the
# 1-minute alarm notification loop, and starts sogod.
# ==============================================================================
set -euo pipefail

echo "[TITAN-SOGO] Initializing SOGo Groupware Stack..."

DB_HOST="${SOGO_DB_HOST:-titan-sogo-db}"
DB_PORT="${SOGO_DB_PORT:-5432}"
DB_USER="${SOGO_DB_USER:-sogo}"
DB_PASS="${SOGO_DB_PASSWORD:-sogo_secret_pass}"
DB_NAME="${SOGO_DB_NAME:-sogo}"

export PGPASSWORD="${DB_PASS}"

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-titan_admin_mail_secret_change_me}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-titan_operator_mail_secret_change_me}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-titan_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-titan_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-titan_marvin_mail_secret_change_me}"

# 1. Wait for isolated SOGo database to become available
echo "[TITAN-SOGO] Waiting for database ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; do
    sleep 1
done
echo "[TITAN-SOGO] Database connected successfully."

# 2. Initialize sogo_users table and seed fleet accounts if missing
echo "[TITAN-SOGO] Ensuring sogo_users schema and seeding accounts..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 <<-EOSQL
    CREATE TABLE IF NOT EXISTS sogo_users (
        c_uid VARCHAR(128) PRIMARY KEY,
        c_name VARCHAR(128) NOT NULL,
        c_password VARCHAR(128) NOT NULL,
        c_cn VARCHAR(128) NOT NULL,
        mail VARCHAR(128) NOT NULL
    );

    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
        ('admin@titan.local', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@titan.local'),
        ('operator@titan.local', 'operator', '${OPERATOR_PASS}', 'Human Operator', 'operator@titan.local'),
        ('terrastella@titan.local', 'terrastella', '${TERRASTELLA_PASS}', 'Terrastella Agent', 'terrastella@titan.local'),
        ('bawtford@titan.local', 'bawtford', '${BAWTFORD_PASS}', 'Bawtford Agent', 'bawtford@titan.local'),
        ('marvin@titan.local', 'marvin', '${MARVIN_PASS}', 'Marvin Agent', 'marvin@titan.local'),
        ('admin', 'admin', '${ADMIN_PASS}', 'System Administrator', 'admin@titan.local'),
        ('operator', 'operator', '${OPERATOR_PASS}', 'Human Operator', 'operator@titan.local'),
        ('terrastella', 'terrastella', '${TERRASTELLA_PASS}', 'Terrastella Agent', 'terrastella@titan.local'),
        ('bawtford', 'bawtford', '${BAWTFORD_PASS}', 'Bawtford Agent', 'bawtford@titan.local'),
        ('marvin', 'marvin', '${MARVIN_PASS}', 'Marvin Agent', 'marvin@titan.local')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password;
EOSQL
echo "[TITAN-SOGO] sogo_users verification complete."

# 3. Start local memcached daemon
echo "[TITAN-SOGO] Starting in-container memcached..."
memcached -u sogo -d -p 11211 -m 64
sleep 1

# 4. Start sogo-ealarms-notify background cron loop (1-minute interval)
echo "[TITAN-SOGO] Spawning background sogo-ealarms-notify daemon (60s cycle)..."
(
    while true; do
        sleep 60
        gosu sogo /usr/sbin/sogo-ealarms-notify 2>&1 || true
    done
) &

# 5. Start nginx web server for WebServerResources static assets & reverse proxy
echo "[TITAN-SOGO] Starting in-container nginx dispatcher on port 20000..."
service nginx start

# 6. Start main sogod process in foreground on loopback port 20001
echo "[TITAN-SOGO] Starting sogod daemon on loopback port 20001..."
exec gosu sogo /usr/sbin/sogod -WONoDetach YES -WOUseWatchDog NO -WONoDebugMode YES -WOLogFile -

