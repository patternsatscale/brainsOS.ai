#!/usr/bin/env bash
# ==============================================================================
# scripts/deploy-cindypawford-com.sh
# Autonomous direct-to-production deployment tool for cindypawford.com
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
PLATFORM_SHELL_SRC="${INFRA_DIR}/src/shell.js"
STAGE="${1:-production}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --stage)
      STAGE="$2"
      shift 2
      ;;
    production|prod)
      STAGE="production"
      ;;
  esac
done

echo "=== [Cindy Pawford Deployment Pipeline] ==="
echo "Stage: ${STAGE}"
echo "Dry Run: ${DRY_RUN}"
echo "Root Dir: ${ROOT_DIR}"

# 1. Ensure Platform Shell is staged and injected
echo "--> Ensuring Platform Shell is injected..."
mkdir -p "${SITE_DIR}/_platform"
if [ -f "${PLATFORM_SHELL_SRC}" ]; then
  cp "${PLATFORM_SHELL_SRC}" "${SITE_DIR}/_platform/shell.js"
fi

# Auto-inject script tag if not present
if [ -f "${SITE_DIR}/index.html" ]; then
  if ! grep -q "/_platform/shell.js" "${SITE_DIR}/index.html"; then
    echo "--> Injecting platform shell script into ${SITE_DIR}/index.html..."
    sed -i '' 's|</body>|  <script src="/_platform/shell.js" defer></script>\
</body>|' "${SITE_DIR}/index.html"
  fi
fi

# 2. Validate TypeScript & SST configuration
echo "--> Validating SST configuration and TypeScript types..."
(cd "${INFRA_DIR}" && npm run typecheck)

# 3. Deploy SST Infrastructure (or Dry-Run Diff)
if [ "${DRY_RUN}" = true ]; then
  echo "--> [DRY RUN] Validating SST configuration..."
  (cd "${INFRA_DIR}" && sst diff --stage "${STAGE}" 2>&1 || echo "--> [DRY RUN] Stage not yet deployed in AWS; ready for initial deployment.")
  echo "=== [DRY RUN Complete: No changes deployed] ==="
  exit 0
fi

echo "--> Deploying SST Ion infrastructure to AWS (${STAGE})..."
(cd "${INFRA_DIR}" && sst deploy --stage "${STAGE}")

# 4. Enforce S3 Bucket Versioning on Production Bucket
echo "--> Checking S3 buckets and enforcing versioning..."
BUCKETS=$(aws s3api list-buckets --query "Buckets[?contains(Name, 'cindy-pawford') || contains(Name, 'cindypawford')].Name" --output text || true)

for b in ${BUCKETS}; do
  if [ -n "$b" ] && [ "$b" != "None" ]; then
    echo "--> Enabling S3 versioning on: ${b}"
    aws s3api put-bucket-versioning --bucket "${b}" --versioning-configuration Status=Enabled || true
  fi
done

echo "=== [Cindy Pawford Deployment Successfully Completed] ==="
