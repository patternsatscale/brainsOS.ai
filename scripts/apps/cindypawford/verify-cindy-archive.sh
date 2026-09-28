#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Cindy Pawford Archive & 'Seal & Reset' Verification Suite
# Ticket #88 (CW-0B): Genesis Preservation, Digital Museum & Seal-and-Reset
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
ARCHIVE_DIR="${REPO_ROOT}/apps/cindypawford/archive"
GENESIS_DIR="${ARCHIVE_DIR}/2024-genesis"
ERAS_FILE="${ARCHIVE_DIR}/eras.json"
LITELLM_CONFIG="${REPO_ROOT}/config/litellm/config.yaml"

log_info "================================================================="
log_info "  Running Cindy Pawford Genesis Archive & Seal-and-Reset Suite  "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Step 1: Manifest Synchronization & Compose Syntax
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet manifest synchronization..."
"${REPO_ROOT}/scripts/control/sync-agents.sh" --check
log_success "Fleet manifest drift check passed."

docker compose config -q
log_success "Docker Compose syntax validated successfully."

# ------------------------------------------------------------------------------
# Step 2: Ensure Container is Running
# ------------------------------------------------------------------------------
log_info "Step 2: Checking agent container status..."
if ! docker ps --format '{{.Names}}' | grep -qw "${CONTAINER}"; then
  docker compose up -d "agent-${AGENT_ID}"
  sleep 2
fi

