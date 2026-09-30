#!/usr/bin/env bash
# ==============================================================================
# scripts/rollback-cindypawford-com.sh
# Deterministic rollback tool for Cindy Pawford's production canvas
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
SITE_DIR="${ROOT_DIR}/data/agent_apps/cindypawford/site"

COMMIT_OR_TAG="${1:-HEAD~1}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=true
      ;;
  esac
done

echo "=== [Cindy Pawford Deterministic Rollback Tool] ==="
echo "Target Site Dir: ${SITE_DIR}"
echo "Rollback Target: ${COMMIT_OR_TAG}"
echo "Dry Run: ${DRY_RUN}"

if [ ! -d "${SITE_DIR}/.git" ]; then
  echo "Error: ${SITE_DIR} is not a git repository."
  exit 1
fi

echo "--> Checking git log in site repository..."
(cd "${SITE_DIR}" && git log -n 3 --oneline)

if [ "${DRY_RUN}" = true ]; then
  echo "--> [DRY RUN] Would checkout ${COMMIT_OR_TAG} in ${SITE_DIR} and redeploy."
  exit 0
fi

echo "--> Reverting site canvas to: ${COMMIT_OR_TAG}..."
(cd "${SITE_DIR}" && git checkout "${COMMIT_OR_TAG}" -- index.html styles.css app.js 2>/dev/null || git checkout "${COMMIT_OR_TAG}")

echo "--> Re-deploying restored canvas via deploy-cindypawford-com.sh..."
"${SCRIPT_DIR}/deploy-cindypawford-com.sh"

echo "=== [Rollback Successfully Completed] ==="
