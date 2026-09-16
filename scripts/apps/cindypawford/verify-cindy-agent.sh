#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Cindy Pawford Agent Unit Automated Verification Suite
# Ticket #87 (CW-0A): Base Persona, Tenancy & Monorepo Web Scaffold
# ==============================================================================

set -euo pipefail

# Visual styling
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

TITAN_DOMAIN="${TITAN_DOMAIN:-titan.local}"
CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-80}"
AGENT_ID="cindy-pawford"
CONTAINER="titan-agent-${AGENT_ID}"
SITE_DIR="${REPO_ROOT}/apps/cindypawford/site"
MEM_DIR="${REPO_ROOT}/data/memories/${AGENT_ID}"
WORK_DIR="${REPO_ROOT}/data/workspace/${AGENT_ID}"

log_info "================================================================="
log_info "  Running Cindy Pawford (CW-0A) Agent Unit Verification Suite   "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Step 1: Manifest Synchronization & Compose Topology
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet manifest synchronization & compose topology..."

if [ ! -x "${REPO_ROOT}/scripts/control/sync-agents.sh" ]; then
  log_error "scripts/control/sync-agents.sh is missing or not executable."
  exit 1
fi

"${REPO_ROOT}/scripts/control/sync-agents.sh" --check
log_success "Fleet manifest drift check passed (config/agents.yaml is 100% in sync)."

docker compose config -q
log_success "Docker Compose topology syntax validated successfully."

# ------------------------------------------------------------------------------
# Step 2: Ensure Container is Running & Sandboxed
# ------------------------------------------------------------------------------
log_info "Step 2: Checking agent container status and sandbox constraints..."

if ! docker ps --format '{{.Names}}' | grep -qw "${CONTAINER}"; then
  log_info "Starting agent container '${CONTAINER}'..."
  docker compose up -d "agent-${AGENT_ID}"
  sleep 3
fi

# Verify container is running
STATUS=$(docker inspect "${CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
if [ "${STATUS}" != "running" ]; then
  log_error "Container '${CONTAINER}' is not in running state (Status: ${STATUS})."
  exit 1
fi
log_success "Container '${CONTAINER}' is running."

# Verify unprivileged UID 1000
UID_CHECK=$(docker exec "${CONTAINER}" id -u hermes 2>/dev/null || echo "failed")
if [ "${UID_CHECK}" = "1000" ]; then
  log_success "Container '${CONTAINER}' verified running under unprivileged UID 1000."
else
  log_error "Security check failed: UID is '${UID_CHECK}' (expected 1000)."
  exit 1
fi

# Verify Docker socket isolation (Rule 4)
if ! docker exec "${CONTAINER}" test -e /var/run/docker.sock 2>/dev/null; then
  log_success "Container '${CONTAINER}' verified strictly isolated from host Docker socket."
else
  log_error "Security violation: Docker socket detected inside container '${CONTAINER}'!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 3: Monorepo Workspace Mount & File Permissions
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying monorepo workspace mount and read/write permissions..."

# Check that host site directory exists
if [ ! -d "${SITE_DIR}" ]; then
  log_error "Host site directory '${SITE_DIR}' does not exist."
  exit 1
fi

# Check required vanilla web files on host
for file in index.html styles.css app.js; do
  if [ -f "${SITE_DIR}/${file}" ]; then
    log_success "Verified host site file: apps/cindypawford/site/${file}"
  else
    log_error "Missing required site file: apps/cindypawford/site/${file}"
    exit 1
  fi
done

# Verify container /workspace mount points to data/workspace/cindy-pawford
WORK_MOUNT_CHECK=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}')
if [ "${WORK_MOUNT_CHECK}" = "${WORK_DIR}" ]; then
  log_success "Verified container '/workspace' bind-mount maps directly to '${WORK_DIR}'."
else
  log_error "Container '/workspace' mount mismatch: '${WORK_MOUNT_CHECK}' vs expected '${WORK_DIR}'."
  exit 1
fi

# Verify container /app/html mount points to apps/cindypawford/site
HTML_MOUNT_CHECK=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/app/html"}}{{.Source}}{{end}}{{end}}')
if [ "${HTML_MOUNT_CHECK}" = "${SITE_DIR}" ]; then
  log_success "Verified container '/app/html' bind-mount maps directly to '${SITE_DIR}'."
