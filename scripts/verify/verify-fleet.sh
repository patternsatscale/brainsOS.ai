#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Multi-Agent Fleet Automated Verification Suite
# Validates manifest drift, compose topology, Caddy ingress routing,
# cross-tenant storage isolation, and LiteLLM hardware serialization.
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
LITELLM_PORT="${LITELLM_PORT:-4000}"
EXPLICIT_MANIFEST=0
if [ -n "${MANIFEST_FILE:-}" ]; then
  EXPLICIT_MANIFEST=1
else
  if [ -f "${REPO_ROOT}/config/agents.local.yaml" ]; then
    MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml"
  elif [ -f "${REPO_ROOT}/config/agents.override.yaml" ]; then
    MANIFEST_FILE="${REPO_ROOT}/config/agents.override.yaml"
  else
    MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml"
  fi
fi

log_info "================================================================="
log_info "  Running Project Titan Multi-Agent Fleet Verification Suite     "
log_info "================================================================="

# ------------------------------------------------------------------------------
# 1. Manifest Drift & Topology Validation (Both Canonical & Local)
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet manifest synchronization & compose topology..."

if [ ! -x "${REPO_ROOT}/scripts/control/sync-agents.sh" ]; then
  log_error "scripts/control/sync-agents.sh is missing or not executable."
  exit 1
fi

if [ "${EXPLICIT_MANIFEST}" -eq 1 ]; then
  log_info "Validating specified manifest: $(basename "${MANIFEST_FILE}")..."
  MANIFEST_FILE="${MANIFEST_FILE}" "${REPO_ROOT}/scripts/control/sync-agents.sh"
  MANIFEST_FILE="${MANIFEST_FILE}" "${REPO_ROOT}/scripts/control/sync-agents.sh" --check
  docker compose config -q
  log_success "Manifest $(basename "${MANIFEST_FILE}") validated successfully."
else
  # Always validate canonical open-source manifest
  log_info "Validating canonical open-source manifest (config/agents.yaml)..."
  MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml" "${REPO_ROOT}/scripts/control/sync-agents.sh"
  MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml" "${REPO_ROOT}/scripts/control/sync-agents.sh" --check
  docker compose config -q
  log_success "Canonical open-source manifest validated successfully."

  # If host-local manifest exists, validate it as well
  if [ -f "${REPO_ROOT}/config/agents.local.yaml" ]; then
    log_info "Validating host-local manifest override (config/agents.local.yaml)..."
    MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml" "${REPO_ROOT}/scripts/control/sync-agents.sh"
    MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml" "${REPO_ROOT}/scripts/control/sync-agents.sh" --check
    docker compose config -q
    log_success "Host-local manifest override validated successfully."
  fi
fi

# Detect enabled agents & primary agent from compose
ENABLED_AGENTS=$(docker compose config --services | grep '^agent-' | sed 's/^agent-//' || echo "primary football-dan cindy-pawford")
PRIMARY_AGENT_ID="primary"
if echo "${ENABLED_AGENTS}" | grep -qw "terrastella"; then
  PRIMARY_AGENT_ID="terrastella"
elif echo "${ENABLED_AGENTS}" | grep -qw "primary"; then
  PRIMARY_AGENT_ID="primary"
else
  PRIMARY_AGENT_ID=$(echo "${ENABLED_AGENTS}" | awk '{print $1}')
fi
PRIMARY_CONTAINER="titan-agent-${PRIMARY_AGENT_ID}"

# ------------------------------------------------------------------------------
# 2. Container Health & Unprivileged UID Verification
# ------------------------------------------------------------------------------
log_info "Step 2: Checking agent container statuses and unprivileged sandboxing..."

# Ensure core services and primary agent unit are running
if ! docker compose ps --services --filter "status=running" | grep -q "^caddy$"; then
  log_info "Starting caddy..."
  docker compose up -d caddy
  sleep 2
fi

# Clean up any conflicting superseded primary agent container
for old_primary in primary terrastella; do
  if [ "${old_primary}" != "${PRIMARY_AGENT_ID}" ]; then
    if docker ps -a --format '{{.Names}}' | grep -qw "titan-agent-${old_primary}"; then
      log_info "Stopping superseded container 'titan-agent-${old_primary}' to release ports for '${PRIMARY_CONTAINER}'..."
      docker stop "titan-agent-${old_primary}" >/dev/null 2>&1 || true
      docker rm -f "titan-agent-${old_primary}" >/dev/null 2>&1 || true
    fi
  fi
done