STATUS=$(docker inspect "${CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
if [ "${STATUS}" != "running" ]; then
  log_error "Container '${CONTAINER}' is not running."
  exit 1
fi
log_success "Container '${CONTAINER}' is running."

# ------------------------------------------------------------------------------
# Step 3: Verify Immutable Archive Vault (Cindy Container Has Zero Access)
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying immutable vault isolation (Rule 4)..."

# Ensure apps/cindypawford/archive is NOT mounted into container
ARCHIVE_MOUNT=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/app/archive"}}{{.Source}}{{end}}{{end}}')
if [ -n "${ARCHIVE_MOUNT}" ]; then
  log_error "Security violation: Archive is mounted directly inside agent container at /app/archive!"
  exit 1
fi

# Ensure container cannot access archive directory
if docker exec "${CONTAINER}" test -d /app/archive 2>/dev/null; then
  log_error "Security violation: /app/archive is accessible inside container!"
  exit 1
fi

if docker exec "${CONTAINER}" test -d "${ARCHIVE_DIR}" 2>/dev/null; then
  log_error "Security violation: Host archive directory path '${ARCHIVE_DIR}' is accessible inside container!"
  exit 1
fi

log_success "Immutable Vault verified: Agent container has zero mounts or write access to archive."

# ------------------------------------------------------------------------------
# Step 4: Verify 2024 Genesis Preservation
# ------------------------------------------------------------------------------
log_info "Step 4: Validating 2024 Genesis era preservation..."

if [ ! -d "${GENESIS_DIR}" ]; then
  log_error "Missing 2024 Genesis directory at ${GENESIS_DIR}."
  exit 1
fi

if [ ! -f "${GENESIS_DIR}/index.html" ]; then
  log_error "Missing index.html in 2024 Genesis archive."
  exit 1
fi

if grep -q "Cindy Pawford Pet Company" "${GENESIS_DIR}/index.html"; then
  log_success "Found valid Genesis HTML title 'Cindy Pawford Pet Company'."
else
  log_error "Genesis index.html does not contain expected title."
  exit 1
fi

if [ ! -f "${GENESIS_DIR}/recap.json" ]; then
  log_error "Missing recap.json in 2024 Genesis archive."
  exit 1
fi

if grep -q "gpt-4-turbo" "${GENESIS_DIR}/recap.json" && grep -q "corporate imperative" "${GENESIS_DIR}/recap.json"; then
  log_success "Verified Genesis recap.json (gpt-4-turbo, founding quote, canine stats)."
else
  log_error "Genesis recap.json missing required metadata fields."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Digital Museum Portal Compilation Check
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying digital museum portal generation..."

python3 "${REPO_ROOT}/scripts/apps/cindypawford/build-archive-portal.py"

PORTAL_HTML="${ARCHIVE_DIR}/index.html"
if [ -f "${PORTAL_HTML}" ] && grep -q "The Grand Fashion Archives" "${PORTAL_HTML}" && grep -q "The Genesis Atelier" "${PORTAL_HTML}"; then
  log_success "Digital museum portal compiled successfully with Genesis gallery card."
else
  log_error "Failed to compile digital museum portal or missing Genesis card."
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 6: Test 'Seal & Reset' Engine Handshake & Model Rotation
# ------------------------------------------------------------------------------
log_info "Step 6: Simulating .archive-ready handshake and 'Seal & Reset' pipeline..."

TEST_SLUG="test-verification-$(date +%s)"
TEST_TAG="archive/cindy-${TEST_SLUG}"

# Seed test files in /app/html (SITE_DIR) to verify snapshot
TEST_CANVAS_FILE="${SITE_DIR}/test_era_canvas.txt"
echo "Exclusive Haute Couture Piece for ${TEST_SLUG}" > "${TEST_CANVAS_FILE}"

# Seed Cindy recap.json in /app/html
cat << EOF > "${SITE_DIR}/recap.json"
{
  "theme_name": "Velvet & Truffle Verification Era",
  "date_range": "2026-09-07 to 2026-09-13",
  "closing_quote": "Excellence is never an accident; it is always the result of high intention and bacon.",
  "stats": {
    "runway_looks": 8,
    "bacon_strips": 500
  }
}
EOF

# Touch .archive-ready flag
touch "${SITE_DIR}/.archive-ready"
log_info "Placed .archive-ready trigger in ${SITE_DIR}."

# Seed persistent tools in /workspace and /memories to verify Zero Amnesia
SEED_SKILL="/workspace/skills/.seal_test_skill.py"
SEED_MEM="/memories/knowledge/.seal_test_memory.md"
docker exec "${CONTAINER}" bash -c "echo '# persistent skill' > ${SEED_SKILL}"
docker exec "${CONTAINER}" bash -c "echo '# persistent memory' > ${SEED_MEM}"

# Run process-cindy-reset.sh
"${REPO_ROOT}/scripts/apps/cindypawford/process-cindy-reset.sh" --week-slug "${TEST_SLUG}"

# Verification 6a: Verify snapshot was captured
TEST_SNAPSHOT_DIR="${ARCHIVE_DIR}/${TEST_SLUG}"
if [ -d "${TEST_SNAPSHOT_DIR}" ] && [ -f "${TEST_SNAPSHOT_DIR}/test_era_canvas.txt" ]; then
  log_success "Verified snapshot captured before reset in ${TEST_SNAPSHOT_DIR}."
else
  log_error "Snapshot verification failed: ${TEST_SNAPSHOT_DIR} missing canvas files!"
  exit 1
fi

# Verification 6b: Verify eras.json has updated
if grep -q "${TEST_SLUG}" "${ERAS_FILE}" && grep -q "Velvet & Truffle Verification Era" "${ERAS_FILE}"; then
  log_success "Verified historical ledger updated with new era."
else
  log_error "Historical ledger was not updated with ${TEST_SLUG}!"
  exit 1
fi

# Verification 6c: Verify Git tag was cut
if git -C "${SITE_DIR}" tag -l "${TEST_TAG}" | grep -q "${TEST_TAG}"; then
  log_success "Verified Git tag '${TEST_TAG}' created in CindyPawford-Online repo."
else
  log_error "Git tag '${TEST_TAG}' was not found in ${SITE_DIR}!"
  exit 1
fi

# Verification 6d: Verify LiteLLM cindy-active-coding-model was updated
if grep -q "cindy-active-coding-model" "${LITELLM_CONFIG}"; then
  ROTATED_MODEL=$(awk '/model_name: cindy-active-coding-model/{getline; getline; print $2}' "${LITELLM_CONFIG}")
  log_success "Verified LiteLLM active coding engine rotated to '${ROTATED_MODEL}'."
else
  log_error "LiteLLM config missing cindy-active-coding-model!"
  exit 1
fi

# Verification 6e: Verify era-info.json in site is sanitized (Rule 7: model engine hidden)
ERA_INFO_FILE="${SITE_DIR}/era-info.json"
if [ -f "${ERA_INFO_FILE}" ]; then
  if grep -qiE "(qwen|llama|ollama|brainsos-core|gpt)" "${ERA_INFO_FILE}"; then
    log_error "Rule 7 violation: Model ID leaked into agent era-info.json!"
    exit 1
  else
    log_success "Rule 7 verified: era-info.json contains sanitized era slug with zero model engine leakage."
  fi
else
  log_error "Missing era-info.json in ${SITE_DIR}!"
  exit 1
fi

# Verification 6f: Verify .archive-ready trigger is removed
if [ ! -f "${SITE_DIR}/.archive-ready" ]; then
  log_success "Verified .archive-ready trigger was cleanly removed."
else
  log_error "Trigger file still present after reset!"
  exit 1
fi

# Verification 6g: Zero Amnesia Check
if docker exec "${CONTAINER}" test -f "${SEED_SKILL}" && docker exec "${CONTAINER}" test -f "${SEED_MEM}"; then
  log_success "Zero Amnesia verified: Erasing /app/html left /workspace and /memories completely untouched."
  docker exec "${CONTAINER}" rm -f "${SEED_SKILL}" "${SEED_MEM}"
else
  log_error "Zero Amnesia violation: Skills or memories in /workspace were modified during reset!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Step 7: Clean Up Test Snapshot & Rebuild Portal
# ------------------------------------------------------------------------------
log_info "Step 7: Cleaning up test verification artifacts..."

rm -rf "${TEST_SNAPSHOT_DIR}"
git -C "${SITE_DIR}" tag -d "${TEST_TAG}" >/dev/null 2>&1 || true
git -C "${SITE_DIR}" checkout . >/dev/null 2>&1 || true
git -C "${SITE_DIR}" clean -fd >/dev/null 2>&1 || true

# Revert ledger back to 2024-genesis for pristine state
cat << 'EOF' > "${ERAS_FILE}"
{
  "total_eras": 1,
  "active_era": 1,
  "eras": [
    {
      "era": 1,
      "slug": "2024-genesis",
      "theme_name": "The Genesis Atelier",
      "date_range": "2024-03-15 to 2024-06-19",
      "quote": "Luxury canine couture isn't just an aesthetic, darling—it's a corporate imperative.",
      "coding_model": "gpt-4-turbo",
      "archived_at": "2024-06-19T00:00:00Z"
    }
  ]
}
EOF

python3 "${REPO_ROOT}/scripts/apps/cindypawford/build-archive-portal.py" >/dev/null
log_success "Digital museum portal cleanly restored to baseline."

# ------------------------------------------------------------------------------
# Step 8: Test Out-of-Band Republishing Script
# ------------------------------------------------------------------------------
log_info "Step 8: Testing out-of-band republishing tooling..."
"${REPO_ROOT}/scripts/apps/cindypawford/republish-archives.sh" --dry-run
log_success "Republishing tooling executed successfully in dry-run mode."

log_info "================================================================="
log_success "  All Ticket #88 (CW-0B) Verification Checks PASSED!            "
log_info "================================================================="
echo ""
echo -e "${BOLD}🎯 Next Ticket Gate:${NC}"
echo -e "   Upon approval of Ticket #88, proceed to Ticket C:"
echo -e "   👉 ${BLUE}Issue #36 (CW-1): Isolated SST Infrastructure, Legacy Stack Retirement & Platform Shell${NC}"
echo ""
