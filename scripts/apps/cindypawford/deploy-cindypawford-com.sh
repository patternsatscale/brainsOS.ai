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
STAGE="production"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --stage)
      STAGE="$2"
      shift 2
      ;;
    production|prod|staging|dev)
      STAGE="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

echo "=== [Cindy Pawford Deployment Pipeline] ==="
echo "Stage: ${STAGE}"
echo "Dry Run: ${DRY_RUN}"
echo "Root Dir: ${ROOT_DIR}"

# 1. Synchronize CindyPawford-Online Canvas
echo "--> Synchronizing Cindy Pawford site canvas..."
if [ ! -d "${SITE_DIR}/.git" ]; then
  echo "--> Cloning patternsatscale/CindyPawford-Online into ${SITE_DIR}..."
  mkdir -p "${SITE_DIR}"
  git clone https://github.com/patternsatscale/CindyPawford-Online.git "${SITE_DIR}"
else
  if git -C "${SITE_DIR}" diff --quiet 2>/dev/null && git -C "${SITE_DIR}" diff --cached --quiet 2>/dev/null; then
    echo "--> Pulling latest canvas from patternsatscale/CindyPawford-Online..."
    git -C "${SITE_DIR}" pull origin main --rebase 2>/dev/null || true
  else
    echo "--> Canvas has local modifications; deploying active working tree state."
  fi
fi

# 2. Stage Platform Shell and Runtime Config into isolated build directory (dist/site)
BUILD_DIR="${INFRA_DIR}/dist/site"
echo "--> Staging canvas and injecting Platform Shell into build directory: ${BUILD_DIR}..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude '.git' "${SITE_DIR}/" "${BUILD_DIR}/"
else
  cp -R "${SITE_DIR}/." "${BUILD_DIR}/"
  rm -rf "${BUILD_DIR}/.git"
fi

mkdir -p "${BUILD_DIR}/_platform"
if [ -f "${PLATFORM_SHELL_SRC}" ]; then
  cp "${PLATFORM_SHELL_SRC}" "${BUILD_DIR}/_platform/shell.js"
fi

# Stage runtime config fallback for non-CloudFront / local environments
cat << 'EOF' > "${BUILD_DIR}/_platform/config.js"
window.CINDY_API_URL = window.CINDY_API_URL || "https://api.cindypawford.com";
EOF

# Auto-inject script tags into all HTML pages in BUILD_DIR if not present
for html_file in "${BUILD_DIR}"/*.html; do
  [ -f "${html_file}" ] || continue
  if ! grep -q "/_platform/config.js" "${html_file}"; then
    echo "--> Injecting runtime config script into $(basename "${html_file}")..."
    sed -i.bak 's|</body>|  <script src="/_platform/config.js"></script>\
</body>|' "${html_file}" && rm -f "${html_file}.bak"
  fi
  if ! grep -q "/_platform/shell.js" "${html_file}"; then
    echo "--> Injecting platform shell script into $(basename "${html_file}")..."
    sed -i.bak 's|</body>|  <script src="/_platform/shell.js" defer></script>\
</body>|' "${html_file}" && rm -f "${html_file}.bak"
  fi
done

# Ingest latest PRs and rebuild digital museum archive portal
if [ -f "${ROOT_DIR}/scripts/apps/cindypawford/build-archive-portal.py" ]; then
  if [ -f "${ROOT_DIR}/scripts/apps/cindypawford/ingest-pr-logbook.py" ]; then
    echo "--> Ingesting latest CindyPawford-Online PRs into declassified logbook..."
    python3 "${ROOT_DIR}/scripts/apps/cindypawford/ingest-pr-logbook.py" --auto-scan || echo "[WARN] PR auto-scan non-fatal fallback."
  fi
  echo "--> Compiling digital museum and declassified logbook archive portal..."
  python3 "${ROOT_DIR}/scripts/apps/cindypawford/build-archive-portal.py"
fi

# 3. Validate TypeScript & SST configuration
echo "--> Validating SST configuration and TypeScript types..."
if [ ! -d "${INFRA_DIR}/.sst/platform" ]; then
  echo "--> Installing SST providers..."
  (cd "${INFRA_DIR}" && npx sst install)
fi
(cd "${INFRA_DIR}" && npm run typecheck)

# 4. Deploy SST Infrastructure (or Dry-Run Diff)
if [ "${DRY_RUN}" = true ]; then
  echo "--> [DRY RUN] Validating SST configuration..."
  (cd "${INFRA_DIR}" && npx sst diff --stage "${STAGE}" 2>&1 || echo "--> [DRY RUN] Stage not yet deployed in AWS; ready for initial deployment.")
  echo "=== [DRY RUN Complete: No changes deployed] ==="
  exit 0
fi

echo "--> Deploying SST Ion infrastructure to AWS (${STAGE})..."
(cd "${INFRA_DIR}" && npx sst deploy --stage "${STAGE}")

# 5. Enforce S3 Bucket Versioning on Production Bucket
echo "--> Checking S3 buckets and enforcing versioning..."
BUCKETS=$(aws s3api list-buckets --query "Buckets[?contains(Name, 'cindy-pawford') || contains(Name, 'cindypawford')].Name" --output text || true)

for b in ${BUCKETS}; do
  if [ -n "$b" ] && [ "$b" != "None" ]; then
    echo "--> Enabling S3 versioning on: ${b}"
    aws s3api put-bucket-versioning --bucket "${b}" --versioning-configuration Status=Enabled || true
  fi
done

echo "=== [Cindy Pawford Deployment Successfully Completed] ==="
