#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Immediate Software Kill-Switch (L7: Communications & Operational Control)
# Instantly halts agent loops by pausing/stopping containers and revoking LiteLLM keys.
# Supports targeted single-tenant stop: ./scripts/control/emergency-stop.sh <tenant_id>
# Or full fleet shutdown:              ./scripts/control/emergency-stop.sh [all]
# ==============================================================================

set -euo pipefail

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

# Load environment variables
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

TARGET_TENANT="${1:-all}"
LITELLM_PORT="${LITELLM_PORT:-4000}"
MASTER_KEY="${LITELLM_MASTER_KEY:-}"
LITELLM_URL="http://127.0.0.1:${LITELLM_PORT}"

log_warn "========================================================"
if [ "${TARGET_TENANT}" = "all" ]; then
  log_warn "     TRIGGERING TITAN FLEET-WIDE EMERGENCY KILL-SWITCH  "
else
  log_warn "     TRIGGERING TARGETED KILL-SWITCH FOR: ${TARGET_TENANT} "
fi
log_warn "========================================================"

# Helper to revoke key in LiteLLM
revoke_key() {
  local key_to_revoke="$1"
  if [ -n "${key_to_revoke}" ] && [ -n "${MASTER_KEY}" ]; then
    log_info "Attempting to revoke virtual key '${key_to_revoke}' via LiteLLM API..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "${LITELLM_URL}/key/delete" \
      -H "Authorization: Bearer ${MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"keys\": [\"${key_to_revoke}\"]}" || echo "000")

    if [ "${HTTP_CODE}" = "200" ]; then
      log_success "Virtual key revoked successfully in LiteLLM: ${key_to_revoke}"
    else
      log_warn "LiteLLM API returned HTTP ${HTTP_CODE} or was unreachable. Container pause ensures loop is halted."
    fi
  fi
}

if [ "${TARGET_TENANT}" != "all" ]; then
  # ----------------------------------------------------------------------------
  # Targeted Single-Tenant Emergency Intervention
  # ----------------------------------------------------------------------------
  CONTAINER_NAME="titan-agent-${TARGET_TENANT}"
  SERVICE_NAME="agent-${TARGET_TENANT}"

  if docker ps --format '{{.Names}}' | grep -qw "${CONTAINER_NAME}"; then
    log_info "Pausing agent container '${CONTAINER_NAME}'..."
    docker pause "${CONTAINER_NAME}" || docker stop "${CONTAINER_NAME}"
    log_success "Agent container '${CONTAINER_NAME}' paused/halted."
  elif docker ps --format '{{.Names}}' | grep -qw "titan-${TARGET_TENANT}"; then
    docker pause "titan-${TARGET_TENANT}" || docker stop "titan-${TARGET_TENANT}"
    log_success "Agent container 'titan-${TARGET_TENANT}' paused/halted."
  else
    log_info "Container for tenant '${TARGET_TENANT}' is not currently running."
  fi

  # Resolve tenant virtual key (macOS Bash 3.2 compatible)
  UPPER_TENANT=$(echo "${TARGET_TENANT}" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
  TENANT_VAR_NAME="HERMES_${UPPER_TENANT}_KEY"
  eval "KEY_VAL=\${${TENANT_VAR_NAME}:-}"
  if [ -z "${KEY_VAL}" ]; then
    KEY_VAL="sk-titan-${TARGET_TENANT}-key"
  fi
  revoke_key "${KEY_VAL}"

  log_success "Targeted emergency intervention complete for '${TARGET_TENANT}'."
  echo ""
  echo "To resume operations for '${TARGET_TENANT}':"
  echo "  1. Audit memories: /memories/agents/${TARGET_TENANT}"
  echo "  2. Unpause container: docker unpause ${CONTAINER_NAME} (or docker start ${CONTAINER_NAME})"
  echo "  3. Resync keys: ./scripts/control/sync-agents.sh --provision-keys"
  echo ""

else
  # ----------------------------------------------------------------------------
  # Fleet-Wide Emergency Intervention (All Agents)
  # ----------------------------------------------------------------------------
  ACTIVE_AGENTS=$(docker ps --format '{{.Names}}' | grep -E '^titan-(agent-|hermes)' || true)

  if [ -n "${ACTIVE_AGENTS}" ]; then
    for c in ${ACTIVE_AGENTS}; do
      log_info "Pausing agent container '${c}'..."
      docker pause "${c}" 2>/dev/null || docker stop "${c}" 2>/dev/null || true
      log_success "Agent container '${c}' paused/halted."
    done
  else
    log_info "No active agent containers detected."
  fi

  # Revoke primary key if defined
  if [ -n "${HERMES_LITELLM_KEY:-}" ]; then
    revoke_key "${HERMES_LITELLM_KEY}"
  fi

  # Revoke all manifest keys if possible
  if [ -f "${REPO_ROOT}/config/agents.yaml" ] && command -v python3 >/dev/null 2>&1; then
    python3 -c "
import os, urllib.request, json, yaml
manifest_path = '${REPO_ROOT}/config/agents.yaml'
master_key = '${MASTER_KEY}'
litellm_url = '${LITELLM_URL}'
if os.path.exists(manifest_path) and master_key:
    with open(manifest_path) as f:
        data = yaml.safe_load(f) or {}
    for a in data.get('agents', []):
        aid = a['id']
        key_name = a.get('routing', {}).get('virtual_key', f'HERMES_{aid.upper().replace(\"-\", \"_\")}_KEY')
        key_val = os.environ.get(key_name, f'sk-titan-{aid}-key')
        req = urllib.request.Request(
            f'{litellm_url}/key/delete',
            data=json.dumps({'keys': [key_val]}).encode(),
            headers={'Authorization': f'Bearer {master_key}', 'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 200:
                    print(f'[SUCCESS] Revoked key for {aid}')
        except Exception:
            pass
" 2>/dev/null || true
  fi

  log_success "Fleet-wide emergency intervention complete. Core platform remains intact."
  echo ""
  echo "To resume fleet operations:"
  echo "  1. Verify memories: bash scripts/control/snapshot-memories.sh"
  echo "  2. Unpause containers: docker compose unpause"
  echo "  3. Resync keys: ./scripts/control/sync-agents.sh --provision-keys"
  echo ""
fi
