#!/usr/bin/env bash
# ==============================================================================
# Project Titan: SOGo Groupware & Isolated Database Provisioning Script
# Provisions dedicated SOGo storage directories, isolated database, and groupware.
# Replaces SnappyMail with SOGo for Webmail, CalDAV, and Reminders (Ticket #166).
# Rule 8 compliant (Script-Driven Discipline) & Rule 6 compliant (DB Isolation)
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
echo "[INFO] Project Titan: Provisioning SOGo Groupware & CalDAV Subsystem"
echo "[INFO] ======================================================================"

COMMS_DIR="${TITAN_COMMS_DIR:-$REPO_ROOT/data/comms}"
SOGO_DIR="$COMMS_DIR/sogo"
SOGO_DB_DIR="$SOGO_DIR/db"
SOGO_SPOOL_DIR="$SOGO_DIR/spool"

echo "[INFO] Target SOGo storage root: $SOGO_DIR"
mkdir -p "$SOGO_DB_DIR" "$SOGO_SPOOL_DIR"

# Ensure permissive access for unprivileged container users
if [ -d "$SOGO_DIR" ]; then
    chmod -R 777 "$SOGO_DIR" 2>/dev/null || true
fi

# 1. Build SOGo Image natively on ARM64 / Host
echo "[INFO] Building titan-sogo container image..."
docker build -t titan-sogo:latest "$REPO_ROOT/docker/sogo"

# 2. Stop old SnappyMail container if running
if docker ps --format '{{.Names}}' | grep -q "titan-net-snappymail"; then
    echo "[INFO] Stopping legacy SnappyMail container..."
    docker stop titan-net-snappymail 2>/dev/null || true
    docker rm titan-net-snappymail 2>/dev/null || true
fi

# 3. Launch isolated database and SOGo service
echo "[INFO] Launching isolated SOGo database and daemon..."
docker compose up -d sogo-db
echo "[INFO] Waiting for sogo-db to accept connections..."
sleep 3

docker compose up -d sogo

# 4. Wait for SOGo HTTP port (20000) readiness
echo "[INFO] Waiting for SOGo to report healthy on port 20000..."
MAX_RETRIES=30
RETRY_COUNT=0
READY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:20000/SOGo | grep -qE "200|302|401"; then
        READY=true
        break
    fi
    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ "$READY" = "true" ]; then
    echo "[SUCCESS] SOGo daemon is online and responding on http://127.0.0.1:20000/SOGo"
else
    echo "[WARN] SOGo did not respond within $MAX_RETRIES seconds. Checking docker logs..."
    docker logs --tail 30 titan-net-sogo || true
fi

# 5. Reload Caddy Ingress if running
if docker ps --format '{{.Names}}' | grep -q "titan-net-caddy"; then
    echo "[INFO] Reloading Caddy Ingress configuration..."
    docker exec titan-net-caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || true
fi

echo "[SUCCESS] SOGo Groupware subsystem setup complete!"
echo "[INFO] Webmail & CalDAV endpoints:"
echo "       - Direct:  http://127.0.0.1:20000/SOGo"
echo "       - Ingress: http://mail.localhost/ or http://mail.titan.local/"
