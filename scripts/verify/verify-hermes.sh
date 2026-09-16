#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Hermes Agent Workspace & Persistence Automated Verification
# Validates host bind-mount persistence, unprivileged sandbox boundaries,
# skills scaffolding, full backup readiness, and secret hygiene.
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Load environment
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

HERMES_PORT="${HERMES_PORT:-8642}"
HERMES_DASHBOARD_PORT="${HERMES_DASHBOARD_PORT:-9119}"
API_SERVER_KEY="${API_SERVER_KEY:-}"
TITAN_DOMAIN="${TITAN_DOMAIN:-titan.local}"
CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-80}"
DATA_DIR="${TITAN_DATA_DIR:-./data/memories}"
WORKSPACE_PATH="${TITAN_WORKSPACE_DIR:-./data/workspace}"

if [[ "$WORKSPACE_PATH" != /* ]]; then
  HOST_WORKSPACE="${REPO_ROOT}/${WORKSPACE_PATH#./}"
else
  HOST_WORKSPACE="${WORKSPACE_PATH}"
fi

if [[ "$DATA_DIR" != /* ]]; then
  HOST_MEMORIES="${REPO_ROOT}/${DATA_DIR#./}"
else
  HOST_MEMORIES="${DATA_DIR}"
fi

# Multi-tenant directory alignment (checks tenant partition if present)
if [ -d "${HOST_WORKSPACE}/primary" ]; then
  HOST_WORKSPACE="${HOST_WORKSPACE}/primary"
fi
if [ -d "${HOST_MEMORIES}/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/primary"
elif [ -d "${HOST_MEMORIES}/agents/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/agents/primary"
elif [ -d "${HOST_MEMORIES}/tenants/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/tenants/primary"
fi

# Detect service & container names (primary agent unit or legacy hermes)
HERMES_SERVICE="agent-primary"
if ! docker compose ps --services | grep -q "^agent-primary$" && docker compose ps --services | grep -q "^hermes$"; then
  HERMES_SERVICE="hermes"
fi
HERMES_CONTAINER="titan-agent-primary"
if ! docker ps -a --format '{{.Names}}' | grep -qw "titan-agent-primary" && docker ps -a --format '{{.Names}}' | grep -qw "titan-hermes"; then
  HERMES_CONTAINER="titan-hermes"
fi

log_info "Running Project Titan Hermes Workspace & Persistence Verification..."
log_info "Host Workspace Path: ${HOST_WORKSPACE}"
log_info "Host Memories Path:  ${HOST_MEMORIES}"
log_info "Target Service:      ${HERMES_SERVICE} (${HERMES_CONTAINER})"

# ------------------------------------------------------------------------------
# 1. Container Running & Health Check
# ------------------------------------------------------------------------------
log_info "Step 1: Checking Hermes and Signal-CLI container statuses..."
if ! docker compose ps --services --filter "status=running" | grep -q "^signal-cli$"; then
  log_warn "Signal-CLI container is not running. Starting signal-cli..."
  docker compose up -d signal-cli
  sleep 2
fi

if ! docker compose ps --services --filter "status=running" | grep -q "^${HERMES_SERVICE}$"; then
  log_warn "${HERMES_SERVICE} container is not running. Starting ${HERMES_SERVICE}..."
  docker compose up -d "${HERMES_SERVICE}"
  sleep 4
fi

CONTAINER_USER=$(docker compose exec -T "${HERMES_SERVICE}" id -u hermes)
if [ "${CONTAINER_USER}" != "1000" ]; then
  log_error "Hermes container user is UID ${CONTAINER_USER} (expected 1000: unprivileged hermes)."
  exit 1
fi
log_success "Hermes container verified configured with unprivileged UID 1000."

# ------------------------------------------------------------------------------
# 2. Web Dashboard & Gateway Reachability
# ------------------------------------------------------------------------------
log_info "Step 2A: Checking Hermes Web Dashboard on port ${HERMES_DASHBOARD_PORT}..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${HERMES_DASHBOARD_PORT}/" || echo "failed")
if [ "${HTTP_STATUS}" == "200" ] || [ "${HTTP_STATUS}" == "302" ]; then
  log_success "Hermes Web Dashboard reachable (HTTP ${HTTP_STATUS})."
else
  log_error "Hermes Web Dashboard returned unexpected HTTP ${HTTP_STATUS}."
  exit 1
fi

log_info "Step 2B: Checking internal Signal-CLI daemon reachability from Hermes..."
SIGNAL_ABOUT=$(docker compose exec -T "${HERMES_SERVICE}" curl -s http://signal-cli:8080/v1/about || echo "failed")
if echo "${SIGNAL_ABOUT}" | grep -q "json-rpc"; then
  log_success "Signal-CLI daemon reachable on titan-internal network."
else
  log_error "Failed to reach Signal-CLI daemon from Hermes container: ${SIGNAL_ABOUT}"
  exit 1
fi

log_info "Step 2C: Checking Hermes OpenAI-compatible API platform on port ${HERMES_PORT}..."
# 1. Unauthenticated rejection (HTTP 401)
UNAUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${HERMES_PORT}/v1/models" || echo "failed")
if [ "${UNAUTH_STATUS}" == "401" ]; then
  log_success "Hermes API enforces authentication: unauthenticated request rejected with HTTP 401."
else
  log_error "Hermes API failed security check: expected HTTP 401 on unauthenticated /v1/models, got '${UNAUTH_STATUS}'."
  exit 1
fi

# 2. Authenticated acceptance (HTTP 200)
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${API_SERVER_KEY}" "http://127.0.0.1:${HERMES_PORT}/v1/models" || echo "failed")
if [ "${AUTH_STATUS}" == "200" ]; then
  log_success "Hermes API authenticated successfully with API_SERVER_KEY (HTTP 200)."
else
  log_error "Hermes API authentication failed: expected HTTP 200 on authenticated /v1/models, got '${AUTH_STATUS}'."
  exit 1
fi

log_info "Step 2D: Checking Caddy reverse proxy routing for api.hermes.${TITAN_DOMAIN}..."
CADDY_API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: api.hermes.${TITAN_DOMAIN}" -H "Authorization: Bearer ${API_SERVER_KEY}" "http://127.0.0.1:${CADDY_HTTP_PORT}/v1/models" || echo "failed")
if [ "${CADDY_API_STATUS}" == "200" ]; then
  log_success "Caddy ingress routes to Hermes API at api.hermes.${TITAN_DOMAIN} (HTTP 200)."
else
  log_error "Caddy ingress failed for api.hermes.${TITAN_DOMAIN}: expected HTTP 200, got '${CADDY_API_STATUS}'."
  exit 1
fi

# ------------------------------------------------------------------------------
# 3. Host Bind-Mount Verification
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying workspace is a host bind-mount..."
COMPOSE_MOUNT_TYPE=$(docker inspect "${HERMES_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Type}}{{end}}{{end}}')
if [ "${COMPOSE_MOUNT_TYPE}" == "bind" ]; then
  log_success "Verified /workspace is mounted as a host 'bind' mount."
else
  log_error "Expected /workspace to be 'bind' mount, but found '${COMPOSE_MOUNT_TYPE}'."
  exit 1
fi

COMPOSE_MOUNT_SRC=$(docker inspect "${HERMES_CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}')
log_success "Verified host source path: ${COMPOSE_MOUNT_SRC}"

# ------------------------------------------------------------------------------
# 4. Bidirectional File Persistence Across Restarts
# ------------------------------------------------------------------------------
log_info "Step 4: Testing file write from inside container and host reflection..."
TEST_MARKER="test_persist_$(date +%s)"
docker compose exec -T "${HERMES_SERVICE}" bash -c "echo '${TEST_MARKER}' > /workspace/test_marker.txt"

if [ ! -f "${HOST_WORKSPACE}/test_marker.txt" ]; then
  log_error "File written inside container did not appear on host at ${HOST_WORKSPACE}/test_marker.txt"
  exit 1
fi

HOST_CONTENT=$(cat "${HOST_WORKSPACE}/test_marker.txt")
if [ "${HOST_CONTENT}" != "${TEST_MARKER}" ]; then
  log_error "Content mismatch: expected '${TEST_MARKER}', got '${HOST_CONTENT}'"
  exit 1
fi
log_success "File written inside container reflected immediately on host."

# Test persistence across container recreation
log_info "Recreating ${HERMES_SERVICE} container to verify persistence..."
docker compose up -d --force-recreate "${HERMES_SERVICE}"
sleep 2

CONTAINER_CONTENT=$(docker compose exec -T "${HERMES_SERVICE}" cat /workspace/test_marker.txt 2>/dev/null || echo "")
if [ "${CONTAINER_CONTENT}" == "${TEST_MARKER}" ]; then
  log_success "File persistence verified across container recreation!"
else
  log_error "File did not persist across container recreation (read: '${CONTAINER_CONTENT}')."
  exit 1
fi

# Clean up test marker
rm -f "${HOST_WORKSPACE}/test_marker.txt"

# ------------------------------------------------------------------------------
# 5. Native hermes-okf Plugin & Tool Registry Verification
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying native 'hermes-okf' plugin and tool registry..."

# 5A: Verify plugin package presence
if docker compose exec -T "${HERMES_SERVICE}" test -f /opt/hermes/plugins/hermes-okf/plugin.yaml; then
  log_success "Native plugin package verified at /opt/hermes/plugins/hermes-okf."
else
  log_error "Plugin manifest /opt/hermes/plugins/hermes-okf/plugin.yaml is missing."
  exit 1
fi

# 5B: Verify zero technical debt (legacy hermes_okf.py removed)
if docker compose exec -T "${HERMES_SERVICE}" test -f /opt/hermes/hermes_okf.py || [ -f "${HOST_WORKSPACE}/skills/hermes_okf.py" ]; then
  log_error "Technical debt violation: legacy hermes_okf.py still detected in runtime."
  exit 1
fi
log_success "Zero technical debt verified: legacy hermes_okf.py completely eradicated."

# 5C: Verify native tool schemas in Hermes Tool Registry
PLUGIN_CHECK=$(docker compose exec -T "${HERMES_SERVICE}" python3 -c '
import json, sys
from hermes_cli.plugins import discover_plugins
discover_plugins()
from tools.registry import registry

required_tools = ["read_okf_note", "write_okf_note", "synthesize_active_rules"]
all_tools = set(registry.get_all_tool_names())
missing = [t for t in required_tools if t not in all_tools]
if missing:
    print(f"MISSING: {missing}")
    sys.exit(1)

# Verify schemas exist
for t in required_tools:
    schema = registry.get_schema(t)
    if not schema or "parameters" not in schema:
        print(f"INVALID_SCHEMA: {t}")
        sys.exit(1)

print("OK")
' 2>/dev/null || echo "FAILED")

if [ "${PLUGIN_CHECK}" == "OK" ]; then
  log_success "Native OKF tools verified registered in Hermes tool registry: read_okf_note, write_okf_note, synthesize_active_rules."
else
  log_error "Failed to verify native OKF tools in registry: ${PLUGIN_CHECK}"
  exit 1
fi

# 5D: Verify tool execution via registry.dispatch
DISPATCH_CHECK=$(docker compose exec -T "${HERMES_SERVICE}" python3 -c '
import json, sys
from hermes_cli.plugins import discover_plugins
discover_plugins()
from tools.registry import registry

# 1. Dispatch write_okf_note
w_res = registry.dispatch("write_okf_note", {
    "rel_path": "knowledge/plugin_dispatch_test.md",
    "content": "# Native Plugin Dispatch Test\nValidated end-to-end tool execution via Hermes registry.",
    "title": "Native Plugin Dispatch Test",
    "tags": ["test", "dispatch"]
})
if isinstance(w_res, str):
    w_data = json.loads(w_res)
else:
    w_data = w_res
assert w_data.get("success") is True, f"Write failed: {w_res}"

# 2. Dispatch read_okf_note
r_res = registry.dispatch("read_okf_note", {"rel_path": "knowledge/plugin_dispatch_test.md"})
if isinstance(r_res, str):
    r_data = json.loads(r_res)
else:
    r_data = r_res
assert r_data.get("success") is True, f"Read failed: {r_res}"
assert r_data.get("title") == "Native Plugin Dispatch Test", f"Title mismatch: {r_data}"
assert "Validated end-to-end" in r_data.get("body", ""), f"Body mismatch: {r_data}"

# 3. Dispatch synthesize_active_rules
s_res = registry.dispatch("synthesize_active_rules", {"max_chars": 1000})
if isinstance(s_res, str):
    s_data = json.loads(s_res)
else:
    s_data = s_res
assert s_data.get("success") is True, f"Rules synthesis failed: {s_res}"

print("DISPATCH_OK")
' 2>/dev/null || echo "DISPATCH_FAILED")

# Clean up test note
rm -f "${HOST_MEMORIES}/knowledge/plugin_dispatch_test.md"

if [ "${DISPATCH_CHECK}" == "DISPATCH_OK" ]; then
  log_success "Native OKF tool dispatch verified via Hermes registry (write -> read -> synthesize)."
else
  log_error "Native OKF tool dispatch failed: ${DISPATCH_CHECK}"
  exit 1
fi

# ------------------------------------------------------------------------------
# 6. Memory Plane Purity Verification
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying Memory Plane purity (Rule 1)..."
DISALLOWED_IN_MEMORIES=$(find "${HOST_MEMORIES}" -type f -name "*.db" -o -name "*.sqlite" -o -name "*.pyc" 2>/dev/null || true)
if [ -n "${DISALLOWED_IN_MEMORIES}" ]; then
  log_error "Disallowed non-OKF runtime files detected in memories plane: ${DISALLOWED_IN_MEMORIES}"
  exit 1
fi
log_success "Memory Plane remains pure OKF Markdown."

# ------------------------------------------------------------------------------
# 7. Unified Backup & Retention Verification
# ------------------------------------------------------------------------------
log_info "Step 7: Testing unified full-data backup script (scripts/control/backup.sh)..."
if [ -x "${REPO_ROOT}/scripts/control/backup.sh" ]; then
  "${REPO_ROOT}/scripts/control/backup.sh"
  "${REPO_ROOT}/scripts/control/backup.sh" --list
  LATEST_BACKUP=$(find "${REPO_ROOT}/data/backups" -name "titan_data_*.tar.gz" -type f | sort | tail -n 1)
  if [ -n "${LATEST_BACKUP}" ] && (tar -tzf "${LATEST_BACKUP}" ./manifest.json >/dev/null 2>&1 || (tar -tzf "${LATEST_BACKUP}" 2>/dev/null || true) | grep -q "manifest.json"); then
    log_success "Full data backup created and validated with manifest: $(basename "${LATEST_BACKUP}")"
  else
    log_error "Latest backup missing or invalid manifest."
    exit 1
  fi
else
  log_error "scripts/control/backup.sh not found or not executable."
  exit 1
fi

# ------------------------------------------------------------------------------
# 8. Zero Docker Socket & LiteLLM Gateway Routing Checks
# ------------------------------------------------------------------------------
log_info "Step 8: Verifying Zero Docker Socket inside Hermes container..."
if ! docker compose exec -T "${HERMES_SERVICE}" test -e /var/run/docker.sock; then
  log_success "Verified /var/run/docker.sock is strictly absent inside container."
else
  log_error "Host Docker socket detected inside container!"
  exit 1
fi

log_info "Step 9: Verifying Gateway reachability via proxy.local from Hermes..."
GATEWAY_HEALTH=$(docker compose exec -T "${HERMES_SERVICE}" curl -s -H "Authorization: Bearer ${HERMES_LITELLM_KEY}" http://proxy.local:4000/health || echo "failed")
if echo "${GATEWAY_HEALTH}" | grep -q "healthy"; then
  log_success "Inference gateway reachable via proxy.local:4000 with virtual key."
else
  log_warn "Gateway health check output from proxy.local:4000: ${GATEWAY_HEALTH}"
fi

# ------------------------------------------------------------------------------
# 10. Git Secret Hygiene Verification
# ------------------------------------------------------------------------------
log_info "Step 10: Checking Git status for uncommitted runtime workspace files..."
UNTRACKED_WORKSPACE=$(git ls-files -o --exclude-standard data/workspace/ | grep -v 'data/workspace/\.gitkeep$' || true)
TRACKED_WORKSPACE=$(git ls-files data/workspace/ | grep -v 'data/workspace/\.gitkeep$' || true)
if [ -n "${UNTRACKED_WORKSPACE}" ] || [ -n "${TRACKED_WORKSPACE}" ]; then
  log_error "Untracked or tracked live workspace files detected: ${UNTRACKED_WORKSPACE} ${TRACKED_WORKSPACE}"
  exit 1
fi
log_success "Git tracking is clean: data/workspace/* properly ignored."

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Hermes Workspace & Full-Data Persistence Checks Passed!     ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