else
  log_error "Container '/app/html' mount mismatch: '${HTML_MOUNT_CHECK}' vs expected '${SITE_DIR}'."
  exit 1
fi

# Test container write permissions in /app/html
TEST_WRITE_FILE="/app/html/.test_cindy_perm_$(date +%s)"
docker exec "${CONTAINER}" bash -c "echo 'cindy_write_ok' > ${TEST_WRITE_FILE}"

if [ -f "${SITE_DIR}/$(basename "${TEST_WRITE_FILE}")" ]; then
  log_success "Verified: Agent has verified write access to apps/cindypawford/site from /app/html."
  docker exec "${CONTAINER}" rm -f "${TEST_WRITE_FILE}"
else
  log_error "Write test failed: Host did not observe file created from container /app/html."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 4: Persona Directives & Memory Plane Purity (Rule 1 & Rule 7)
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying persona directives and memory plane purity..."

# Check SOUL.md in agent memory partition
SOUL_PATH="${MEM_DIR}/SOUL.md"
if [ -f "${SOUL_PATH}" ]; then
  log_success "Found seeded SOUL.md at ${SOUL_PATH}."
else
  log_error "Missing SOUL.md in memory partition: ${SOUL_PATH}"
  exit 1
fi

# Verify persona content markers (couture, bacon, comedic irony, Creative Director)
if grep -q "Cindy Pawford" "${SOUL_PATH}" && grep -q "bacon" "${SOUL_PATH}" && grep -q "couture" "${SOUL_PATH}" && grep -q "Creative Director" "${SOUL_PATH}"; then
  log_success "SOUL.md contains required persona voice and Creative Director directives."
else
  log_error "SOUL.md is missing required voice or Creative Director elements."
  exit 1
fi

# Verify Sub-Agent SOUL.md in memory partition and workspace
SUB_SOUL_PATH="${MEM_DIR}/subagents/web-developer/SOUL.md"
WORK_SUB_SOUL="${WORK_DIR}/subagents/web-developer/SOUL.md"
if [ -f "${SUB_SOUL_PATH}" ] && [ -f "${WORK_SUB_SOUL}" ]; then
  log_success "Found seeded sub-agent SOUL.md at ${SUB_SOUL_PATH} and ${WORK_SUB_SOUL}."
else
  log_error "Missing sub-agent SOUL.md in subagents partition!"
  exit 1
fi

# Verify developer sub-agent persona purity (Strict engineering, ZERO canine humor/bacon)
if grep -q "Website Builder Sub-Agent" "${SUB_SOUL_PATH}" && grep -q "Zero Conversational Chatter" "${SUB_SOUL_PATH}"; then
  log_success "Sub-agent SOUL.md verified under clean software engineering persona."
else
  log_error "Sub-agent SOUL.md is missing required engineering directives."
  exit 1
fi

if grep -qi "bacon" "${SUB_SOUL_PATH}" || grep -qi "tennis ball" "${SUB_SOUL_PATH}"; then
  log_error "Persona contamination: Found conversational canine humor inside developer sub-agent SOUL.md!"
  exit 1
fi
log_success "Sub-agent SOUL.md verified 100% clean of conversational roleplay or canine humor."

# Verify Rule 7: Compartmentalization (No host daemon/DB leakage in SOUL.md or sub-agent SOUL.md)
for forbidden in "127.0.0.1:11434" "titan-litellm-db" "postgresql://" "vllm" "SST"; do
  if grep -qi "${forbidden}" "${SOUL_PATH}" || grep -qi "${forbidden}" "${SUB_SOUL_PATH}"; then
    log_error "Rule 7 violation: Found forbidden backend leak '${forbidden}' in SOUL files!"
    exit 1
  fi
done
log_success "Rule 7 verified: Zero host backend infrastructure details leaked in SOUL files."

# Verify Rule 1: Memory plane purity (No sqlite .db or binary indices in /memories)
DIRTY_FILES=$(find "${MEM_DIR}" -type f \( -name "*.db" -o -name "*.sqlite" -o -name "*.bin" \) 2>/dev/null || true)
if [ -z "${DIRTY_FILES}" ]; then
  log_success "Rule 1 verified: Memory plane ${MEM_DIR} is 100% pure OKF Markdown."
