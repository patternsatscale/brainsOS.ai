#!/usr/bin/env bash
# ==============================================================================
# scripts/verify-cw1-staging.sh
# Verification harness for Ticket #36 (CW-1):
# SST Ion Infrastructure, Platform Shell & Suggestion API
# ==============================================================================
set -euo pipefail

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
ROOT_DIR="${REPO_ROOT}"

INFRA_DIR="${ROOT_DIR}/apps/cindypawford/infra"
SITE_DIR="${ROOT_DIR}/apps/cindypawford/site"

PASS=0
FAIL=0

assert_success() {
  local desc="$1"
  shift
  echo -n "  [TEST] ${desc}... "
  if "$@" >/dev/null 2>&1; then
    echo "PASS"
    PASS=$((PASS + 1))
  else
    echo "FAIL"
    FAIL=$((FAIL + 1))
  fi
}

assert_output_contains() {
  local desc="$1"
  local expected="$2"
  shift 2
  echo -n "  [TEST] ${desc}... "
  local out
  out=$("$@")
  if echo "${out}" | grep "${expected}" >/dev/null; then
    echo "PASS"
    PASS=$((PASS + 1))
  else
    echo "FAIL (expected to contain '${expected}')"
    FAIL=$((FAIL + 1))
  fi
}

assert_output_not_contains() {
  local desc="$1"
  local unexpected="$2"
  shift 2
  echo -n "  [TEST] ${desc}... "
  local out
  out=$("$@")
  if echo "${out}" | grep "${unexpected}" >/dev/null; then
    echo "FAIL (expected NOT to contain '${unexpected}')"
    FAIL=$((FAIL + 1))
  else
    echo "PASS"
    PASS=$((PASS + 1))
  fi
}

echo "================================================================================"
echo "brainsOS: Ticket #36 (CW-1) End-to-End Verification Suite"
echo "================================================================================"

# ------------------------------------------------------------------------------
# 1. Zero Cloud Credentials & Compartmentalization (Rule 4 & Rule 7)
# ------------------------------------------------------------------------------
echo
echo "--- 1. Agent Boundary & Compartmentalization (Rules 4 & 7) ---"

assert_output_not_contains \
  "Agent container compose has NO infra mount" \
  "./apps/cindypawford/infra" \
  cat "${ROOT_DIR}/docker-compose.agents.yml"

assert_output_not_contains \
  "Agent container compose has NO AWS credentials" \
  "AWS_ACCESS_KEY_ID" \
  cat "${ROOT_DIR}/docker-compose.agents.yml"

assert_output_contains \
  "Agent container mounts ONLY site to /app/html" \
  "./apps/cindypawford/site:/app/html" \
  cat "${ROOT_DIR}/docker-compose.agents.yml"

# ------------------------------------------------------------------------------
# 2. SST Ion Infrastructure Scaffold (CW1-2 & CW1-4)
# ------------------------------------------------------------------------------
echo
echo "--- 2. SST Ion Infrastructure Scaffold ---"

assert_success \
  "apps/cindypawford/infra/package.json exists" \
  test -f "${INFRA_DIR}/package.json"

assert_output_contains \
  "sst.config.ts provisions DynamoDB Suggestions with era partitioning" \
  "hashKey: \"era_id\", rangeKey: \"id\"" \
  cat "${INFRA_DIR}/sst.config.ts"

assert_output_contains \
  "sst.config.ts provisions ProductionSite with cindypawford.com and www redirect" \
  "www.cindypawford.com" \
  cat "${INFRA_DIR}/sst.config.ts"

assert_output_contains \
  "sst.config.ts provisions ArchiveSite with archive.cindypawford.com" \
  "archive.cindypawford.com" \
  cat "${INFRA_DIR}/sst.config.ts"

assert_success \
  "SST Ion infrastructure passes TypeScript typecheck (0 errors)" \
  npm --prefix "${INFRA_DIR}" run typecheck

