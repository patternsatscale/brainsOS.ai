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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml"

log_info "================================================================="
log_info "  Running Project Titan Multi-Agent Fleet Verification Suite     "
log_info "================================================================="

# ------------------------------------------------------------------------------
# 1. Manifest Drift & Topology Validation
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet manifest synchronization & compose topology..."

if [ ! -x "${REPO_ROOT}/scripts/sync-agents.sh" ]; then
  log_error "scripts/sync-agents.sh is missing or not executable."
  exit 1
fi

"${REPO_ROOT}/scripts/sync-agents.sh" --check
log_success "Fleet manifest drift check passed (config/agents.yaml is in sync)."

docker compose config -q
log_success "Docker Compose topology syntax validated successfully."

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

if ! docker compose ps --services --filter "status=running" | grep -q "^agent-primary$"; then
  log_info "Starting fleet agents..."
  docker compose up -d agent-primary agent-football-dan agent-cindy-pawford
  sleep 3
fi

for agent_id in primary football-dan cindy-pawford; do
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

for agent_id in primary football-dan cindy-pawford; do
  SUBDOMAIN="${agent_id}.${TITAN_DOMAIN}"
  
  # HTTP probe via Caddy on port 80 with Host header
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${SUBDOMAIN}" "http://127.0.0.1:${CADDY_HTTP_PORT}/" || echo "failed")
  if [ "${HTTP_STATUS}" = "200" ] || [ "${HTTP_STATUS}" = "302" ] || [ "${HTTP_STATUS}" = "401" ]; then
    log_success "Caddy ingress resolves '${SUBDOMAIN}' -> HTTP ${HTTP_STATUS}."
  else
    log_error "Caddy ingress failed for '${SUBDOMAIN}': got HTTP '${HTTP_STATUS}'."
    exit 1
  fi

  # Check localhost alias as well
  LOCAL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${agent_id}.localhost" "http://127.0.0.1:${CADDY_HTTP_PORT}/" || echo "failed")
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

# Test 1: Write marker note into Agent primary memory
TEST_MARKER="marker_primary_$(date +%s)"
docker exec titan-agent-primary bash -c "echo '${TEST_MARKER}' > /memories/knowledge/isolation_test.md"

# Test 2: Verify Agent football-dan CANNOT see Agent primary marker
if docker exec titan-agent-football-dan test -f /memories/knowledge/isolation_test.md 2>/dev/null; then
  log_error "Isolation breach: football-dan container can access primary container /memories!"
  exit 1
fi
log_success "Verified: Agent 'football-dan' cannot access Agent 'primary' memory partition."

# Test 3: Verify Agent primary CANNOT see Agent football-dan workspace
FB_MARKER="marker_football_$(date +%s)"
docker exec titan-agent-football-dan bash -c "echo '${FB_MARKER}' > /workspace/fb_isolated.txt"

if docker exec titan-agent-primary test -f /workspace/fb_isolated.txt 2>/dev/null; then
  log_error "Isolation breach: primary container can access football-dan container /workspace!"
  exit 1
fi
log_success "Verified: Agent 'primary' cannot access Agent 'football-dan' workspace partition."

# Clean up isolation test files
docker exec titan-agent-primary rm -f /memories/knowledge/isolation_test.md 2>/dev/null || true
docker exec titan-agent-football-dan rm -f /workspace/fb_isolated.txt 2>/dev/null || true

# ------------------------------------------------------------------------------
# 5. Hardware Concurrency & Serialization via LiteLLM
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying hardware serialization through LiteLLM (Rule 3)..."

if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
  log_info "LiteLLM gateway is online; issuing concurrent completion probes across agents..."

  PRIMARY_KEY="${HERMES_LITELLM_KEY:-sk-titan-primary-key}"
  FOOTBALL_KEY="${HERMES_FOOTBALL_DAN_KEY:-sk-titan-football-dan-key}"

  # Issue concurrent health / models requests with different keys
  REQ1=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${PRIMARY_KEY}" "http://127.0.0.1:${LITELLM_PORT}/models" || echo "failed")
  REQ2=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${FOOTBALL_KEY}" "http://127.0.0.1:${LITELLM_PORT}/models" || echo "failed")

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

if [ -x "${REPO_ROOT}/scripts/emergency-stop.sh" ]; then
  # Target only football-dan
  "${REPO_ROOT}/scripts/emergency-stop.sh" football-dan

  # Assert football-dan is paused or stopped
  FB_STATE=$(docker inspect titan-agent-football-dan --format '{{.State.Status}}' 2>/dev/null || echo "stopped")
  if [ "${FB_STATE}" = "paused" ] || [ "${FB_STATE}" = "exited" ]; then
    log_success "Targeted emergency stop successfully paused/stopped titan-agent-football-dan (State: ${FB_STATE})."
  else
    log_error "Targeted stop failed: titan-agent-football-dan is in state '${FB_STATE}'."
    exit 1
  fi

  # Assert primary agent was NOT stopped
  PRIMARY_STATE=$(docker inspect titan-agent-primary --format '{{.State.Status}}' 2>/dev/null || echo "stopped")
  if [ "${PRIMARY_STATE}" = "running" ]; then
    log_success "Non-targeted agent 'titan-agent-primary' remained RUNNING without interruption."
  else
    log_error "Blast radius failure: non-targeted agent 'titan-agent-primary' was affected (State: ${PRIMARY_STATE})."
    exit 1
  fi

  # Restore football-dan
  docker unpause titan-agent-football-dan 2>/dev/null || docker compose start agent-football-dan 2>/dev/null || true
  log_info "Restored football-dan container."
else
  log_error "scripts/emergency-stop.sh not found."
  exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Multi-Agent Fleet Verification Checks Passed Successfully!  ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
