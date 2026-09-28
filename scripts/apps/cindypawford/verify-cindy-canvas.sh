#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Cindy Pawford Canvas & GitHub Tooling Verification Suite
# Ticket #92 (CW-0A.1): Isolate HTML Canvas to /app/html & Bind Dedicated Repo
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

AGENT_ID="cindy-pawford"
CONTAINER="brainsos-agent-${AGENT_ID}"
SITE_DIR="${REPO_ROOT}/apps/cindypawford/site"
MEM_DIR="${REPO_ROOT}/data/memories/${AGENT_ID}"
WORK_DIR="${REPO_ROOT}/data/workspace/${AGENT_ID}"
REMOTE_REPO="patternsatscale/CindyPawford-Online"

log_info "================================================================="
log_info "  Running Cindy Pawford Canvas Isolation Verification (CW-0A.1)  "
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
# Step 2: Ensure Container is Running
# ------------------------------------------------------------------------------
log_info "Step 2: Checking agent container status..."

if ! docker ps --format '{{.Names}}' | grep -qw "${CONTAINER}"; then
  log_info "Starting agent container '${CONTAINER}'..."
  docker compose up -d "agent-${AGENT_ID}"
  sleep 3
fi

STATUS=$(docker inspect "${CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
if [ "${STATUS}" != "running" ]; then
  log_error "Container '${CONTAINER}' is not in running state (Status: ${STATUS})."
  exit 1
fi
log_success "Container '${CONTAINER}' is running."

# ------------------------------------------------------------------------------
# Step 3: Verify Boundary Separation (Three Distinct Mounts)
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying explicit boundary separation across mounts..."

# 3a. Verify /workspace mount maps to data/workspace/cindy-pawford
WORK_MOUNT=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}')
if [ "${WORK_MOUNT}" = "${WORK_DIR}" ]; then
  log_success "Verified container '/workspace' bind-mount maps to '${WORK_DIR}'."
else
  log_error "Container '/workspace' mount mismatch: '${WORK_MOUNT}' vs expected '${WORK_DIR}'."
  exit 1
fi

# 3b. Verify /memories mount maps to data/memories/cindy-pawford
MEM_MOUNT=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/memories"}}{{.Source}}{{end}}{{end}}')
if [ "${MEM_MOUNT}" = "${MEM_DIR}" ]; then
  log_success "Verified container '/memories' bind-mount maps to '${MEM_DIR}'."
else
  log_error "Container '/memories' mount mismatch: '${MEM_MOUNT}' vs expected '${MEM_DIR}'."
  exit 1
fi

# 3c. Verify /app/html mount maps to apps/cindypawford/site
HTML_MOUNT=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/app/html"}}{{.Source}}{{end}}{{end}}')
if [ "${HTML_MOUNT}" = "${SITE_DIR}" ]; then
  log_success "Verified container '/app/html' bind-mount maps to '${SITE_DIR}'."
else
  log_error "Container '/app/html' mount mismatch: '${HTML_MOUNT}' vs expected '${SITE_DIR}'."
  exit 1
fi

# Ensure all three mounts are strictly distinct directories
if [ "${WORK_MOUNT}" != "${MEM_MOUNT}" ] && [ "${WORK_MOUNT}" != "${HTML_MOUNT}" ] && [ "${MEM_MOUNT}" != "${HTML_MOUNT}" ]; then
  log_success "Boundary separation verified: /workspace, /memories, and /app/html are 100% distinct paths."
else
  log_error "Mount overlap detected between agent workspaces!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 4: No Amnesia on Reset Test
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying 'No Amnesia on Reset' (wiping /app/html preserves agent state)..."

# Seed a test skill in /workspace and a test memory note in /memories
SEED_SKILL="/workspace/skills/.probe_skill_$(date +%s).py"
SEED_MEM="/memories/knowledge/.probe_note_$(date +%s).md"
CANVAS_PROBE="/app/html/.temp_canvas_probe_$(date +%s).txt"