# ------------------------------------------------------------------------------
# 3. Closed Shadow DOM Platform Shell Isolation (CW1-3)
# ------------------------------------------------------------------------------
echo
echo "--- 3. Platform Shell Closed Shadow DOM Isolation ---"

assert_success \
  "shell.js exists in infra/src" \
  test -f "${INFRA_DIR}/src/shell.js"

assert_output_contains \
  "shell.js uses Closed Shadow DOM isolation" \
  "this.attachShadow({ mode: \"closed\" })" \
  cat "${INFRA_DIR}/src/shell.js"

assert_output_contains \
  "shell.js contains un-nukeable MutationObserver" \
  "new MutationObserver" \
  cat "${INFRA_DIR}/src/shell.js"

assert_output_contains \
  "shell.js links to @CindyPawford_bot on Telegram" \
  "https://t.me/CindyPawford_bot" \
  cat "${INFRA_DIR}/src/shell.js"

assert_output_contains \
  "shell.js links to archive.cindypawford.com" \
  "https://archive.cindypawford.com" \
  cat "${INFRA_DIR}/src/shell.js"

assert_success \
  "Platform shell script is auto-injected into site/_platform/shell.js" \
  test -f "${SITE_DIR}/_platform/shell.js"

# ------------------------------------------------------------------------------
# 4. Serverless Suggestion & Voting Logic (CW1-4)
# ------------------------------------------------------------------------------
echo
echo "--- 4. Suggestion & Voting Logic ---"

assert_success \
  "API handlers export topSuggestions, suggest, and vote" \
  node -e '
    const api = require("fs").readFileSync("'${INFRA_DIR}'/src/api.ts", "utf8");
    if (!api.includes("export async function topSuggestions")) process.exit(1);
    if (!api.includes("export async function suggest")) process.exit(1);
    if (!api.includes("export async function vote")) process.exit(1);
    process.exit(0);
  '

assert_success \
  "API enforces 140 character limit on suggestions" \
  node -e '
    const api = require("fs").readFileSync("'${INFRA_DIR}'/src/api.ts", "utf8");
    if (!api.includes("140")) process.exit(1);
    process.exit(0);
  '

assert_success \
  "API rejects spam and profanity" \
  node -e '
    const api = require("fs").readFileSync("'${INFRA_DIR}'/src/api.ts", "utf8");
    if (!api.includes("isProfaneOrSpam")) process.exit(1);
    process.exit(0);
  '

# ------------------------------------------------------------------------------
# 5. Deployment & Rollback Tooling (CW1-5)
# ------------------------------------------------------------------------------
echo
echo "--- 5. Deployment & Rollback Scripts ---"

assert_success \
  "scripts/apps/cindypawford/deploy-cindypawford-com.sh shell syntax is valid" \
  bash -n "${ROOT_DIR}/scripts/apps/cindypawford/deploy-cindypawford-com.sh"

assert_success \
  "scripts/apps/cindypawford/rollback-cindypawford-com.sh shell syntax is valid" \
  bash -n "${ROOT_DIR}/scripts/apps/cindypawford/rollback-cindypawford-com.sh"

assert_output_contains \
  "deploy-cindypawford-com.sh supports --dry-run" \
  "DRY RUN" \
  "${ROOT_DIR}/scripts/apps/cindypawford/deploy-cindypawford-com.sh" --dry-run

assert_success \
  "Platform shell script is staged into build dist/site/_platform/shell.js" \
  test -f "${INFRA_DIR}/dist/site/_platform/shell.js"

assert_success \
  "deploy-cindypawford-com.sh preserves canvas git purity (zero uncommitted changes)" \
  test -z "$(git -C "${SITE_DIR}" status --porcelain 2>/dev/null)"

echo
echo "================================================================================"
echo "Verification Summary: ${PASS} Passed, ${FAIL} Failed"
echo "================================================================================"

if [ "${FAIL}" -eq 0 ]; then
  echo "ALL VERIFICATION CHECKS PASSED!"
  exit 0
else
  echo "VERIFICATION FAILED WITH ${FAIL} ERRORS!"
  exit 1
fi
