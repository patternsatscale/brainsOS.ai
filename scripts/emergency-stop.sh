#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Immediate Software Kill-Switch
# Instantly halts agent loops by stopping the container and revoking the LiteLLM key
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Load environment variables
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_KEY="${HERMES_LITELLM_KEY:-}"
MASTER_KEY="${LITELLM_MASTER_KEY:-}"

log_warn "========================================================"
log_warn "       TRIGGERING PROJECT TITAN EMERGENCY KILL-SWITCH   "
log_warn "========================================================"

# ------------------------------------------------------------------------------
# 1. Immediately Pause/Halt the Hermes Agent Container
# ------------------------------------------------------------------------------
if docker compose ps -q hermes >/dev/null 2>&1; then
  log_info "Pausing Hermes agent execution loop..."
  docker compose pause hermes || docker compose stop hermes
  log_success "Hermes agent container paused/halted."
else
  log_info "Hermes container is not currently running."
fi

# ------------------------------------------------------------------------------
# 2. Invalidate Virtual Key in LiteLLM Control Plane (if reachable)
# ------------------------------------------------------------------------------
if [ -n "${LITELLM_KEY}" ] && [ -n "${MASTER_KEY}" ]; then
  LITELLM_URL="http://127.0.0.1:${LITELLM_PORT}"
  log_info "Attempting to revoke virtual key via LiteLLM API at ${LITELLM_URL}..."
  
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${LITELLM_URL}/key/delete" \
    -H "Authorization: Bearer ${MASTER_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"keys\": [\"${LITELLM_KEY}\"]}" || echo "000")

  if [ "${HTTP_CODE}" = "200" ]; then
    log_success "Virtual key revoked successfully in LiteLLM."
  else
    log_warn "LiteLLM API returned HTTP ${HTTP_CODE} or was unreachable. Container halt ensures loop is terminated."
  fi
fi

log_success "Emergency intervention complete. Host system and memory plane remain intact."
echo ""
echo "To resume agent operations after audit:"
echo "  1. Verify memories: bash scripts/snapshot-memories.sh"
echo "  2. Unpause container: docker compose unpause hermes (or docker compose start hermes)"
echo ""