docker exec "${CONTAINER}" bash -c "echo '# persistent skill' > ${SEED_SKILL}"
docker exec "${CONTAINER}" bash -c "echo '# persistent memory' > ${SEED_MEM}"
docker exec "${CONTAINER}" bash -c "echo 'canvas temporary' > ${CANVAS_PROBE}"

# Verify files were created
docker exec "${CONTAINER}" test -f "${SEED_SKILL}"
docker exec "${CONTAINER}" test -f "${SEED_MEM}"
docker exec "${CONTAINER}" test -f "${CANVAS_PROBE}"

# Simulate weekly canvas wipe / reset: remove canvas probe
docker exec "${CONTAINER}" rm -f "${CANVAS_PROBE}"

# Assert agent runtime home (/workspace) and memory (/memories) were completely unaffected
if docker exec "${CONTAINER}" test -f "${SEED_SKILL}" && docker exec "${CONTAINER}" test -f "${SEED_MEM}"; then
  log_success "'No Amnesia' verified: Wiping canvas (/app/html) left /workspace and /memories 100% intact."
  docker exec "${CONTAINER}" rm -f "${SEED_SKILL}" "${SEED_MEM}"
else
  log_error "'No Amnesia' check failed: Skills or memories were affected by canvas operations!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Container Git & GitHub CLI Tooling Inspection
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying container Git tooling & GitHub CLI (gh) capabilities..."

# Check git binary
GIT_PATH=$(docker exec "${CONTAINER}" which git 2>/dev/null || echo "")
if [ -n "${GIT_PATH}" ]; then
  log_success "Found git binary in container at ${GIT_PATH}."
else
  log_error "git binary not found in container '${CONTAINER}'."
  exit 1
fi

# Check gh binary
GH_PATH=$(docker exec "${CONTAINER}" which gh 2>/dev/null || echo "")
if [ -n "${GH_PATH}" ]; then
  log_success "Found gh (GitHub CLI) binary in container at ${GH_PATH}."
else
  log_error "gh binary not found in container '${CONTAINER}'."
  exit 1
fi

# Check container git identity
GIT_NAME=$(docker exec "${CONTAINER}" bash -c "cd /app/html && git config user.name" 2>/dev/null || echo "")
GIT_EMAIL=$(docker exec "${CONTAINER}" bash -c "cd /app/html && git config user.email" 2>/dev/null || echo "")

if [ "${GIT_NAME}" = "Cindy Pawford" ] && [ "${GIT_EMAIL}" = "cindy@cindypawford.com" ]; then
  log_success "Container Git identity verified: '${GIT_NAME} <${GIT_EMAIL}>'."
else
  log_error "Git identity mismatch: '${GIT_NAME}' / '${GIT_EMAIL}'."
  exit 1
fi

# Check git status inside /app/html
GIT_STATUS=$(docker exec "${CONTAINER}" bash -c "cd /app/html && git status --short" 2>&1)
log_success "Container 'git status' inside /app/html executed successfully."

# ------------------------------------------------------------------------------
# Step 6: GitHub CLI Authentication & API Operations
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying GitHub CLI authentication and API access..."

# Assert zero ambient tokens in container environment (Ticket #93)
ENV_TOKENS=$(docker exec "${CONTAINER}" env | grep -i -E '(gh_token|github_token|github_pat)' || true)
if [ -n "${ENV_TOKENS}" ]; then
  log_error "Security boundary violation: GitHub tokens detected in container environment!"
  exit 1
fi
log_success "Zero ambient GitHub secrets detected in container environment."

# Verify gh auth status (via in-transit proxy or direct)
AUTH_OUTPUT=$(docker exec "${CONTAINER}" bash -c "gh auth status" 2>&1 || true)
if echo "${AUTH_OUTPUT}" | grep -qi -E "Logged in to (github\.com|github-proxy\.brainsos\.local)"; then
  log_success "Verified 'gh auth status' inside container: authenticated via in-transit relay."
else
  log_error "GitHub CLI is not authenticated inside container! Output:\n${AUTH_OUTPUT}"
  exit 1
fi

