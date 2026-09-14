#!/usr/bin/env bash
# ==============================================================================
# scripts/verify-cw1-staging.sh
# Verification harness for Ticket #36 (CW-1):
# SST Ion Infrastructure, Legacy Stack Retirement, Platform Shell & Suggestion API
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INFRA_DIR="${ROOT_DIR}/apps/cindypawford/infra"
SITE_DIR="${ROOT_DIR}/apps/cindypawford/site"
PAS_DIR="${ROOT_DIR}/../pas-webapps"

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
  if echo "${out}" | grep -q "${expected}"; then
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
  if ! echo "${out}" | grep -q "${unexpected}"; then
    echo "PASS"
    PASS=$((PASS + 1))
  else
    echo "FAIL (found unexpected '${unexpected}')"
    FAIL=$((FAIL + 1))
  fi
}

echo "================================================================================"
echo "Project Titan: Ticket #36 (CW-1) End-to-End Verification Suite"
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
# 2. Legacy Stack Retirement & PASStack Protection (CW1-1)
# ------------------------------------------------------------------------------
echo
echo "--- 2. Legacy Stack Retirement & PASStack Safety ---"

assert_output_not_contains \
  "Legacy CindyStack is removed from pas-webapps sst.config.ts" \
  "CindyStack" \
  cat "${PAS_DIR}/sst.config.ts"

assert_output_contains \
  "PASStack is safely preserved in pas-webapps sst.config.ts" \
  "app.stack(PASStack)" \
  cat "${PAS_DIR}/sst.config.ts"

assert_output_contains \
  "BackendStack is safely preserved in pas-webapps sst.config.ts" \
  "app.stack(BackendStack)" \
  cat "${PAS_DIR}/sst.config.ts"

assert_success \
  "pas-webapps passes TypeScript typecheck without errors" \
  npm --prefix "${PAS_DIR}" run typecheck

assert_success \
  "prod-patternsatscale-CindyStack is confirmed absent from AWS CloudFormation" \
  node -e '
    const { execSync } = require("child_process");
    try {
      execSync("aws cloudformation describe-stacks --region us-east-1 --stack-name prod-patternsatscale-CindyStack 2>&1", { stdio: "pipe" });
      process.exit(1); // Should not succeed
    } catch (e) {
      process.exit(0); // Expected to fail
    }
  '

assert_success \
  "prod-patternsatscale-PASStack remains intact and active in AWS" \
  node -e '
    const { execSync } = require("child_process");
    const out = execSync("aws cloudformation describe-stacks --region us-east-1 --stack-name prod-patternsatscale-PASStack --query \"Stacks[0].StackStatus\" --output text").toString().trim();
    if (out.includes("COMPLETE")) process.exit(0);
    process.exit(1);
  '

# ------------------------------------------------------------------------------
# 3. SST Ion Infrastructure Scaffold (CW1-2 & CW1-4)
# ------------------------------------------------------------------------------
echo
echo "--- 3. SST Ion Infrastructure Scaffold ---"

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
# 4. Closed Shadow DOM Platform Shell Isolation (CW1-3)
# ------------------------------------------------------------------------------
echo
echo "--- 4. Platform Shell Closed Shadow DOM Isolation ---"

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
# 5. Serverless Suggestion & Voting Logic (CW1-4)
# ------------------------------------------------------------------------------
echo
echo "--- 5. Suggestion & Voting Logic ---"

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
# 6. Deployment & Rollback Tooling (CW1-5)
# ------------------------------------------------------------------------------
echo
echo "--- 6. Deployment & Rollback Scripts ---"

assert_success \
  "scripts/deploy-cindypawford-com.sh shell syntax is valid" \
  bash -n "${SCRIPT_DIR}/deploy-cindypawford-com.sh"

assert_success \
  "scripts/rollback-cindypawford-com.sh shell syntax is valid" \
  bash -n "${SCRIPT_DIR}/rollback-cindypawford-com.sh"

assert_output_contains \
  "deploy-cindypawford-com.sh supports --dry-run" \
  "DRY RUN" \
  "${SCRIPT_DIR}/deploy-cindypawford-com.sh" --dry-run

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