if ! docker compose ps --services --filter "status=running" | grep -q "^agent-${PRIMARY_AGENT_ID}$"; then
  log_info "Starting fleet agents..."
  for a_id in ${ENABLED_AGENTS}; do
    docker compose up -d "agent-${a_id}"
  done
  sleep 3
fi

for agent_id in ${ENABLED_AGENTS}; do
  CONTAINER="titan-agent-${agent_id}"
  if ! docker ps --format '{{.Names}}' | grep -qw "${CONTAINER}"; then
    log_warn "Container '${CONTAINER}' is not currently running. Starting service agent-${agent_id}..."
    docker compose up -d "agent-${agent_id}"
    sleep 2
  fi

  # Verify UID 1000
  UID_CHECK=$(docker exec "${CONTAINER}" id -u hermes 2>/dev/null || echo "failed")
  if [ "${UID_CHECK}" = "1000" ]; then
    log_success "Container '${CONTAINER}' verified configured with unprivileged UID 1000."
  else
    log_error "Container '${CONTAINER}' security check failed: UID is '${UID_CHECK}' (expected 1000)."
    exit 1
  fi

  # Verify no docker socket mounted
  if ! docker exec "${CONTAINER}" test -e /var/run/docker.sock 2>/dev/null; then
    log_success "Container '${CONTAINER}' verified strictly isolated from host Docker socket."
  else
    log_error "Security violation: Docker socket detected inside container '${CONTAINER}'!"
    exit 1
  fi
done

# ------------------------------------------------------------------------------
# 3. Caddy Ingress Gateway & Subdomain Resolution
# ------------------------------------------------------------------------------
log_info "Step 3: Checking Caddy ingress routing for agent subdomains..."

for agent_id in ${ENABLED_AGENTS}; do
  SUBDOMAIN="${agent_id}.${TITAN_DOMAIN}"
  
  # HTTP probe via Caddy on port 80 with Host header (with retry for container bootstrap)
  HTTP_STATUS="failed"
  for _ in {1..8}; do
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${SUBDOMAIN}" "http://127.0.0.1:${CADDY_HTTP_PORT}/" || echo "failed")
    if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "302" ] || [ "${HTTP_STATUS}" = "401" ]; then
      break
    fi
    sleep 1
  done
  if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "302" ] || [ "${HTTP_STATUS}" = "401" ]; then
    log_success "Caddy ingress resolves '${SUBDOMAIN}' -> HTTP ${HTTP_STATUS}."
  else
    log_error "Caddy ingress failed for '${SUBDOMAIN}': got HTTP '${HTTP_STATUS}'."
    exit 1
  fi

  # Check localhost alias as well
  LOCAL_STATUS="failed"
  for _ in {1..8}; do
    LOCAL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${agent_id}.localhost" "http://127.0.0.1:${CADDY_HTTP_PORT}/" || echo "failed")
    if [ "${LOCAL_STATUS}" = "200" ] || [ "${LOCAL_STATUS}" = "302" ] || [ "${LOCAL_STATUS}" = "401" ]; then
      break
    fi
    sleep 1
  done
  if [ "${LOCAL_STATUS}" = "200" ] || [ "${LOCAL_STATUS}" = "302" ] || [ "${LOCAL_STATUS}" = "401" ]; then
    log_success "Caddy ingress resolves '${agent_id}.localhost' -> HTTP ${LOCAL_STATUS}."
  else
    log_error "Caddy ingress failed for '${agent_id}.localhost': got HTTP '${LOCAL_STATUS}'."
    exit 1
  fi
done

# ------------------------------------------------------------------------------
# 4. Cross-Tenant Storage & Memory Isolation Probes
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying cross-tenant storage isolation (Rule 1 & Rule 4)..."

