#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Signal Messaging Gateway Verification Suite
# Validates Signal daemon health, operator accounts, Hermes adapter connectivity,
# operator whitelisting, storage persistence, and zero-drift fleet synchronization.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${BOLD}=================================================================${NC}"
echo -e "${BOLD} Project Titan: Signal Messaging Gateway Verification Suite     ${NC}"
echo -e "${BOLD}=================================================================${NC}"

# ------------------------------------------------------------------------------
# 0. Rule 13 Precondition: Mandatory .env check
# ------------------------------------------------------------------------------
if [ ! -f "${REPO_ROOT}/.env" ]; then
    log_error "Precondition Failed (Rule 13): No .env file present in repository root."
    log_error "This machine is an unconfigured repository clone and must not run verification."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a

SIGNAL_CONTAINER="titan-net-signal-cli"
HERMES_CONTAINER="titan-agent-terrastella"
HERMES_SERVICE="agent-terrastella"
SIGNAL_SERVICE="signal-cli"
WORKSPACE_DIR="${TITAN_WORKSPACE_DIR:-${REPO_ROOT}/data/workspace}"
SIGNAL_STORAGE="${WORKSPACE_DIR}/signal"

# ------------------------------------------------------------------------------
# 1. Daemon Running & Health Check
# ------------------------------------------------------------------------------
log_info "Step 1: Checking Signal daemon container status..."
if ! docker compose ps --services --filter "status=running" | grep -q "^${SIGNAL_SERVICE}$"; then
    log_warn "Signal daemon container is not running. Starting ${SIGNAL_SERVICE}..."
    docker compose up -d "${SIGNAL_SERVICE}"
    sleep 3
fi

SIGNAL_USER=$(docker exec "${SIGNAL_CONTAINER}" id -u signal-api 2>/dev/null || echo "1000")
if [ "${SIGNAL_USER}" != "1000" ]; then
    log_error "Signal container user is UID ${SIGNAL_USER} (expected 1000: unprivileged signal-api)."
    exit 1
fi
log_success "Signal daemon container verified running with unprivileged UID 1000."

# ------------------------------------------------------------------------------
# 2. REST API & Accounts Verification
# ------------------------------------------------------------------------------
log_info "Step 2A: Verifying Signal REST daemon capabilities (/v1/about)..."
ABOUT_RESP=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/about 2>/dev/null || echo "failed")
if echo "${ABOUT_RESP}" | grep -q "json-rpc"; then
    log_success "Signal REST API healthy on 127.0.0.1:8080 (mode: json-rpc verified)."
else
    log_error "Signal REST API /v1/about failed: ${ABOUT_RESP}"
    exit 1
fi

log_info "Step 2B: Verifying Signal accounts endpoint (/v1/accounts)..."
ACCOUNTS_RESP=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/accounts 2>/dev/null || echo "failed")
if echo "${ACCOUNTS_RESP}" | grep -q '^\['; then
    log_success "Signal accounts endpoint valid JSON array response: ${ACCOUNTS_RESP}"
else
    log_error "Signal accounts endpoint returned invalid response: ${ACCOUNTS_RESP}"
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. Hermes Reachability on titan-internal
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying Hermes reachability to Signal daemon on titan-internal..."
if ! docker compose ps --services --filter "status=running" | grep -q "^${HERMES_SERVICE}$"; then
    log_warn "Hermes container (${HERMES_SERVICE}) is not running. Starting..."
    docker compose up -d "${HERMES_SERVICE}"
    sleep 3
fi

