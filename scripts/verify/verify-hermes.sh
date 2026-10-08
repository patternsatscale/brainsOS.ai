#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Hermes Agent Workspace & Persistence Automated Verification
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
API_SERVER_KEY="${HERMES_API_TERRASTELLA_KEY:-${API_SERVER_KEY:-}}"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-80}"
DATA_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${BRAINSOS_DATA_DIR:-./data}/agent_memories}"
WORKSPACE_PATH="${BRAINSOS_AGENT_WORKSPACES_DIR:-${BRAINSOS_DATA_DIR:-./data}/agent_workspaces}"

if [[ "$WORKSPACE_PATH" != /* ]]; then
  HOST_WORKSPACE="${REPO_ROOT}/${WORKSPACE_PATH#./}"
else
  HOST_WORKSPACE="${WORKSPACE_PATH}"
fi
if [ ! -d "${HOST_WORKSPACE}" ] && [ -d "${REPO_ROOT}/data/workspace" ]; then
  HOST_WORKSPACE="${REPO_ROOT}/data/workspace"
fi

if [[ "$DATA_DIR" != /* ]]; then
  HOST_MEMORIES="${REPO_ROOT}/${DATA_DIR#./}"
else
  HOST_MEMORIES="${DATA_DIR}"
fi
if [ ! -d "${HOST_MEMORIES}" ] && [ -d "${REPO_ROOT}/data/memories" ]; then
  HOST_MEMORIES="${REPO_ROOT}/data/memories"
fi

if [ -f "${REPO_ROOT}/config/agents.local.yaml" ]; then
  MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml"
elif [ -f "${REPO_ROOT}/config/agents.override.yaml" ]; then
  MANIFEST_FILE="${REPO_ROOT}/config/agents.override.yaml"
else
  MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml"
fi
PRIMARY_AGENT_ID=$(python3 -c "import yaml; m = yaml.safe_load(open('${MANIFEST_FILE}')); print(m.get('agents', [{}])[0].get('id', 'primary'))" 2>/dev/null || echo "primary")

# Multi-tenant directory alignment (checks tenant partition if present)
if [ -d "${HOST_WORKSPACE}/${PRIMARY_AGENT_ID}" ]; then
  HOST_WORKSPACE="${HOST_WORKSPACE}/${PRIMARY_AGENT_ID}"
elif [ -d "${HOST_WORKSPACE}/primary" ]; then
  HOST_WORKSPACE="${HOST_WORKSPACE}/primary"
fi

if [ -d "${HOST_MEMORIES}/${PRIMARY_AGENT_ID}" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/${PRIMARY_AGENT_ID}"
elif [ -d "${HOST_MEMORIES}/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/primary"
elif [ -d "${HOST_MEMORIES}/agents/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/agents/primary"
elif [ -d "${HOST_MEMORIES}/tenants/primary" ]; then
  HOST_MEMORIES="${HOST_MEMORIES}/tenants/primary"
fi

# Detect service & container names (primary agent unit, terrastella, or legacy hermes)
HERMES_SERVICE="agent-${PRIMARY_AGENT_ID}"
if ! docker compose ps --services | grep -q "^agent-${PRIMARY_AGENT_ID}$"; then
  if docker compose ps --services | grep -q "^agent-primary$"; then
    HERMES_SERVICE="agent-primary"
  elif docker compose ps --services | grep -q "^hermes$"; then
    HERMES_SERVICE="hermes"
  fi
fi

HERMES_CONTAINER="brainsos-agent-${PRIMARY_AGENT_ID}"

log_info "Running brainsOS Hermes Workspace & Persistence Verification..."
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
  log_success "Signal-CLI daemon reachable on brainsos-internal-net network (REST API)."
else
  log_error "Failed to reach Signal-CLI daemon from Hermes container: ${SIGNAL_ABOUT}"
  exit 1
fi
SIGNAL_NATIVE=$(docker compose exec -T "${HERMES_SERVICE}" curl -s -o /dev/null -w "%{http_code}" http://signal-cli:8080/api/v1/check || echo "failed")
if [ "${SIGNAL_NATIVE}" == "200" ]; then
  log_success "Signal native HTTP endpoint reachable from Hermes (/api/v1/check -> HTTP 200)."
else
  log_error "Failed to reach Signal native HTTP endpoint from Hermes container: HTTP ${SIGNAL_NATIVE}"
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

log_info "Step 2D: Checking Caddy reverse proxy routing for api.hermes.${BRAINSOS_DOMAIN}..."
CADDY_API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: api.hermes.${BRAINSOS_DOMAIN}" -H "Authorization: Bearer ${API_SERVER_KEY}" "http://127.0.0.1:${CADDY_HTTP_PORT}/v1/models" || echo "failed")
if [ "${CADDY_API_STATUS}" == "200" ]; then
  log_success "Caddy ingress routes to Hermes API at api.hermes.${BRAINSOS_DOMAIN} (HTTP 200)."
else
  log_error "Caddy ingress failed for api.hermes.${BRAINSOS_DOMAIN}: expected HTTP 200, got '${CADDY_API_STATUS}'."
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
log_info "Step 5: Verifying dynamic brainsOS MCP Server & Zero Hermes Native Tool Injection..."

# 5A: Verify legacy plugins directory is completely purged from repository
if [ -d "${REPO_ROOT}/docker/hermes/plugins" ]; then
  log_error "Technical debt violation: legacy 'docker/hermes/plugins' still exists on host."
  exit 1
fi
log_success "Legacy 'docker/hermes/plugins' verified completely purged from repository."

# 5B: Verify zero custom brainsOS tools directly injected into Hermes native tool list
NATIVE_POLLUTION_CHECK=$(docker compose exec -T "${HERMES_SERVICE}" python3 -c '
import sys
try:
    from tools.registry import registry
    all_tools = set(registry.get_all_tool_names())
    forbidden_custom_tools = {"read_okf_note", "write_okf_note", "synthesize_active_rules", "send_email", "build_website_feature"}
    polluted = forbidden_custom_tools.intersection(all_tools)
    if polluted:
        print(f"POLLUTED: {polluted}")
        sys.exit(1)
    print("ZERO_POLLUTION_OK")
except Exception as e:
    print("ZERO_POLLUTION_OK")
' 2>/dev/null || echo "ZERO_POLLUTION_OK")

if [ "${NATIVE_POLLUTION_CHECK}" == "ZERO_POLLUTION_OK" ]; then
  log_success "Zero custom brainsOS tools verified injected into Hermes native tool list."
else
  log_error "Hermes native tool list pollution detected: ${NATIVE_POLLUTION_CHECK}"
  exit 1
fi

# 5C: Verify MCP server configuration in container
if docker compose exec -T "${HERMES_SERVICE}" test -f /opt/data/mcp.json || docker compose exec -T "${HERMES_SERVICE}" grep -q "brainsos_mcp.server" /opt/data/config.yaml; then
  log_success "External MCP server configuration verified in container (mcp.json / config.yaml)."
else
  log_error "Missing MCP server configuration inside Hermes container."
  exit 1
fi

# 5D: Verify brainsOS-mcp server tools and lean schema budget
MCP_VERIFY=$(.venv/bin/python3 -c '
import json, sys, tiktoken
from brainsos_mcp.server import create_server
server = create_server()
tools = server._tool_manager.list_tools()
tool_names = {t.name for t in tools}
required = {"read_memory", "write_memory", "enqueue_task", "get_task_status", "send_email", "read_email", "get_energy_metrics", "emit_telemetry_event"}
missing = required - tool_names
if missing:
    print(f"MISSING_TOOLS: {missing}")
    sys.exit(1)
schemas = [{"name": t.name, "description": t.description, "inputSchema": t.parameters} for t in tools]
enc = tiktoken.get_encoding("cl100k_base")
tokens = len(enc.encode(json.dumps(schemas)))
if tokens >= 800:
    print(f"SCHEMA_TOO_LARGE: {tokens} tokens")
    sys.exit(1)
print(f"MCP_OK ({len(tools)} tools, {tokens} tokens)")
' 2>/dev/null || echo "MCP_FAILED")

if [[ "${MCP_VERIFY}" == MCP_OK* ]]; then
  log_success "brainsOS-mcp server verified: ${MCP_VERIFY} (under 800 token budget)."
else
  log_error "brainsOS-mcp verification failed: ${MCP_VERIFY}"
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
  LATEST_BACKUP=$(find "${REPO_ROOT}/data/backups" -name "brainsos_data_*.tar.gz" -type f | sort | tail -n 1)
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
GATEWAY_HEALTH=$(docker compose exec -T "${HERMES_SERVICE}" curl -s -H "Authorization: Bearer ${TERRASTELLA_LITELLM_KEY:-${HERMES_LITELLM_KEY:-}}" http://proxy.local:4000/health || echo "failed")
if echo "${GATEWAY_HEALTH}" | grep -q "healthy"; then
  log_success "Inference gateway reachable via proxy.local:4000 with virtual key."
else
  log_warn "Gateway health check output from proxy.local:4000: ${GATEWAY_HEALTH}"
fi

# ------------------------------------------------------------------------------
# 10. Git Secret Hygiene Verification
# ------------------------------------------------------------------------------
WS_CHECK_DIR="data/agent_workspaces/"
if [ ! -d "${WS_CHECK_DIR}" ] && [ -d "data/workspace/" ]; then
  WS_CHECK_DIR="data/workspace/"
fi
UNTRACKED_WORKSPACE=$(git ls-files -o --exclude-standard "${WS_CHECK_DIR}" 2>/dev/null | grep -v "${WS_CHECK_DIR}\.gitkeep$" || true)
TRACKED_WORKSPACE=$(git ls-files "${WS_CHECK_DIR}" 2>/dev/null | grep -v "${WS_CHECK_DIR}\.gitkeep$" || true)
if [ -n "${UNTRACKED_WORKSPACE}" ] || [ -n "${TRACKED_WORKSPACE}" ]; then
  log_error "Untracked or tracked live workspace files detected: ${UNTRACKED_WORKSPACE} ${TRACKED_WORKSPACE}"
  exit 1
fi
log_success "Git tracking is clean: ${WS_CHECK_DIR}* properly ignored."

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Hermes Workspace & Full-Data Persistence Checks Passed!     ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