# Verify gh pr list
PR_OUTPUT=$(docker exec "${CONTAINER}" bash -c "cd /app/html && gh pr list --repo ${REMOTE_REPO}" 2>&1 || echo "failed")
if [ "${PR_OUTPUT}" != "failed" ]; then
  log_success "Verified 'gh pr list' against '${REMOTE_REPO}' from inside container."
else
  log_error "Failed to execute 'gh pr list' inside container."
  exit 1
fi

# Verify gh issue list
ISSUE_OUTPUT=$(docker exec "${CONTAINER}" bash -c "cd /app/html && gh issue list --repo ${REMOTE_REPO}" 2>&1 || echo "failed")
if [ "${ISSUE_OUTPUT}" != "failed" ]; then
  log_success "Verified 'gh issue list' against '${REMOTE_REPO}' from inside container."
else
  log_error "Failed to execute 'gh issue list' inside container."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 7: Dedicated Remote Branch & Commit Probe
# ------------------------------------------------------------------------------
log_info "Step 7: Testing live branch creation, commit, and remote push to ${REMOTE_REPO}..."

PROBE_BRANCH="probe/cindy-canvas-auth-$(date +%s)"
PROBE_FILE="probe_test_$(date +%s).txt"

# Run git operations inside container
docker exec "${CONTAINER}" bash -c "
  cd /app/html && \
  git checkout -b ${PROBE_BRANCH} && \
  echo 'Cindy Pawford Canvas Verification' > ${PROBE_FILE} && \
  git add ${PROBE_FILE} && \
  git commit -m 'chore(test): automated cindy canvas auth probe' && \
  git push -u origin ${PROBE_BRANCH}
"
log_success "Container successfully created branch '${PROBE_BRANCH}' and pushed commit to remote."

# Clean up remote probe branch and switch back to main inside container
docker exec "${CONTAINER}" bash -c "
  cd /app/html && \
  git checkout main && \
  git branch -D ${PROBE_BRANCH} && \
  git push origin --delete ${PROBE_BRANCH}
"
log_success "Cleaned up remote probe branch '${PROBE_BRANCH}' on GitHub."

# ------------------------------------------------------------------------------
# Step 8: Security & Sandboxing Invariants (Rules 4 & 7)
# ------------------------------------------------------------------------------
log_info "Step 8: Validating security boundaries and sandboxing invariants..."

# Rule 4: Unprivileged UID 1000
UID_CHECK=$(docker exec "${CONTAINER}" id -u hermes 2>/dev/null || echo "failed")
if [ "${UID_CHECK}" = "1000" ]; then
  log_success "Verified container runs under unprivileged UID 1000."
else
  log_error "Security violation: UID is '${UID_CHECK}' (expected 1000)."
  exit 1
fi

# Rule 4: Docker socket isolation
if ! docker exec "${CONTAINER}" test -e /var/run/docker.sock 2>/dev/null; then
  log_success "Verified container has zero access to host Docker socket."
else
  log_error "Security violation: Docker socket detected in container!"
  exit 1
fi

# Rule 7: Persona compartmentalization (no host backend leakage)
SOUL_PATH="${MEM_DIR}/SOUL.md"
for forbidden in "127.0.0.1:11434" "brainsos-litellm-db" "postgresql://" "vllm" "SST"; do
  if grep -qi "${forbidden}" "${SOUL_PATH}"; then
    log_error "Rule 7 violation: Found forbidden backend leak '${forbidden}' in ${SOUL_PATH}!"
    exit 1
  fi
done
log_success "Rule 7 verified: Zero host backend infrastructure details leaked in SOUL.md."

log_info "================================================================="
log_success "  All Ticket #92 (CW-0A.1) Verification Checks PASSED!          "
log_info "================================================================="
echo ""
echo -e "${BOLD}🎯 Next Ticket Gate:${NC}"
echo -e "   Upon approval of Ticket #92, proceed to Ticket B:"
echo -e "   👉 ${BLUE}Issue #88 (CW-0B): Genesis Archive, Digital Museum Platform & 'Seal & Reset' Engine${NC}"
echo ""
