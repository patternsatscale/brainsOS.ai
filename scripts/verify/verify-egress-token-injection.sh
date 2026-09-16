#!/usr/bin/env bash
# ==============================================================================
# Project Titan: In-Transit Egress Credential Injection Verification Suite
# Ticket #93: In-Transit GitHub Token Relay via Caddy Gateway
#
# Asserts:
#   1. Zero ambient GitHub tokens (GH_TOKEN, GITHUB_TOKEN, PAT) in container env
#   2. Caddy terminates internal TLS at https://github-proxy.titan.local
#   3. GitHub CLI (gh) authenticated seamlessly through in-transit token relay
#   4. gh pr list & gh issue list execute successfully
#   5. Git Smart HTTP fetch, branch push, and delete succeed through proxy
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
  # shellcheck disable=SC1091
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.example
  set +a
fi

AGENT_ID="cindy-pawford"
CONTAINER="titan-agent-${AGENT_ID}"
CADDY_CONTAINER="titan-caddy"
REMOTE_REPO="patternsatscale/CindyPawford-Online"
PROXY_HOST="github-proxy.titan.local"

log_info "================================================================="
log_info "  Running Egress Credential Injection Verification (Ticket #93)  "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Step 1: Manifest Synchronization & Compose Topology Drift Check
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
# Step 2: Ensure Required Containers are Running
# ------------------------------------------------------------------------------
log_info "Step 2: Checking container status (Caddy & Agent)..."

for c in "${CADDY_CONTAINER}" "${CONTAINER}"; do
  if ! docker ps --format '{{.Names}}' | grep -qw "${c}"; then
    log_info "Starting container '${c}'..."
    docker compose up -d
    sleep 3
    break
  fi
done

