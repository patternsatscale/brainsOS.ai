#!/usr/bin/env bash
# ==============================================================================
# scripts/apps/cindypawford/sync-cindy-site.sh
# Synchronizes Cindy Pawford site canvas with upstream CindyPawford-Online repo
# and injects the latest master platform shell and runtime configuration.
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
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

SITE_DIR="${REPO_ROOT}/data/agent_apps/cindypawford/site"
INFRA_DIR="${REPO_ROOT}/data/agent_apps/cindypawford/pipeline"
SHELL_SRC="${INFRA_DIR}/src/shell.js"

echo "=== [Cindy Pawford Canvas Synchronization] ==="
echo "Repo Root: ${REPO_ROOT}"
echo "Site Dir:  ${SITE_DIR}"

# 1. Clone or Pull Latest from CindyPawford-Online
if [ ! -d "${SITE_DIR}/.git" ]; then
  echo "--> Cloning patternsatscale/CindyPawford-Online into ${SITE_DIR}..."
  mkdir -p "${SITE_DIR}"
  git clone https://github.com/patternsatscale/CindyPawford-Online.git "${SITE_DIR}"
else
  if git -C "${SITE_DIR}" diff --quiet 2>/dev/null && git -C "${SITE_DIR}" diff --cached --quiet 2>/dev/null; then
    echo "--> Pulling latest canvas from patternsatscale/CindyPawford-Online..."
    git -C "${SITE_DIR}" pull origin main --rebase 2>/dev/null || true
  else
    echo "--> Canvas has local modifications; using active working tree state."
  fi
fi

# 2. Validate Site Syntax
if [ -f "${SITE_DIR}/app.js" ]; then
  echo "--> Validating app.js syntax..."
  node -c "${SITE_DIR}/app.js"
fi

echo "=== [Canvas Synchronization Successfully Completed] ==="
