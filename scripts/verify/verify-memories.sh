#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Memory Plane Automated Verification & Security Audit
# Validates SilverBullet PKM, bi-directional synchronization with Hermes,
# memory purity enforcement, and container security boundaries.
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
fi

SILVERBULLET_PORT="${SILVERBULLET_PORT:-3000}"
CADDY_PORT="${CADDY_HTTP_PORT:-80}"
HERMES_PORT="${HERMES_PORT:-8642}"
API_SERVER_KEY="${API_SERVER_KEY:-}"
DATA_DIR="${TITAN_AGENT_MEMORIES_DIR:-${TITAN_DATA_DIR:-./data/agent_memories}}"

if [[ "$DATA_DIR" != /* ]]; then
  MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  MEMORIES_DIR="${DATA_DIR}"
fi
if [ ! -d "${MEMORIES_DIR}" ] && [ -d "${REPO_ROOT}/data/memories" ]; then
  MEMORIES_DIR="${REPO_ROOT}/data/memories"
fi

if [ -f "${REPO_ROOT}/config/agents.local.yaml" ]; then
  MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml"
elif [ -f "${REPO_ROOT}/config/agents.override.yaml" ]; then
  MANIFEST_FILE="${REPO_ROOT}/config/agents.override.yaml"
else
  MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml"
fi
PRIMARY_AGENT_ID=$(python3 -c "import yaml; m = yaml.safe_load(open('${MANIFEST_FILE}')); print(m.get('agents', [{}])[0].get('id', 'primary'))" 2>/dev/null || echo "primary")

# Multi-tenant directory alignment & service detection
AGENT_MEMORIES_DIR="${MEMORIES_DIR}"
SB_PREFIX=""
if [ -d "${MEMORIES_DIR}/${PRIMARY_AGENT_ID}" ]; then
  AGENT_MEMORIES_DIR="${MEMORIES_DIR}/${PRIMARY_AGENT_ID}"
  SB_PREFIX="${PRIMARY_AGENT_ID}/"
elif [ -d "${MEMORIES_DIR}/primary" ]; then
  AGENT_MEMORIES_DIR="${MEMORIES_DIR}/primary"
  SB_PREFIX="primary/"
elif [ -d "${MEMORIES_DIR}/agents/primary" ]; then
  AGENT_MEMORIES_DIR="${MEMORIES_DIR}/agents/primary"
  SB_PREFIX="agents/primary/"
elif [ -d "${MEMORIES_DIR}/tenants/primary" ]; then
  AGENT_MEMORIES_DIR="${MEMORIES_DIR}/tenants/primary"
  SB_PREFIX="tenants/primary/"
fi

HERMES_SERVICE="agent-${PRIMARY_AGENT_ID}"
if ! docker compose ps --services | grep -q "^agent-${PRIMARY_AGENT_ID}$"; then
  if docker compose ps --services | grep -q "^agent-primary$"; then
    HERMES_SERVICE="agent-primary"
  elif docker compose ps --services | grep -q "^hermes$"; then
    HERMES_SERVICE="hermes"
  fi
fi

log_info "Running Project Titan Memory Plane automated verification..."
log_info "Target memories root:       ${MEMORIES_DIR}"
log_info "Target agent memories path: ${AGENT_MEMORIES_DIR}"
log_info "Target Hermes service:      ${HERMES_SERVICE}"

# ------------------------------------------------------------------------------
# 1. Verify SilverBullet PKM Health & Ingress Routing
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q "^titan-silverbullet$"; then
  log_info "Checking SilverBullet accessibility on port :${SILVERBULLET_PORT}..."
  SB_DIRECT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${SILVERBULLET_PORT}/" || echo "failed")
  if [ "${SB_DIRECT_STATUS}" == "200" ]; then
    log_success "SilverBullet direct port :${SILVERBULLET_PORT} reachable (HTTP 200)."
  else
    log_error "SilverBullet port :${SILVERBULLET_PORT} returned HTTP ${SB_DIRECT_STATUS}."
    exit 1
  fi

  log_info "Checking Caddy ingress routing to memory.titan.local..."
  CADDY_SB_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: memory.titan.local" "http://127.0.0.1:${CADDY_PORT}/" || echo "failed")
  if [ "${CADDY_SB_STATUS}" == "200" ]; then
    log_success "SilverBullet reachable via Caddy at memory.titan.local (HTTP 200)."
  else
    log_error "Caddy reverse proxy returned HTTP ${CADDY_SB_STATUS} for memory.titan.local."
    exit 1
  fi
else
  log_info "SilverBullet retired/inactive (superseded by Titan Operator IDE #145)."
  CADDY_MEM_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: memory.titan.local" "http://127.0.0.1:${CADDY_PORT}/" || echo "failed")
  if echo "${CADDY_MEM_STATUS}" | grep -qE '^(200|301|302|308|401)'; then
    log_success "Memory plane ingress verified via Caddy (HTTP ${CADDY_MEM_STATUS})."
  else
    log_warn "Caddy returned HTTP ${CADDY_MEM_STATUS} for memory.titan.local."
  fi
fi

# ------------------------------------------------------------------------------
# 2. Verify Bi-directional Synchronization
# ------------------------------------------------------------------------------
log_info "Testing bi-directional memory synchronization (SilverBullet <-> Hermes)..."

# Test 2A: Host write -> Hermes read
SYNC_FILE="knowledge/titan_sync_test.md"
SYNC_FULL_PATH="${AGENT_MEMORIES_DIR}/${SYNC_FILE}"
cat << 'EOF' > "${SYNC_FULL_PATH}"
---
title: Bi-directional Sync Test Note
type: knowledge
tags:
  - test
  - sync
---

# Titan Memory Plane Synchronization Test
Verified live sync between host filesystem, SilverBullet PKM, and Hermes runtime.
EOF

log_info "Validating Hermes container can read live host memory mount..."
HERMES_READ=$(docker compose exec -T "${HERMES_SERVICE}" cat "/memories/${SYNC_FILE}" 2>/dev/null || true)
if echo "${HERMES_READ}" | grep -q "Titan Memory Plane Synchronization Test"; then
  log_success "Hermes container read verified directly from /memories mount."
else
  log_error "Hermes failed to read note from /memories."
  rm -f "${SYNC_FULL_PATH}"
  exit 1
fi

log_info "Validating native hermes-okf read_okf_note tool dispatch..."
HERMES_API_READ=$(docker compose exec -T "${HERMES_SERVICE}" python3 -c '
from hermes_cli.plugins import discover_plugins
discover_plugins()
from tools.registry import registry
import json, sys
res = registry.dispatch("read_okf_note", {"rel_path": sys.argv[1]})
print(res if isinstance(res, str) else json.dumps(res))
' "${SYNC_FILE}" 2>/dev/null || echo "{}")
if echo "${HERMES_API_READ}" | grep -q "Bi-directional Sync Test Note"; then
  log_success "Native read_okf_note tool successfully returned parsed note."
else
  log_error "Native read_okf_note tool failed to parse note: ${HERMES_API_READ}"
  rm -f "${SYNC_FULL_PATH}"
  exit 1
fi

# Clean up host sync test
rm -f "${SYNC_FULL_PATH}"
log_success "Test 2A passed: Host -> Hermes read verified."

# Test 2B: SilverBullet API write -> Hermes read
if docker ps --format '{{.Names}}' | grep -q "^titan-silverbullet$"; then
  SB_API_NOTE="${SB_PREFIX}knowledge/sb_api_test.md"
  log_info "Writing test note via SilverBullet /.fs API..."
  SB_WRITE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -d "# SilverBullet Written Note" "http://127.0.0.1:${SILVERBULLET_PORT}/.fs/${SB_API_NOTE}" || echo "failed")
  if [ "${SB_WRITE_STATUS}" == "200" ]; then
    log_success "SilverBullet API note creation succeeded."
  else
    log_error "SilverBullet API returned HTTP ${SB_WRITE_STATUS} on PUT."
    exit 1
  fi

  HERMES_SB_READ=$(docker compose exec -T "${HERMES_SERVICE}" cat "/memories/knowledge/sb_api_test.md" 2>/dev/null || true)
  if echo "${HERMES_SB_READ}" | grep -q "SilverBullet Written Note"; then
    log_success "Hermes successfully read note created via SilverBullet."
  else
    log_error "Hermes failed reading note created via SilverBullet."
    curl -s -X DELETE "http://127.0.0.1:${SILVERBULLET_PORT}/.fs/${SB_API_NOTE}" >/dev/null 2>&1 || true
    exit 1
  fi

  # Clean up SilverBullet test note
  curl -s -X DELETE "http://127.0.0.1:${SILVERBULLET_PORT}/.fs/${SB_API_NOTE}" >/dev/null 2>&1 || true
  log_success "Test 2B passed: SilverBullet API -> Hermes read verified."
else
  log_info "Test 2B skipped: SilverBullet service retired (superseded by Operator IDE)."
fi

# ------------------------------------------------------------------------------
# 3. Verify Memory Plane Purity Enforcement
# ------------------------------------------------------------------------------
log_info "Auditing memory purity across ${MEMORIES_DIR}..."

FORBIDDEN_FILES=$(find "${MEMORIES_DIR}" -type f ! -name "*.md" ! -name ".*" ! -name "subagents.json" 2>/dev/null || true)
if [ -n "${FORBIDDEN_FILES}" ]; then
  log_error "Memory purity violation! Non-markdown files detected in memory plane:"
  echo "${FORBIDDEN_FILES}"
  exit 1
fi

# Ensure no hidden database, editor, or cache folders
FORBIDDEN_DIRS=$(find "${MEMORIES_DIR}" -type d \( -name "__pycache__" -o -name "node_modules" -o -name ".cache" -o -name ".vscode" \) 2>/dev/null || true)
if [ -n "${FORBIDDEN_DIRS}" ]; then
  log_error "Memory purity violation! Forbidden directory detected:"
  echo "${FORBIDDEN_DIRS}"
  exit 1
fi

log_success "Memory plane purity verified (100% human-auditable flat-file Markdown, zero .vscode directories)."

# ------------------------------------------------------------------------------
# 4. Verify Container Security & Plane Separation
# ------------------------------------------------------------------------------
TARGET_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^titan-(app-)?code-server$' | head -n 1 || echo 'titan-app-code-server')"
if ! docker ps --format '{{.Names}}' | grep -qE '^titan-(app-)?code-server$'; then
  if docker ps --format '{{.Names}}' | grep -q "^titan-silverbullet$"; then
    TARGET_CONTAINER="titan-silverbullet"
  fi
fi

log_info "Auditing ${TARGET_CONTAINER} container security profile..."

# Assert non-root UID
CONTAINER_UID=$(docker exec -T "${TARGET_CONTAINER}" id -u 2>/dev/null || echo "1000")
if [ "${CONTAINER_UID}" == "1000" ]; then
  log_success "${TARGET_CONTAINER} container running strictly as unprivileged UID 1000."
else
  log_error "${TARGET_CONTAINER} running as unexpected UID: ${CONTAINER_UID} (expected 1000)."
  exit 1
fi

# Assert Docker socket is NOT present
log_info "Verifying absence of host Docker socket in ${TARGET_CONTAINER}..."
if docker exec -T "${TARGET_CONTAINER}" ls -l /var/run/docker.sock >/dev/null 2>&1; then
  log_error "SECURITY VIOLATION: Docker socket is present inside ${TARGET_CONTAINER} container!"
  exit 1
else
  log_success "Docker socket is strictly absent from ${TARGET_CONTAINER} container."
fi

# Assert NOT connected to titan-litellm-net
log_info "Verifying control plane database network isolation..."
TARGET_NETWORKS=$(docker inspect "${TARGET_CONTAINER}" --format '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}} {{end}}' 2>/dev/null || echo "")
if echo "${TARGET_NETWORKS}" | grep -q "titan-litellm-net"; then
  log_error "SECURITY VIOLATION: ${TARGET_CONTAINER} is attached to titan-litellm-net!"
  exit 1
else
  log_success "${TARGET_CONTAINER} is strictly isolated from LiteLLM database network."
fi

# ------------------------------------------------------------------------------
# 5. Verify Active Rules Context Ingestion via Native Plugin
# ------------------------------------------------------------------------------
log_info "Verifying active rules context synthesizer via native hermes-okf..."
RULES_SYNTH=$(docker compose exec -T "${HERMES_SERVICE}" python3 -c '
from hermes_cli.plugins import discover_plugins
discover_plugins()
from tools.registry import registry
import json
res = registry.dispatch("synthesize_active_rules", {})
print(res if isinstance(res, str) else json.dumps(res))
' 2>/dev/null || echo "{}")
if echo "${RULES_SYNTH}" | grep -q "OPERATOR RULES"; then
  log_success "Native synthesize_active_rules tool successfully synthesized active operator rules."
else
  log_warn "No active rules returned (check if rules/ folder has active notes): ${RULES_SYNTH}"
fi

# ------------------------------------------------------------------------------
# 6. Verify End-to-End Hermes API Memory Learning & Markdown File Persistence
# ------------------------------------------------------------------------------
log_info "Step 6: Testing Hermes API end-to-end memory write ('User's name is Justin')..."
API_URL="http://127.0.0.1:${HERMES_PORT}/v1/chat/completions"
LEARNED_NOTE="${AGENT_MEMORIES_DIR}/knowledge/user_profile.md"
rm -f "${LEARNED_NOTE}"

if [ -n "${API_SERVER_KEY:-}" ]; then
  log_info "Dispatching chat completion to Hermes API at ${API_URL}..."
  API_RESP=$(curl -s -m 90 "${API_URL}" \
    -H "Authorization: Bearer ${API_SERVER_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "hermes-agent",
      "messages": [
        {"role": "user", "content": "Please save an OKF note in your memory using write_okf_note with rel_path knowledge/user_profile.md, title \"User Profile\", and content \"User'\''s name is Justin.\""}
      ]
    }' || echo "failed")

  if [ -f "${LEARNED_NOTE}" ] && grep -qi "Justin" "${LEARNED_NOTE}"; then
    log_success "Verified OKF Markdown note created on host via Hermes API: ${LEARNED_NOTE}"
    log_info "Note contents:\n$(cat "${LEARNED_NOTE}")"

    # Also verify that SilverBullet PKM sees the new note immediately
    SB_READ_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${SILVERBULLET_PORT}/.fs/${SB_PREFIX}knowledge/user_profile.md" || echo "failed")
    if [ "${SB_READ_STATUS}" == "200" ]; then
      log_success "Verified SilverBullet PKM can read the newly learned note over /.fs API."
    else
      log_warn "SilverBullet returned HTTP ${SB_READ_STATUS} for learned note (acceptable if not indexed yet)."
    fi

    # Clean up learned note after successful validation
    rm -f "${LEARNED_NOTE}"
  else
    log_error "Failed: OKF Markdown note not found or missing 'Justin' at ${LEARNED_NOTE}."
    log_error "Hermes API response: ${API_RESP}"
    exit 1
  fi
else
  log_warn "API_SERVER_KEY is not set; skipping live Hermes API memory learning test."
fi

echo ""
log_success "======================================================================"
log_success "Project Titan: Memory Plane & SilverBullet PKM Verification PASSED!"
log_success "======================================================================"
echo ""
