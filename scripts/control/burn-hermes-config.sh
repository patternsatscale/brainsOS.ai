#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Snapshot & Burn Hermes Runtime Configuration (Ticket #207)
# Extracts live UI customizations (tools, disabled toolsets, gateway settings,
# model endpoints) from the running runner-hermes container into git-tracked
# config/default_runners/hermes/ files.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

TARGET_DIR="${REPO_ROOT}/config/default_runners/hermes"
mkdir -p "${TARGET_DIR}"

CONTAINER_NAME="brainsos-runner-hermes"
CONTAINER_RUNNING=false

if command -v docker &>/dev/null && docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
  CONTAINER_RUNNING=true
fi

log_info "======================================================================"
log_info "Burning Hermes Runner Live Configuration to ${TARGET_DIR}"
log_info "======================================================================"

if [ "${CONTAINER_RUNNING}" = "true" ]; then
  log_info "Extracting live settings directly from container: ${CONTAINER_NAME}..."
  for file in config.yaml config.json model_pool.json mcp.json; do
    if docker exec "${CONTAINER_NAME}" test -f "/root/.hermes/${file}" 2>/dev/null; then
      docker cp "${CONTAINER_NAME}:/root/.hermes/${file}" "${TARGET_DIR}/${file}"
      log_success "Extracted ${file} from container."
    fi
  done
else
  # Check if live settings exist in local volume / runners data path
  LOCAL_RUNNER_DIR="${BRAINSOS_RUNNERS_DIR:-${BRAINSOS_DATA_DIR:-./data}/runners}/hermes"
  if [ -d "${LOCAL_RUNNER_DIR}" ]; then
    log_info "Container not running; syncing from local runner volume: ${LOCAL_RUNNER_DIR}..."
    for file in config.yaml config.json model_pool.json mcp.json; do
      if [ -f "${LOCAL_RUNNER_DIR}/${file}" ]; then
        cp "${LOCAL_RUNNER_DIR}/${file}" "${TARGET_DIR}/${file}"
        log_success "Synced ${file} from local volume."
      fi
    done
  else
    log_warn "Neither running container nor local runner directory found. Ensuring target files exist."
  fi
fi

# Sanitize host-specific loops (Rule 2: normalize http://localhost:4000 to http://litellm:4000)
for file in "${TARGET_DIR}/config.yaml" "${TARGET_DIR}/config.json"; do
  if [ -f "${file}" ]; then
    sed -i.bak 's|http://localhost:4000|http://litellm:4000|g' "${file}"
    sed -i.bak 's|http://127.0.0.1:4000|http://litellm:4000|g' "${file}"
    rm -f "${file}.bak"
  fi
done

log_success "Sanitized provider base URLs to internal Docker network (http://litellm:4000)."
log_info "Current git diff for Hermes default configuration:"
git diff --stat "${TARGET_DIR}" || true

log_success "Hermes runner configuration burn completed successfully."
