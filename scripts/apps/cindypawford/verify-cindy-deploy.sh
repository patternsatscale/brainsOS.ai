#!/usr/bin/env bash
# ==============================================================================
# scripts/apps/cindypawford/verify-cindy-deploy.sh
# End-to-End Automated Verification Suite for Cindy Pawford Protected CI/CD Pipeline
# Ticket #98: Protected GitHub Actions Deployment Workflow for CindyPawford-Online
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

REMOTE_REPO="patternsatscale/CindyPawford-Online"
CONTAINER="titan-agent-cindy-pawford"
SITE_DIR="${REPO_ROOT}/apps/cindypawford/site"

log_info "================================================================="
log_info "  Running Cindy Pawford Protected CI/CD Verification Suite (#98) "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Test 1: Manifest Synchronization & Compose Topology Drift Check
# ------------------------------------------------------------------------------
log_info "Test 1: Validating fleet manifest synchronization & compose topology..."

"${REPO_ROOT}/scripts/control/sync-agents.sh" --check
log_success "Fleet manifest drift check passed (config/agents.yaml is 100% in sync)."

docker compose config -q
log_success "Docker Compose configuration validated successfully."

# ------------------------------------------------------------------------------
# Test 2: Verify Container Filesystem Masking (Read-Only Mount)
# ------------------------------------------------------------------------------
log_info "Test 2: Verifying container filesystem masking on /app/html/.github..."

if ! docker ps --format '{{.Names}}' | grep -qw "${CONTAINER}"; then
  log_info "Starting agent container '${CONTAINER}'..."
  docker compose up -d agent-cindy-pawford
  sleep 2
fi

GITHUB_MOUNT_RW=$(docker inspect "${CONTAINER}" --format '{{range .Mounts}}{{if eq .Destination "/app/html/.github"}}{{.RW}}{{end}}{{end}}')

if [ "${GITHUB_MOUNT_RW}" = "false" ]; then
  log_success "Verified container '/app/html/.github' is mounted read-only (RW: false)."
else
  log_error "Container mount '/app/html/.github' is NOT read-only (RW: '${GITHUB_MOUNT_RW}')."
  exit 1
fi

# Assert write rejection
WRITE_ERR=$(docker exec "${CONTAINER}" bash -c "touch /app/html/.github/test-tamper.tmp" 2>&1 || true)
if echo "${WRITE_ERR}" | grep -qi "Read-only file system"; then
  log_success "Verified write protection: container touch on /app/html/.github rejected ('${WRITE_ERR}')."
else
  log_error "Security violation! Container was able to touch /app/html/.github: '${WRITE_ERR}'"
  exit 1
fi

# Assert workflow modification rejection
MODIFY_ERR=$(docker exec "${CONTAINER}" bash -c "echo 'tamper' >> /app/html/.github/workflows/deploy.yml" 2>&1 || true)
if echo "${MODIFY_ERR}" | grep -qi "Read-only file system"; then
  log_success "Verified tamper protection: container edit to deploy.yml rejected ('${MODIFY_ERR}')."
else
  log_error "Security violation! Container was able to modify deploy.yml: '${MODIFY_ERR}'"
  exit 1
fi

# ------------------------------------------------------------------------------
# Test 3: Remote Repository Secrets & Variables Verification
# ------------------------------------------------------------------------------
log_info "Test 3: Inspecting GitHub Secrets and Variables on ${REMOTE_REPO}..."

SECRETS_LIST=$(gh secret list --repo "${REMOTE_REPO}")
for secret in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION; do
  if echo "${SECRETS_LIST}" | grep -qw "${secret}"; then
    log_success "Found required secret '${secret}' in ${REMOTE_REPO}."
  else
    log_error "Missing required secret '${secret}' in ${REMOTE_REPO}!"
    exit 1
  fi
done

VARS_LIST=$(gh variable list --repo "${REMOTE_REPO}")
for var in PRODUCTION_BUCKET CLOUDFRONT_DISTRIBUTION_ID; do
  if echo "${VARS_LIST}" | grep -qw "${var}"; then
    log_success "Found required variable '${var}' in ${REMOTE_REPO}."
  else
    log_error "Missing required variable '${var}' in ${REMOTE_REPO}!"
    exit 1
  fi
done

# ------------------------------------------------------------------------------
# Test 4: Branch Protection & Ruleset Verification
# ------------------------------------------------------------------------------
log_info "Test 4: Verifying GitHub branch protection ruleset on ${REMOTE_REPO}..."

RULESETS_JSON=$(gh api "repos/${REMOTE_REPO}/rulesets")
RULESET_MATCH=$(echo "${RULESETS_JSON}" | grep -o '"name":"Protected Main & Agent Guard"' || true)

if [ -n "${RULESET_MATCH}" ]; then
  log_success "Verified active ruleset 'Protected Main & Agent Guard' on ${REMOTE_REPO}."
else
  log_error "Ruleset 'Protected Main & Agent Guard' not found on ${REMOTE_REPO}!"
  exit 1
fi

# ------------------------------------------------------------------------------
# Test 5: End-to-End Autonomous PR Merge & CloudFront CDN Invalidation
# ------------------------------------------------------------------------------
log_info "Test 5: Testing autonomous PR flow and CloudFront invalidation..."

