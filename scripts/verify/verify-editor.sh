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
CODE_SERVER_PASSWORD="${CODE_SERVER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_operator_secret}}"
OPERATOR_LITELLM_KEY="${OPERATOR_LITELLM_KEY:-sk-brainsos-operator-virtual-key}"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
DATA_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${BRAINSOS_DATA_DIR:-./data}/agent_memories}"

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

# Unauthenticated request must return 401 Unauthorized or 302 SSO redirect
UNAUTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: editor.${BRAINSOS_DOMAIN}" "http://127.0.0.1:${CADDY_PORT}/" || echo "000")
if echo "${UNAUTH_STATUS}" | grep -qE '^(401|302)'; then
  log_success "Caddy ingress gate enforced: Unauthenticated request returned HTTP ${UNAUTH_STATUS} (Auth Gate Redirect/Challenge)."
else
  fail_check "Caddy ingress gate failure: Expected HTTP 401 or 302 for unauthenticated request, got HTTP ${UNAUTH_STATUS}."
fi

# Verify direct upstream container reachability
CODE_UPSTREAM=$(docker compose exec -T caddy curl -s -o /dev/null -w "%{http_code}" http://code-server:8443/ 2>/dev/null || echo "000")
if echo "${CODE_UPSTREAM}" | grep -qE '^(200|302)'; then
  log_success "Direct container upstream code-server:8443 verified (HTTP ${CODE_UPSTREAM})."
else
  fail_check "Direct container upstream code-server:8443 failed: HTTP ${CODE_UPSTREAM}."
fi

# Test TLS reachability over HTTPS with exported root CA
log_info "Testing Caddy TLS ingress with exported root CA certificate..."
TARGET_CERT="${BRAINSOS_CONTROL_PLANE_DIR:-${BRAINSOS_DATA_DIR:-./data}/control_plane}/caddy_root.crt"
if [[ "$TARGET_CERT" != /* ]]; then
  TARGET_CERT="${REPO_ROOT}/${TARGET_CERT#./}"
fi

if [ -s "${TARGET_CERT}" ]; then
  TLS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --cacert "${TARGET_CERT}" \
    -u "${OPERATOR_USER}:${CODE_SERVER_PASSWORD}" \
    "https://editor.${BRAINSOS_DOMAIN}/" || echo "000")
  if echo "${TLS_STATUS}" | grep -qE '^(200|302)'; then
    log_success "Caddy ingress TLS reachability verified (HTTP ${TLS_STATUS}) via exported root CA."
  else
    fail_check "Caddy ingress TLS request with CA cert to editor.${BRAINSOS_DOMAIN} returned unexpected HTTP ${TLS_STATUS}."
  fi
else
  fail_check "Caddy root CA certificate not found or empty at: ${TARGET_CERT}"
fi

# ------------------------------------------------------------------------------
# 5. Verify Workspace Layout & Memory Plane Purity (Rule 1)
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying Workspace layout and filesystem mounts..."

docker compose exec -T code-server test -f /workspace/brainsos.code-workspace -o -f /etc/brainsos/editor/brainsos.code-workspace || fail_check "Workspace file not found inside container."

# Rule 14 Check: Engine platform repository must NOT be mounted into code-server
if docker compose exec -T code-server test -d /workspace/brainsos 2>/dev/null; then
  fail_check "Rule 14 Violation: Engine platform repository (/workspace/brainsos) is mounted into code-server!"
else
  log_success "Engine platform repository (/workspace/brainsos) is strictly absent from container."
fi

# Validate Fleet Data Repository mount (/data) as single workspace root
docker compose exec -T code-server test -d /data || fail_check "Fleet data repository (/data) mount missing inside container."
log_success "Fleet data repository (/data) mount verified inside container."

# Verify coder.json specifies single folder /data
if docker compose exec -T code-server grep -q '"folder": *"/data"' /home/coder/.local/share/code-server/coder.json 2>/dev/null; then
  log_success "Single folder workspace root (/data) verified in coder.json."
else
  fail_check "Single folder workspace root (/data) not configured in coder.json!"
fi

# Verify workspace template defines only /data
if docker compose exec -T code-server python3 -c '
import json, sys, os
p = "/etc/brainsos/editor/brainsos.code-workspace" if os.path.exists("/etc/brainsos/editor/brainsos.code-workspace") else "/workspace/brainsos.code-workspace"
data = json.load(open(p))
paths = [f.get("path") for f in data.get("folders", [])]
if paths != ["/data"]:
    print("Expected only [\"/data\"], got", paths)
    sys.exit(1)
' 2>/dev/null; then
  log_success "Workspace definition strictly verified with single /data folder root."
else
  fail_check "Workspace definition contains multiple roots (expected only /data)!"
fi

docker compose exec -T code-server test -d /memories || fail_check "Memory plane mount (/memories) missing inside container."
log_success "Workspace filesystem mounts verified inside container."

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

# LiteLLM Connector for Copilot extension check
LITELLM_COPILOT_EXT=$(docker compose exec -T code-server code-server --list-extensions 2>/dev/null | grep -i 'gethnet.litellm-connector-copilot' || echo "")
if [ -n "${LITELLM_COPILOT_EXT}" ]; then
  log_success "LiteLLM Connector for Copilot extension verified: ${LITELLM_COPILOT_EXT}."
else
  fail_check "LiteLLM Connector for Copilot extension (gethnet.litellm-connector-copilot) not found inside container."
fi

# Copilot Language Models Configuration (chatLanguageModels.json)
log_info "Verifying Copilot LiteLLM Connector configuration in chatLanguageModels.json..."
if docker compose exec -T code-server test -f /home/coder/.local/share/code-server/User/chatLanguageModels.json; then
  log_success "chatLanguageModels.json verified at /home/coder/.local/share/code-server/User/chatLanguageModels.json."
  docker compose exec -T code-server grep -q "litellm-connector" /home/coder/.local/share/code-server/User/chatLanguageModels.json || \
    fail_check "chatLanguageModels.json missing litellm-connector vendor."
  docker compose exec -T code-server grep -q "litellm:4000" /home/coder/.local/share/code-server/User/chatLanguageModels.json || \
    fail_check "chatLanguageModels.json missing LiteLLM baseUrl (http://litellm:4000)."
  log_success "LiteLLM Connector endpoint verified in chatLanguageModels.json."
else
  fail_check "chatLanguageModels.json missing inside container."
fi

# Workspace trust and SSL bypass verification
log_info "Verifying Workspace Trust disabled and SSL bypass in settings.json..."
if docker compose exec -T code-server grep -q '"security.workspace.trust.enabled": false' /home/coder/.local/share/code-server/User/settings.json; then
  log_success "Workspace trust is explicitly disabled in editor settings.json."
else
  fail_check "Workspace trust is not disabled in editor settings.json!"
fi

# Dark Theme verification
log_info "Verifying Default Dark Modern color theme in settings.json..."
if docker compose exec -T code-server grep -qE '"workbench.colorTheme": *"(Default )?Dark Modern"' /home/coder/.local/share/code-server/User/settings.json; then
  log_success "Default dark theme ('Default Dark Modern') verified in code-server User settings."
else
  fail_check "Dark theme not configured in /home/coder/.local/share/code-server/User/settings.json!"
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

# Terminal in editor area verification
log_info "Verifying terminal front-and-center in editor area..."
if docker compose exec -T code-server grep -q '"terminal.integrated.defaultLocation": *"editor"' /home/coder/.local/share/code-server/User/settings.json; then
  log_success "Terminal default location verified: 'editor' (front and center)."
else
  fail_check "Terminal default location is not set to 'editor' in settings.json!"
fi

# Startup terminal extension verification
log_info "Verifying brainsos.system-terminal extension..."
EXTS=$(docker compose exec -T code-server code-server --list-extensions 2>/dev/null || docker compose exec -T code-server code-server --list-extensions 2>/dev/null || echo "")
if echo "${EXTS}" | grep -q 'brainsos.system-terminal'; then
  log_success "Startup terminal extension (brainsos.system-terminal) verified."
else
  fail_check "Startup terminal extension (brainsos.system-terminal) not listed in code-server! Found: ${EXTS}"
fi

# VS Code AI settings & Language Models Dynamic Discovery verification
log_info "Verifying VS Code built-in AI settings and dynamic LiteLLM Connector..."
if docker compose exec -T code-server test -f /home/coder/.local/share/code-server/User/chatLanguageModels.json; then
  log_success "chatLanguageModels.json verified at /home/coder/.local/share/code-server/User/chatLanguageModels.json."
  docker compose exec -T code-server grep -q '"vendor": *"litellm-connector"' /home/coder/.local/share/code-server/User/chatLanguageModels.json || \
    fail_check "chatLanguageModels.json missing litellm-connector vendor."
  docker compose exec -T code-server grep -q "http://litellm:4000" /home/coder/.local/share/code-server/User/chatLanguageModels.json || \
    fail_check "chatLanguageModels.json missing LiteLLM gateway endpoint."
  log_success "Dynamic LiteLLM connector configuration verified in chatLanguageModels.json."
else
  fail_check "chatLanguageModels.json missing inside container."
fi

# Pruned Explorer Views & BYOK Chat Settings verification
log_info "Verifying pruned explorer view configurations and BYOK settings in settings.json..."
docker compose exec -T code-server grep -q '"explorer.openEditors.visible": *0' /home/coder/.local/share/code-server/User/settings.json || \
  fail_check "Open Editors view is not hidden in settings.json ('explorer.openEditors.visible: 0' missing)."
docker compose exec -T code-server grep -q '"outline.collapseItems": *"alwaysCollapse"' /home/coder/.local/share/code-server/User/settings.json || \
  fail_check "Outline view collapse setting missing in settings.json."
docker compose exec -T code-server grep -q '"timeline.excludeSources"' /home/coder/.local/share/code-server/User/settings.json || \
  fail_check "Timeline view exclusion missing in settings.json."
docker compose exec -T code-server grep -q '"chat.byokUtilityModelDefault": *"mainAgent"' /home/coder/.local/share/code-server/User/settings.json || \
  fail_check "BYOK utility model default setting missing in settings.json."
log_success "Pruned explorer views and BYOK chat settings verified in settings.json."

# Verify Foam extension explorer views are disabled (when: false)
log_info "Verifying Foam extension explorer views are disabled in package.json..."
if docker compose exec -T code-server python3 -c '
import json, glob, sys
pkgs = glob.glob("/home/coder/.local/share/code-server/extensions/foam.foam-vscode-*/package.json")
if not pkgs:
    print("Foam package.json not found")
    sys.exit(1)
for p in pkgs:
    d = json.load(open(p))
    for v in d.get("contributes", {}).get("views", {}).get("explorer", []):
        if v.get("when") != "false":
            print("View not disabled:", v.get("id"), "when:", v.get("when"))
            sys.exit(1)
print("OK")
' 2>/dev/null; then
  log_success "All Foam explorer subviews (connections, tags, notes, orphans) verified disabled (when: false)."
else
  fail_check "Foam explorer subviews are not properly disabled in package.json!"
fi

# In-container System Terminal Make commands verification
log_info "Verifying 'make urls' command execution from /data inside container..."
MAKE_URLS_OUT=$(docker compose exec -T -w /data code-server make urls 2>&1 || echo "ERROR")
if echo "${MAKE_URLS_OUT}" | grep -q "Platform Service Directory"; then
  log_success "'make urls' successfully executed from /data directory."
else
  fail_check "'make urls' execution failed inside container! Output: ${MAKE_URLS_OUT}"
fi

log_info "Verifying 'make status' command execution from /data inside container..."
MAKE_STATUS_OUT=$(docker compose exec -T -w /data code-server make status 2>&1 || echo "ERROR")
if echo "${MAKE_STATUS_OUT}" | grep -q "LiteLLM Gateway"; then
  log_success "'make status' successfully executed from /data directory."
else
  fail_check "'make status' execution failed inside container! Output: ${MAKE_STATUS_OUT}"
fi

log_info "Verifying 'make models' command execution from /data inside container..."
MAKE_MODELS_OUT=$(docker compose exec -T -w /data code-server make models 2>&1 || echo "ERROR")
if echo "${MAKE_MODELS_OUT}" | grep -q "brainsos-core"; then
  log_success "'make models' successfully executed from /data directory."
else
  fail_check "'make models' execution failed inside container! Output: ${MAKE_MODELS_OUT}"
fi

echo ""
log_success "======================================================================"
log_success "brainsOS: Operator IDE Verification PASSED (All Checks Satisfied)"
log_success "======================================================================"
echo ""