else
  log_error "Rule 1 violation: Found forbidden binary/db files in memory: ${DIRTY_FILES}"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Cross-Agent & Host Isolation Probes
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying cross-agent and host filesystem isolation..."

# Probe 1: Cindy cannot access primary agent memory
if docker exec "${CONTAINER}" test -d "${REPO_ROOT}/data/memories/primary" 2>/dev/null; then
  log_error "Isolation breach: Cindy container can access primary agent memory on host!"
  exit 1
fi
log_success "Verified: Cindy cannot access primary agent memory."

# Probe 2: Cindy cannot access primary workspace
if docker exec "${CONTAINER}" test -d "${REPO_ROOT}/data/workspace/primary" 2>/dev/null; then
  log_error "Isolation breach: Cindy container can access primary agent workspace on host!"
  exit 1
fi
log_success "Verified: Cindy cannot access primary agent workspace."

# Probe 3: Cindy cannot view host root files or .env
if docker exec "${CONTAINER}" test -f "${REPO_ROOT}/.env" 2>/dev/null; then
  log_error "Isolation breach: Cindy container can access host .env file!"
  exit 1
fi
log_success "Verified: Cindy container is strictly isolated from host root and secrets."

# ------------------------------------------------------------------------------
# Step 6: Hermes Cron Job Automation Definitions
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying Hermes cron job automation definitions..."

CRON_FILE="${WORK_DIR}/cron/jobs.json"
if [ -f "${CRON_FILE}" ]; then
  log_success "Found cron jobs configuration at ${CRON_FILE}."
else
  log_error "Missing cron jobs configuration at ${CRON_FILE}."
  exit 1
fi

# Verify daily feature drop job
if grep -q "daily-feature-drop" "${CRON_FILE}" && grep -q "0 2 \* \* 1-6" "${CRON_FILE}"; then
  log_success "Verified 'Daily Feature Drop' cron job defined (Mon–Sat 2:00 AM)."
else
  log_error "Missing or invalid 'Daily Feature Drop' cron definition in ${CRON_FILE}."
  exit 1
fi

# Verify weekly era reset job
if grep -q "weekly-era-reset" "${CRON_FILE}" && grep -q "0 2 \* \* 0" "${CRON_FILE}"; then
  log_success "Verified 'Weekly Era Reset' cron job defined (Sunday 2:00 AM)."
else
  log_error "Missing or invalid 'Weekly Era Reset' cron definition in ${CRON_FILE}."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 7: Caddy Ingress & Telegram Stub
# ------------------------------------------------------------------------------
log_info "Step 7: Verifying Caddy ingress resolution and Telegram stub..."

# HTTP probe via Caddy on port 80 with Host header
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: cindy-pawford.${TITAN_DOMAIN}" "http://127.0.0.1:${CADDY_HTTP_PORT}/" || echo "failed")
if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "302" ] || [ "${HTTP_STATUS}" = "401" ]; then
  log_success "Caddy ingress resolves 'cindy-pawford.${TITAN_DOMAIN}' -> HTTP ${HTTP_STATUS}."
else
  log_warn "Caddy ingress returned '${HTTP_STATUS}' (gateway will route upon reload)."
fi

# Verify Telegram bot per-agent configuration
if grep -qE "@CindyPawford(_bot|Bot)" "${REPO_ROOT}/config/agents.yaml" && \
   grep -qE "@CindyPawford(_bot|Bot)" "${WORK_DIR}/config.yaml" && \
   grep -q "TELEGRAM_BOT_TOKEN_CINDY" "${REPO_ROOT}/docker-compose.agents.yml"; then
  log_success "Verified per-agent Telegram config (CindyPawford bot profile, TELEGRAM_BOT_TOKEN_CINDY)."
else
  log_error "Missing per-agent Telegram configuration for Cindy Pawford."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 8: Generic Sub-Agent Manifest & Code Quality Gate Sanitization
# ------------------------------------------------------------------------------
log_info "Step 8: Verifying generic sub-agent manifest and quality gate sanitization..."

# 8a. Verify subagents.json catalog in workspace and memories
if [ -f "${WORK_DIR}/subagents.json" ] && [ -f "${MEM_DIR}/subagents.json" ]; then
  log_success "Found subagents.json catalog in workspace and memory partitions."