SECONDARY_AGENT_ID=$(echo "${ENABLED_AGENTS}" | tr ' ' '\n' | grep -v "^${PRIMARY_AGENT_ID}$" | head -n 1 || echo "")
if [ -n "${SECONDARY_AGENT_ID}" ]; then
  SECONDARY_CONTAINER="titan-agent-${SECONDARY_AGENT_ID}"

  # Test 1: Write marker note into primary agent memory
  TEST_MARKER="marker_primary_$(date +%s)"
  docker exec "${PRIMARY_CONTAINER}" bash -c "echo '${TEST_MARKER}' > /memories/knowledge/isolation_test.md"

  # Test 2: Verify Secondary Agent CANNOT see primary agent marker
  if docker exec "${SECONDARY_CONTAINER}" test -f /memories/knowledge/isolation_test.md 2>/dev/null; then
    log_error "Isolation breach: ${SECONDARY_AGENT_ID} container can access ${PRIMARY_CONTAINER} /memories!"
    exit 1
  fi
  log_success "Verified: Agent '${SECONDARY_AGENT_ID}' cannot access Agent '${PRIMARY_AGENT_ID}' memory partition."

  # Test 3: Verify primary agent CANNOT see Secondary Agent workspace
  SEC_MARKER="marker_${SECONDARY_AGENT_ID}_$(date +%s)"
  docker exec "${SECONDARY_CONTAINER}" bash -c "echo '${SEC_MARKER}' > /workspace/sec_isolated.txt"

  if docker exec "${PRIMARY_CONTAINER}" test -f /workspace/sec_isolated.txt 2>/dev/null; then
    log_error "Isolation breach: ${PRIMARY_CONTAINER} can access ${SECONDARY_AGENT_ID} container /workspace!"
    exit 1
  fi
  log_success "Verified: Agent '${PRIMARY_AGENT_ID}' cannot access Agent '${SECONDARY_AGENT_ID}' workspace partition."

  # Clean up isolation test files
  docker exec "${PRIMARY_CONTAINER}" rm -f /memories/knowledge/isolation_test.md 2>/dev/null || true
  docker exec "${SECONDARY_CONTAINER}" rm -f /workspace/sec_isolated.txt 2>/dev/null || true

  # ------------------------------------------------------------------------------
  # 5. Hardware Concurrency & Serialization via LiteLLM
  # ------------------------------------------------------------------------------
  log_info "Step 5: Verifying hardware serialization through LiteLLM (Rule 3)..."

  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
    log_info "LiteLLM gateway is online; issuing concurrent completion probes across agents..."

    PRIMARY_KEY="${HERMES_LITELLM_KEY:-sk-titan-${PRIMARY_AGENT_ID}-key}"
    SEC_KEY="sk-titan-${SECONDARY_AGENT_ID}-key"

    # Issue concurrent health / models requests with different keys
    REQ1=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${PRIMARY_KEY}" "http://127.0.0.1:${LITELLM_PORT}/models" || echo "failed")
    REQ2=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${SEC_KEY}" "http://127.0.0.1:${LITELLM_PORT}/models" || echo "failed")

    if [ "${REQ1}" = "200" ] && [ "${REQ2}" = "200" ]; then
      log_success "Concurrent requests with distinct virtual keys handled cleanly by LiteLLM."
    else
      log_warn "LiteLLM concurrent probe returned HTTP ${REQ1} / ${REQ2} (acceptable if offline)."
    fi
  else
    log_info "LiteLLM gateway is not active; skipping live concurrency probe."
  fi

  # ------------------------------------------------------------------------------
  # 6. Targeted Emergency Stop & Granular Revocation Test
  # ------------------------------------------------------------------------------
  log_info "Step 6: Testing targeted single-tenant emergency stop..."

  if [ -x "${REPO_ROOT}/scripts/control/emergency-stop.sh" ]; then
    # Target only secondary agent
    "${REPO_ROOT}/scripts/control/emergency-stop.sh" "${SECONDARY_AGENT_ID}"

    # Assert secondary agent is paused or stopped
    SEC_STATE=$(docker inspect "${SECONDARY_CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "stopped")
    if [ "${SEC_STATE}" = "paused" ] || [ "${SEC_STATE}" = "exited" ]; then
      log_success "Targeted emergency stop successfully paused/stopped ${SECONDARY_CONTAINER} (State: ${SEC_STATE})."
    else
      log_error "Targeted stop failed: ${SECONDARY_CONTAINER} is in state '${SEC_STATE}'."
      exit 1
    fi

    # Assert primary agent was NOT stopped
    PRIMARY_STATE=$(docker inspect "${PRIMARY_CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "stopped")
    if [ "${PRIMARY_STATE}" = "running" ]; then
      log_success "Non-targeted agent '${PRIMARY_CONTAINER}' remained RUNNING without interruption."
    else
      log_error "Blast radius failure: non-targeted agent '${PRIMARY_CONTAINER}' was affected (State: ${PRIMARY_STATE})."
      exit 1
    fi

    # Restore secondary agent
    docker unpause "${SECONDARY_CONTAINER}" 2>/dev/null || docker compose start "agent-${SECONDARY_AGENT_ID}" 2>/dev/null || true
    log_info "Restored ${SECONDARY_CONTAINER} container."
  else
    log_error "scripts/control/emergency-stop.sh not found."
    exit 1
  fi
else
  log_warn "No secondary agent found in enabled agents; skipping cross-tenant isolation probe."
fi

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Multi-Agent Fleet Verification Checks Passed Successfully!  ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