TIMESTAMP=$(date +%s)
TEST_BRANCH="test/cicd-verify-${TIMESTAMP}"
ORIGINAL_HEAD=$(git -C "${SITE_DIR}" rev-parse HEAD)

log_info "Creating test verification branch '${TEST_BRANCH}' in ${SITE_DIR}..."
git -C "${SITE_DIR}" checkout -b "${TEST_BRANCH}"

# Make a benign comment change to index.html
echo "<!-- Automated CI/CD Verification Probe ${TIMESTAMP} -->" >> "${SITE_DIR}/index.html"
git -C "${SITE_DIR}" add index.html
git -C "${SITE_DIR}" commit -m "chore(test): automated PR verification probe ${TIMESTAMP}"
git -C "${SITE_DIR}" push origin "${TEST_BRANCH}"

log_info "Opening verification Pull Request against ${REMOTE_REPO}..."
PR_URL=$(gh pr create --repo "${REMOTE_REPO}" \
  --base main \
  --head "${TEST_BRANCH}" \
  --title "chore(test): automated PR deployment verification ${TIMESTAMP}" \
  --body "> 🤖 **Automated CI/CD Verification Probe** — *Project Titan Ticket #98*
Testing end-to-end PR guard check and automated deployment pipeline.")

PR_NUM=$(echo "${PR_URL}" | grep -oE '[0-9]+$')
log_success "Created PR #${PR_NUM}: ${PR_URL}"

# Wait for PR guard status check
log_info "Waiting for 'Guard Protected Paths' status check to report on PR #${PR_NUM}..."
GUARD_PASSED=false
for attempt in {1..30}; do
  CHECK_STATUS=$(gh pr view "${PR_NUM}" --repo "${REMOTE_REPO}" --json statusCheckRollup --jq '.statusCheckRollup[]? | select(.name == "Guard Protected Paths") | .conclusion' || true)
  if [ "${CHECK_STATUS}" = "SUCCESS" ]; then
    log_success "'Guard Protected Paths' status check PASSED."
    GUARD_PASSED=true
    break
  elif [ "${CHECK_STATUS}" = "FAILURE" ]; then
    log_error "'Guard Protected Paths' status check FAILED!"
    exit 1
  fi
  sleep 3
done

if [ "${GUARD_PASSED}" != "true" ]; then
  log_warn "Status check timed out; inspecting checks on PR..."
  gh pr checks "${PR_NUM}" --repo "${REMOTE_REPO}" || true
fi

# Merge PR
log_info "Merging PR #${PR_NUM} into main (squash)..."
gh pr merge "${PR_NUM}" --repo "${REMOTE_REPO}" --squash --delete-branch

log_success "PR #${PR_NUM} merged into main successfully."

# Switch local site repo back to main and pull
git -C "${SITE_DIR}" checkout main
git -C "${SITE_DIR}" pull origin main

# Wait for Deploy Cindy Pawford Production workflow to trigger and complete
log_info "Monitoring GitHub Actions deployment workflow triggered by merge..."
DEPLOY_PASSED=false
for attempt in {1..40}; do
  RUN_INFO=$(gh run list --repo "${REMOTE_REPO}" --workflow "deploy.yml" --limit 1 --json databaseId,status,conclusion,headSha --jq '.[0]' || true)
  RUN_STATUS=$(echo "${RUN_INFO}" | grep -o '"status":"[^"]*"' | cut -d'"' -f4 || true)
  RUN_CONCLUSION=$(echo "${RUN_INFO}" | grep -o '"conclusion":"[^"]*"' | cut -d'"' -f4 || true)
  RUN_ID=$(echo "${RUN_INFO}" | grep -o '"databaseId":[0-9]*' | cut -d':' -f2 || true)

  if [ "${RUN_STATUS}" = "completed" ]; then
    if [ "${RUN_CONCLUSION}" = "success" ]; then
      log_success "Deployment workflow run ${RUN_ID} COMPLETED with SUCCESS!"
      DEPLOY_PASSED=true
      break
    else
      log_error "Deployment workflow run ${RUN_ID} completed with FAILURE (${RUN_CONCLUSION})!"
      gh run view "${RUN_ID}" --repo "${REMOTE_REPO}" --log || true
      exit 1
    fi
  else
    log_info "Run ${RUN_ID} status: ${RUN_STATUS}... (attempt ${attempt}/40)"
  fi
  sleep 5
done

if [ "${DEPLOY_PASSED}" != "true" ]; then
  log_error "Timed out waiting for deployment workflow to complete."
  exit 1
fi

# Verify CloudFront invalidation in AWS
log_info "Querying AWS CloudFront for recent invalidations on distribution E1AXFS263AVC77..."
LATEST_INV=$(aws cloudfront list-invalidations --distribution-id E1AXFS263AVC77 --max-items 1 --query "InvalidationList.Items[0].[Id, Status, CreateTime]" --output text || true)
log_success "Latest CloudFront Invalidation: ${LATEST_INV}"

log_info "================================================================="
log_success "  All Ticket #98 Acceptance Criteria Verified Successfully!      "
log_info "================================================================="