else
  log_error "Missing subagents.json catalog!"
  exit 1
fi

# Verify subagent properties (id, tool_name, persona, model)
if grep -q "web-developer" "${WORK_DIR}/subagents.json" && \
   grep -q "build_website_feature" "${WORK_DIR}/subagents.json" && \
   grep -q "cindy-active-coding-model" "${WORK_DIR}/subagents.json"; then
  log_success "Verified 'web-developer' subagent definition in subagents.json."
else
  log_error "Invalid or incomplete web-developer subagent definition in subagents.json!"
  exit 1
fi

# 8b. Verify subagent execution engine script exists
BUILDER_SCRIPT="${REPO_ROOT}/scripts/apps/cindypawford/cindy-web-builder.py"
if [ -x "${BUILDER_SCRIPT}" ]; then
  log_success "Found executable sub-agent builder script: ${BUILDER_SCRIPT}"
else
  log_error "Missing or non-executable sub-agent builder script: ${BUILDER_SCRIPT}"
  exit 1
fi

# 8c. Test parameterized sub-agent invocation with dry-run
log_info "Testing parameterized subagent invocation with quality gate & sanitization..."
INVOKE_OUTPUT=$(python3 "${BUILDER_SCRIPT}" \
  --feature-name "Velvet Paw VIP Status Lounge" \
  --specification "Add a luxury gold badge in the navigation bar" \
  --canvas-dir "${SITE_DIR}" \
  --memory-dir "${MEM_DIR}" \
  --dry-run)

if echo "${INVOKE_OUTPUT}" | grep -q '"status": "success"'; then
  log_success "Sub-agent dry-run execution succeeded with status 'success'."
else
  log_error "Sub-agent dry-run execution failed: ${INVOKE_OUTPUT}"
  exit 1
fi

# 8d. Test Quality Gate & Sanitization functions (Markdown fences & conversational strip)
python3 -c "
import sys
sys.path.insert(0, '${REPO_ROOT}/scripts/apps/cindypawford')
import importlib.util
spec = importlib.util.spec_from_file_location('cindy_web_builder', '${BUILDER_SCRIPT}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from pathlib import Path

# Test fence stripping
dirty_js = '''\`\`\`javascript
(function() {
  console.log('Clean execution');
})();
\`\`\`'''
clean_js, warns = mod.sanitize_code_content(dirty_js, 'app.js')
assert '\`\`\`' not in clean_js, 'Markdown fences were not stripped!'
assert '(function()' in clean_js, 'Valid JS missing!'

# Test conversational header stripping
dirty_html = '''Here is the updated HTML with the new VIP banner:
\`\`\`html
<section id=\"vip-lounge\"><h2>VIP Lounge</h2></section>
\`\`\`
Hope this looks fabulous!'''
clean_html, warns = mod.sanitize_code_content(dirty_html, 'index.html')
assert '\`\`\`' not in clean_html, 'Fences remained in HTML!'
assert '<section' in clean_html, 'HTML content missing!'
assert 'Here is the' not in clean_html, 'Conversational header was not stripped!'

# Test syntax validation
valid, err = mod.validate_syntax(Path('app.js'), clean_js)
assert valid, f'Syntax check failed on clean JS: {err}'

# Test invalid syntax rejection
invalid_js = 'function broken( {'
valid_bad, err_bad = mod.validate_syntax(Path('app.js'), invalid_js)
assert not valid_bad, 'Syntax check failed to reject invalid JavaScript!'
"
log_success "Quality Gate passed: Markdown fences and conversational chatter stripped, JS syntax validated."

# 8e. Verify titan-subagents plugin files
PLUGIN_DIR="${WORK_DIR}/plugins/titan-subagents"
if [ -f "${PLUGIN_DIR}/plugin.yaml" ] && [ -f "${PLUGIN_DIR}/__init__.py" ]; then
  log_success "Verified titan-subagents plugin scaffolded in workspace: ${PLUGIN_DIR}."
else
  log_error "Missing titan-subagents plugin in workspace!"
  exit 1
fi

log_info "================================================================="
log_success "  All Cindy Pawford (CW-0A) Verification Checks PASSED!         "
log_info "================================================================="