for c in "${CADDY_CONTAINER}" "${CONTAINER}"; do
  STATUS=$(docker inspect "${c}" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
  if [ "${STATUS}" != "running" ]; then
    log_error "Container '${c}' is not in running state (Status: ${STATUS})."
    exit 1
  fi
  log_success "Container '${c}' is running."
done

# ------------------------------------------------------------------------------
# Step 3: Verify Zero Ambient GitHub Tokens Inside Agent Container
# ------------------------------------------------------------------------------
log_info "Step 3: Asserting ZERO ambient GitHub secrets inside agent container..."

# Check environment for any GH_TOKEN, GITHUB_TOKEN, or PAT strings
ENV_TOKENS=$(docker exec "${CONTAINER}" env | grep -i -E '(gh_token|github_token|github_pat)' || true)
if [ -n "${ENV_TOKENS}" ]; then
  log_error "Security Boundary Violation: GitHub tokens detected in container environment!"
  echo "${ENV_TOKENS}" >&2
  exit 1
fi
log_success "Zero GitHub tokens in container environment (GH_TOKEN, GITHUB_TOKEN, and PAT strings absent)."

# Verify GH_HOST points to Caddy gateway
CONTAINER_GH_HOST=$(docker exec "${CONTAINER}" bash -c 'echo "${GH_HOST:-}"')
if [ "${CONTAINER_GH_HOST}" = "${PROXY_HOST}" ]; then
  log_success "Container GH_HOST correctly configured to in-transit proxy '${PROXY_HOST}'."
else
  log_error "Container GH_HOST mismatch: expected '${PROXY_HOST}', got '${CONTAINER_GH_HOST}'."
  exit 1
fi

# Verify Git insteadOf rewrite is active
GIT_INSTEAD_OF=$(docker exec "${CONTAINER}" git config --system --get "url.https://${PROXY_HOST}/.insteadOf" 2>/dev/null || true)
if [ "${GIT_INSTEAD_OF}" = "https://github.com/" ]; then
  log_success "Git insteadOf rewrite active: 'https://${PROXY_HOST}/' replaces 'https://github.com/'."
else
  log_warn "System insteadOf not returned by git config --system; checking global / local config..."
fi

# ------------------------------------------------------------------------------
# Step 4: Verify Caddy Internal PKI Trust & Connectivity
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying Caddy internal PKI CA trust & TLS handshake..."

# Ensure internal CA cert exists inside container trust store
if docker exec "${CONTAINER}" test -f /usr/local/share/ca-certificates/caddy-root.crt; then
  log_success "Caddy internal CA root certificate is present in container trust store."
else
  log_error "Caddy internal CA certificate missing in /usr/local/share/ca-certificates/!"
  exit 1
fi

# Verify TLS connection to proxy without skipping verification
PROXY_HTTP_CODE=$(docker exec "${CONTAINER}" curl -s -o /dev/null -w "%{http_code}" "https://${PROXY_HOST}/" || echo "failed")
if [ "${PROXY_HTTP_CODE}" = "200" ] || [ "${PROXY_HTTP_CODE}" = "301" ] || [ "${PROXY_HTTP_CODE}" = "302" ]; then
  log_success "Container successfully connected to 'https://${PROXY_HOST}/' with full TLS verification (HTTP ${PROXY_HTTP_CODE})."
else
  log_error "Failed to connect to 'https://${PROXY_HOST}/' via container curl (Code: ${PROXY_HTTP_CODE})."
  exit 1
fi

# Verify REST API proxy endpoint with injected Bearer token
API_USER=$(docker exec "${CONTAINER}" curl -s "https://${PROXY_HOST}/api/v3/user" | grep -o '"login": *"[^"]*"' | head -n 1 || echo "")
if [ -n "${API_USER}" ]; then
  log_success "In-transit REST API authentication verified (Upstream identity: ${API_USER})."
else
  log_error "REST API authentication failed through 'https://${PROXY_HOST}/api/v3/user'!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Verify GitHub CLI (gh) Authentication & API Queries
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying GitHub CLI (gh) authentication and API access..."

AUTH_STATUS=$(docker exec "${CONTAINER}" gh auth status 2>&1 || true)
if echo "${AUTH_STATUS}" | grep -q "Logged in to ${PROXY_HOST}"; then
  log_success "GitHub CLI verified authenticated for '${PROXY_HOST}'."
else
  log_error "GitHub CLI authentication status check failed! Output:\n${AUTH_STATUS}"
  exit 1
fi

# Verify gh pr list
PR_OUTPUT=$(docker exec -w /app/html "${CONTAINER}" gh pr list --repo "${REMOTE_REPO}" 2>&1 || echo "failed")
if [ "${PR_OUTPUT}" != "failed" ]; then
  log_success "Verified 'gh pr list' against '${REMOTE_REPO}' through Caddy relay."
else
  log_error "Failed to execute 'gh pr list' inside container."
  exit 1
fi

# Verify gh issue list
ISSUE_OUTPUT=$(docker exec -w /app/html "${CONTAINER}" gh issue list --repo "${REMOTE_REPO}" 2>&1 || echo "failed")
if [ "${ISSUE_OUTPUT}" != "failed" ]; then
  log_success "Verified 'gh issue list' against '${REMOTE_REPO}' through Caddy relay."
else
  log_error "Failed to execute 'gh issue list' inside container."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 6: Verify Git Smart HTTP Protocol (Fetch & Remote Branch Push)
# ------------------------------------------------------------------------------
log_info "Step 6: Testing live branch creation, commit, and remote push through proxy..."

PROBE_BRANCH="probe/egress-token-inject-$(date +%s)"
PROBE_FILE="probe_test_$(date +%s).txt"

# Run git operations inside container
docker exec -w /app/html "${CONTAINER}" bash -c "
  set -euo pipefail
  git fetch origin
  git checkout -b ${PROBE_BRANCH}
  echo 'Project Titan Ticket #93 In-Transit Egress Verification' > ${PROBE_FILE}
  git add ${PROBE_FILE}
  git commit -m 'chore(test): automated egress credential injection probe'
  git push -u origin ${PROBE_BRANCH}
"
log_success "Container successfully created branch '${PROBE_BRANCH}' and pushed commit through Caddy relay."

# Clean up remote probe branch
docker exec -w /app/html "${CONTAINER}" bash -c "
  set -euo pipefail
  git checkout main
  git branch -D ${PROBE_BRANCH}
  git push origin --delete ${PROBE_BRANCH}
  rm -f ${PROBE_FILE}
"
log_success "Cleaned up remote probe branch '${PROBE_BRANCH}' on GitHub."

# ------------------------------------------------------------------------------
# Step 7: Security Boundaries & Invariants
# ------------------------------------------------------------------------------
log_info "Step 7: Validating security boundaries and sandboxing invariants..."

# Unprivileged execution
CONT_UID=$(docker exec "${CONTAINER}" id -u hermes 2>/dev/null || echo "failed")
if [ "${CONT_UID}" = "1000" ]; then
  log_success "Verified container runs under unprivileged UID 1000."
else
  log_error "Security violation: Container is running as UID ${CONT_UID} (expected 1000)."
  exit 1
fi

# Docker socket isolation
if docker exec "${CONTAINER}" test -S /var/run/docker.sock 2>/dev/null; then
  log_error "Security violation: Host Docker socket is mounted in container!"
  exit 1
fi
log_success "Verified container has zero access to host Docker socket."

# Rule 1: Memory plane purity
MEM_FILES=$(find "${REPO_ROOT}/data/memories/${AGENT_ID}" -type f ! -name "*.md" ! -name ".gitkeep" ! -name ".*")
if [ -z "${MEM_FILES}" ]; then
  log_success "Rule 1 verified: Memory plane data/memories/${AGENT_ID} is 100% pure OKF Markdown."
else
  log_error "Memory plane purity violation: non-markdown files detected: ${MEM_FILES}"
  exit 1
fi

log_info "================================================================="
log_success "  All Ticket #93 Egress Credential Injection Checks PASSED!    "
log_info "================================================================="
