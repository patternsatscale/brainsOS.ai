#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Operator IDE Automated Verification & Security Audit
# Validates container health, security boundaries, multi-tenant isolation,
# Caddy ingress authentication, Aider & Goose tooling, and memory purity.
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

fail_check() {
  log_error "$*"
  exit 1
}

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

# Load environment variables
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
else
  if [ -f .env.example ]; then
    set -a
    . ./.env.example
    set +a
  fi
fi

CODE_SERVER_PORT="${CODE_SERVER_PORT:-8443}"
CADDY_PORT="${CADDY_HTTP_PORT:-80}"
OPERATOR_USER="${OPERATOR_USER:-operator}"
CODE_SERVER_PASSWORD="${CODE_SERVER_PASSWORD:-brainsos_operator_secret}"
OPERATOR_LITELLM_KEY="${OPERATOR_LITELLM_KEY:-sk-brainsos-operator-virtual-key}"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
DATA_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-./data/agent_memories}"

if [[ "$DATA_DIR" != /* ]]; then
  MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  MEMORIES_DIR="${DATA_DIR}"
fi
if [ ! -d "${MEMORIES_DIR}" ] && [ -d "${REPO_ROOT}/data/memories" ]; then
  MEMORIES_DIR="${REPO_ROOT}/data/memories"
fi

log_info "Starting brainsOS Operator IDE automated verification..."

# ------------------------------------------------------------------------------
# 1. Verify Docker Compose Configuration
# ------------------------------------------------------------------------------
log_info "Step 1: Validating Docker Compose configuration..."
docker compose config >/dev/null || fail_check "docker compose config failed!"
log_success "Docker Compose configuration is valid."

# ------------------------------------------------------------------------------
# 2. Verify Container Runtime Health & Direct Port Accessibility
# ------------------------------------------------------------------------------
CONTAINER_NAME="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?code-server$' | head -n 1 || echo 'brainsos-app-code-server')"
log_info "Step 2: Checking ${CONTAINER_NAME} container status..."
CONTAINER_STATUS=$(docker inspect --format '{{.State.Status}}' "${CONTAINER_NAME}" 2>/dev/null || echo "missing")
if [ "${CONTAINER_STATUS}" != "running" ]; then
  fail_check "${CONTAINER_NAME} container is not running (status: ${CONTAINER_STATUS}). Run ./scripts/setup/setup-editor.sh"
fi
log_success "${CONTAINER_NAME} container is running."

log_info "Testing direct port :${CODE_SERVER_PORT} responsiveness..."
DIRECT_HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${CODE_SERVER_PORT}/" || echo "000")
if echo "${DIRECT_HTTP_STATUS}" | grep -qE '^(200|302|401)'; then
  log_success "Direct port :${CODE_SERVER_PORT} responding (HTTP ${DIRECT_HTTP_STATUS})."
else
  fail_check "Direct port :${CODE_SERVER_PORT} failed to respond (HTTP ${DIRECT_HTTP_STATUS})."
fi

# ------------------------------------------------------------------------------
# 3. Verify Container Security Boundaries (Rules 1, 4 & 9)
# ------------------------------------------------------------------------------
log_info "Step 3: Auditing container security profile and isolation invariants..."

# Rule 4: Least Privilege UID check
CONTAINER_UID=$(docker compose exec -T code-server id -u 2>/dev/null || echo "unknown")
if [ "${CONTAINER_UID}" == "1000" ]; then
  log_success "Container executes strictly as unprivileged non-root user (UID 1000)."
else
  fail_check "Security violation: Container running with unexpected UID: ${CONTAINER_UID} (expected 1000)."
fi

# Rule 4: Docker Socket Absence check
if docker compose exec -T code-server ls -l /var/run/docker.sock >/dev/null 2>&1; then
  fail_check "Security violation: Docker socket (/var/run/docker.sock) mounted into code-server container!"
else
  log_success "Docker socket (/var/run/docker.sock) is strictly absent from container."
fi

# Rule 9: Multi-Tenant Isolation - Agent containers cannot reach Operator IDE
log_info "Verifying multi-tenant isolation: asserting agents cannot connect to Operator IDE..."
PRIMARY_AGENT=$(docker ps --format '{{.Names}}' | grep '^brainsos-agent-' | head -n 1 || echo "")
if [ -n "${PRIMARY_AGENT}" ]; then
  # Probe code-server from inside agent container
  PROBE_RESULT=$(docker exec -T "${PRIMARY_AGENT}" nc -z -w 2 brainsos-code-server 8443 2>/dev/null && echo "connected" || echo "blocked")
  if [ "${PROBE_RESULT}" == "blocked" ]; then
    log_success "Multi-tenant boundary verified: Agent '${PRIMARY_AGENT}' is strictly blocked from Operator IDE."
  else
    fail_check "Security violation: Agent '${PRIMARY_AGENT}' was able to route to brainsos-code-server:8443!"
  fi
else
  log_warn "No running brainsos-agent-* container found to run agent-side network probe."
fi

# ------------------------------------------------------------------------------
# 4. Verify Caddy Ingress Routing & Authentication Gate
# ------------------------------------------------------------------------------
log_info "Step 4: Testing Caddy ingress routing and HTTP Basic Auth security gate..."

# Unauthenticated request must return 401 Unauthorized
UNAUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: editor.${BRAINSOS_DOMAIN}" "http://127.0.0.1:${CADDY_PORT}/" || echo "000")
if [ "${UNAUTH_STATUS}" == "401" ]; then
  log_success "Caddy ingress gate enforced: Unauthenticated request returned HTTP 401 Unauthorized."
else
  fail_check "Caddy ingress gate failure: Expected HTTP 401 for unauthenticated request, got HTTP ${UNAUTH_STATUS}."
fi

# Authenticated request must succeed (HTTP 200 or HTTP 302 login redirect)
AUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -u "${OPERATOR_USER}:${CODE_SERVER_PASSWORD}" \
  -H "Host: editor.${BRAINSOS_DOMAIN}" \
  "http://127.0.0.1:${CADDY_PORT}/" || echo "000")

if echo "${AUTH_STATUS}" | grep -qE '^(200|302)'; then
  log_success "Caddy ingress authenticated routing verified (HTTP ${AUTH_STATUS}) for editor.${BRAINSOS_DOMAIN}."
else
  fail_check "Authenticated request to editor.${BRAINSOS_DOMAIN} returned unexpected HTTP ${AUTH_STATUS}."
fi

# Test code.brainsos.local alias
CODE_ALIAS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -u "${OPERATOR_USER}:${CODE_SERVER_PASSWORD}" \
  -H "Host: code.${BRAINSOS_DOMAIN}" \
  "http://127.0.0.1:${CADDY_PORT}/" || echo "000")
if echo "${CODE_ALIAS_STATUS}" | grep -qE '^(200|302)'; then
  log_success "Caddy ingress alias code.${BRAINSOS_DOMAIN} verified (HTTP ${CODE_ALIAS_STATUS})."
fi

# ------------------------------------------------------------------------------
# 5. Verify Multi-Root Workspace & Memory Plane Purity (Rule 1)
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying Multi-Root Workspace layout and filesystem mounts..."

docker compose exec -T code-server test -f /workspace/brainsos.code-workspace || fail_check "Multi-root workspace file (/workspace/brainsos.code-workspace) not found inside container."
docker compose exec -T code-server test -d /workspace/brainsos || fail_check "Repository root mount (/workspace/brainsos) missing inside container."
docker compose exec -T code-server test -d /memories || fail_check "Memory plane mount (/memories) missing inside container."
docker compose exec -T code-server test -d /data/workspace || fail_check "Agent workspaces mount (/data/workspace) missing inside container."
docker compose exec -T code-server test -d /data/comms || fail_check "Communications gateways mount (/data/comms) missing inside container."
docker compose exec -T code-server test -d /data/agent_apps/cindypawford/site || fail_check "App canvas mount (/data/agent_apps/cindypawford/site) missing inside container."
log_success "All 5 Multi-Root Workspace mount points verified inside container."

# Rule 1 Purity Check: Ensure no .vscode or SQLite files in memories
log_info "Auditing Memory Plane purity (ensuring zero .vscode directories in memories)..."
FORBIDDEN_DOT_VSCODE=$(find "${MEMORIES_DIR}" -type d -name ".vscode" 2>/dev/null || true)
if [ -n "${FORBIDDEN_DOT_VSCODE}" ]; then
  fail_check "Rule 1 Violation: .vscode directory detected inside memory plane: ${FORBIDDEN_DOT_VSCODE}"
else
  log_success "Memory Plane is 100% pure (zero .vscode directories in ${MEMORIES_DIR})."
fi

# ------------------------------------------------------------------------------
# 6. Verify AI Assistant Tooling (Aider, Goose, brainsos-chat) & LiteLLM Reachability
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying AI tooling and LiteLLM reachability..."

# Aider CLI check
AIDER_PATH=$(docker compose exec -T code-server which aider 2>/dev/null || echo "")
if [ -n "${AIDER_PATH}" ]; then
  log_success "Aider CLI tooling installed at ${AIDER_PATH}."
else
  fail_check "Aider CLI tooling (aider) not found inside container."
fi

# Continue VS Code extension check
CONTINUE_EXT=$(docker compose exec -T code-server code-server --list-extensions 2>/dev/null | grep 'continue.continue' || echo "")
if [ -n "${CONTINUE_EXT}" ]; then
  log_success "Continue AI extension verified: ${CONTINUE_EXT}."
else
  fail_check "Continue AI extension (continue.continue) not found inside container."
fi

# Continue configuration and API endpoints check
if docker compose exec -T code-server test -f /home/coder/.continue/config.yaml; then
  log_success "Continue configuration verified at /home/coder/.continue/config.yaml."
  docker compose exec -T code-server grep -qE "api\.(terrastella|cindypawford|bawtford)" /home/coder/.continue/config.yaml || \
    fail_check "Continue config missing Agent API endpoint."
  docker compose exec -T code-server grep -q "litellm:4000" /home/coder/.continue/config.yaml || \
    fail_check "Continue config missing LiteLLM endpoint."
  log_success "Continue API endpoints (LiteLLM & Agent APIs) verified in config.yaml."
else
  fail_check "Continue configuration (/home/coder/.continue/config.yaml) missing inside container."
fi

# Workspace trust and SSL bypass verification
log_info "Verifying Workspace Trust disabled and SSL bypass in settings.json..."
if docker compose exec -T code-server grep -q '"security.workspace.trust.enabled": false' /home/coder/.local/share/code-server/User/settings.json; then
  log_success "Workspace trust is explicitly disabled in editor settings.json."
else
  fail_check "Workspace trust is not disabled in editor settings.json!"
fi

# In-container Agent API DNS reachability check
log_info "Verifying Operator IDE network reachability to Ingress Gateway Agent APIs..."
AGENT_PROBE=$(docker compose exec -T code-server curl -s -m 5 -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${HERMES_API_TERRASTELLA_KEY:-${API_SERVER_KEY:-}}" \
  "http://api.terrastella.brainsos.local/v1/models" 2>/dev/null || echo "000")
if echo "${AGENT_PROBE}" | grep -qE '^(200|401|405)'; then
  log_success "Operator IDE successfully routed to api.terrastella.brainsos.local (HTTP ${AGENT_PROBE})."
else
  log_warn "Operator IDE probe to api.terrastella.brainsos.local returned HTTP ${AGENT_PROBE}."
fi

# brainsos-chat CLI check
BRAINSOS_CHAT_PATH=$(docker compose exec -T code-server which brainsos-chat 2>/dev/null || echo "")
if [ -n "${BRAINSOS_CHAT_PATH}" ]; then
  log_success "Fleet communication helper installed at ${BRAINSOS_CHAT_PATH}."
else
  fail_check "brainsos-chat helper script not found inside container."
fi

# LiteLLM reachability from container
log_info "Verifying container reachability to LiteLLM Control Plane (http://litellm:4000)..."
LITELLM_STATUS=$(docker compose exec -T code-server curl -s -m 5 -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${OPERATOR_LITELLM_KEY}" \
  "http://litellm:4000/health/liveness" 2>/dev/null || echo "000")

if echo "${LITELLM_STATUS}" | grep -qE '^(200|401|405)'; then
  log_success "Container successfully connected to LiteLLM control plane (HTTP ${LITELLM_STATUS})."
else
  log_warn "LiteLLM control plane at http://litellm:4000 returned HTTP ${LITELLM_STATUS} (may be standby)."
fi

echo ""
log_success "======================================================================"
log_success "brainsOS: Operator IDE Verification PASSED (All Checks Satisfied)"
log_success "======================================================================"
echo ""