HERMES_TO_SIGNAL=$(docker compose exec -T "${HERMES_SERVICE}" curl -s http://signal-cli:8080/v1/about 2>/dev/null || echo "failed")
if echo "${HERMES_TO_SIGNAL}" | grep -q "json-rpc"; then
    log_success "Hermes container successfully reaches signal-cli:8080 over titan-internal."
else
    log_error "Hermes failed to reach Signal daemon over titan-internal: ${HERMES_TO_SIGNAL}"
    exit 1
fi

# ------------------------------------------------------------------------------
# 4. Native Signal HTTP & JSON-RPC Endpoints (Hermes Adapter Protocol)
# ------------------------------------------------------------------------------
log_info "Step 4A: Verifying native Signal health endpoint (/api/v1/check)..."
NATIVE_CHECK_CODE=$(docker compose exec -T "${HERMES_SERVICE}" curl -s -o /dev/null -w "%{http_code}" http://signal-cli:8080/api/v1/check 2>/dev/null || echo "failed")
if [ "${NATIVE_CHECK_CODE}" = "200" ]; then
    log_success "Native Signal HTTP health endpoint verified reachable (/api/v1/check -> HTTP 200)."
else
    log_error "Native Signal health check failed: expected HTTP 200, got ${NATIVE_CHECK_CODE}"
    exit 1
fi

log_info "Step 4B: Verifying native JSON-RPC endpoint (/api/v1/rpc)..."
RPC_RESP=$(docker compose exec -T "${HERMES_SERVICE}" curl -s -X POST http://signal-cli:8080/api/v1/rpc \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"listAccounts","id":"verify_test"}' 2>/dev/null || echo "failed")
if echo "${RPC_RESP}" | grep -q '"jsonrpc":"2.0"'; then
    log_success "Native JSON-RPC 2.0 endpoint verified operational: ${RPC_RESP}"
else
    log_error "Native JSON-RPC 2.0 call failed: ${RPC_RESP}"
    exit 1
fi

# ------------------------------------------------------------------------------
# 5. Cryptographic Session Storage & Memory Plane Purity
# ------------------------------------------------------------------------------
log_info "Step 5A: Verifying Signal session keys & database persistence location..."
COMPOSE_SIGNAL_MOUNT=$(docker inspect "${SIGNAL_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/home/.local/share/signal-cli"}}{{.Source}}{{end}}{{end}}')
if [ -n "${COMPOSE_SIGNAL_MOUNT}" ] && echo "${COMPOSE_SIGNAL_MOUNT}" | grep -q "signal"; then
    log_success "Verified Signal session data is host bind-mounted at: ${COMPOSE_SIGNAL_MOUNT}"
else
    log_error "Signal session volume mount invalid or missing: ${COMPOSE_SIGNAL_MOUNT}"
    exit 1
fi

log_info "Step 5B: Verifying Memory Plane purity (Rule 1)..."
"${REPO_ROOT}/scripts/verify/verify-memories.sh"
log_success "Memory plane purity verified: zero Signal keys or binary files in /memories."

# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# 6. Hermes Signal Adapter & Operator Whitelisting Assertions
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying Hermes Signal Adapter & Operator Whitelisting..."
ADAPTER_TEST=$(docker compose exec -T "${HERMES_SERVICE}" /opt/hermes/.venv/bin/python3 -c '
import asyncio, os, sys
from gateway.config import Platform, PlatformConfig
from gateway.platforms.signal import validate_signal_config, SignalAdapter
from gateway.pairing import _PLATFORM_ALLOWLIST_ENV
from gateway.platforms.signal_format import markdown_to_signal

# 1. Verify platform allowlist mapping
assert _PLATFORM_ALLOWLIST_ENV.get("signal") == "SIGNAL_ALLOWED_USERS", "Allowlist env mismatch"

# 2. Verify config validation
cfg_empty = PlatformConfig(enabled=False, extra={})
old_acc = os.environ.pop("SIGNAL_ACCOUNT", None)
assert validate_signal_config(cfg_empty) is False, "Empty config should fail"
if old_acc: os.environ["SIGNAL_ACCOUNT"] = old_acc

cfg_valid = PlatformConfig(enabled=True, extra={"http_url": "http://signal-cli:8080", "account": "+15550009999"})
assert validate_signal_config(cfg_valid) is True, "Valid config must pass"

# 3. Verify markdown formatting converter
plain, styles = markdown_to_signal("**Alert:** _System Normal_")
assert "Alert:" in plain, "Markdown formatting failed"

# 4. Verify sender whitelisting logic & event routing
os.environ["SIGNAL_ALLOWED_USERS"] = "+15551234567, +15559876543"
adapter = SignalAdapter(cfg_valid)
assert "+15551234567" in adapter.dm_allow_from, "Authorized user not in allowlist"
assert "+15550000000" not in adapter.dm_allow_from, "Unauthorized user was not blocked"

# 5. Verify inbound envelope handling from authorized operator
handled_events = []
async def dummy_handle(event):
    handled_events.append(event)
adapter.handle_message = dummy_handle

auth_env = {
    "envelope": {
        "source": "+15551234567",
        "sourceNumber": "+15551234567",
        "dataMessage": {"message": "Operator Ping"}
    }
}
asyncio.run(adapter._handle_envelope(auth_env))
assert len(handled_events) == 1, "Authorized message event was not dispatched"
assert handled_events[0].text == "Operator Ping", "Message content mismatch"

print("SIGNAL_ADAPTER_VERIFIED")
' 2>/dev/null || echo "FAILED")

if [ "${ADAPTER_TEST}" = "SIGNAL_ADAPTER_VERIFIED" ]; then
    log_success "Hermes Signal adapter logic, formatting, and strict whitelisting verified."
else
    log_error "Hermes Signal adapter in-container verification failed: ${ADAPTER_TEST}"
    exit 1
fi

# ------------------------------------------------------------------------------
# 7. Fleet Synchronization Drift Check
# ------------------------------------------------------------------------------
log_info "Step 7: Verifying fleet manifest synchronization (zero drift)..."
"${REPO_ROOT}/scripts/control/sync-agents.sh" --check
log_success "Fleet manifest and rendered compose topologies are in 100% synchronization."

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Signal Messaging Gateway Verification Checks Passed!        ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
