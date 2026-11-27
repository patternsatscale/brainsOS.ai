#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Immediate Software Kill-Switch (L7: Communications & Operational Control)
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
    if [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
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

resolve_litellm_url() {
  local port="$1"
  if command -v curl >/dev/null 2>&1 && curl -sf --max-time 2 "http://127.0.0.1:${port}/health/liveness" >/dev/null 2>&1; then
    echo "http://127.0.0.1:${port}"
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    local target_cname="brainsos-control-litellm"
    local ip=""
    ip="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{if eq $k "brainsos-control-net"}}{{$v.IPAddress}}{{end}}{{end}}' "${target_cname}" 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -z "${ip}" ]; then
      ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${target_cname}" 2>/dev/null | awk '{print $1}' || true)"
    fi
    if [ -z "${ip}" ]; then
      local cid=""
      cid="$(docker compose ps -q litellm 2>/dev/null | head -n 1 || true)"
      if [ -n "${cid}" ]; then
        ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${cid}" 2>/dev/null | awk '{print $1}' || true)"
      fi
    fi
    if [ -n "${ip}" ]; then
      echo "http://${ip}:${port}"
      return 0
    fi
  fi

  echo "http://127.0.0.1:${port}"
}

LITELLM_URL="$(resolve_litellm_url "${LITELLM_PORT}")"

log_warn "========================================================"
if [ "${TARGET_TENANT}" = "all" ]; then
  log_warn "     TRIGGERING BRAINSOS FLEET-WIDE EMERGENCY KILL-SWITCH  "
else
  log_warn "     TRIGGERING TARGETED KILL-SWITCH FOR: ${TARGET_TENANT} "
fi
log_warn "========================================================"

# Helper to revoke key in LiteLLM
revoke_key() {
  local key_to_revoke="$1"
  if [ -n "${key_to_revoke}" ] && [ -n "${MASTER_KEY}" ]; then
    log_info "Attempting to revoke virtual key '${key_to_revoke}' via LiteLLM API (${LITELLM_URL})..."
    HTTP_CODE=$(curl -s --max-time 3 -o /dev/null -w "%{http_code}" \
      -X POST "${LITELLM_URL}/key/delete" \
      -H "Authorization: Bearer ${MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"keys\": [\"${key_to_revoke}\"]}" 2>/dev/null || echo "000")

    if [ "${HTTP_CODE}" = "200" ]; then
      log_success "Virtual key revoked successfully in LiteLLM: ${key_to_revoke}"
    else
      log_warn "LiteLLM API returned HTTP ${HTTP_CODE} or was unreachable. Container termination ensures loop is halted."
    fi
  fi
}

stop_host_worker() {
  local cp_dir="${BRAINSOS_CONTROL_PLANE_DIR:-${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/control_plane}"
  local pid_file="${cp_dir}/queue_worker.pid"
  local stopped=false

  if [ -f "${pid_file}" ]; then
    local pid=""
    pid="$(cat "${pid_file}" 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      log_info "Stopping host brainsos_agent.worker (PID ${pid})..."
      kill -TERM "${pid}" 2>/dev/null || true
      stopped=true
    fi
    rm -f "${pid_file}" 2>/dev/null || true
  fi

  if command -v pkill >/dev/null 2>&1; then
    if pkill -TERM -f "[b]rainsos_agent.worker" 2>/dev/null; then
      stopped=true
    fi
  fi

  if [ "${stopped}" = true ]; then
    log_success "Host brainsos_agent.worker halted."
  else
    log_info "Host brainsos_agent.worker was not running."
  fi
}

kill_ephemeral_containers() {
  local filter_expr="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  local ephem_ids=""
  ephem_ids="$(docker ps -q --filter "${filter_expr}" 2>/dev/null || true)"
  if [ -n "${ephem_ids}" ]; then
    for cid in ${ephem_ids}; do
      log_info "Killing ephemeral runner container '${cid}'..."
      docker kill "${cid}" >/dev/null 2>&1 || true
      log_success "Ephemeral runner container '${cid}' killed."
    done
  else
    log_info "No active ephemeral containers matching '${filter_expr}'."
  fi
}

if [ "${TARGET_TENANT}" != "all" ]; then
  # ----------------------------------------------------------------------------
  # Targeted Single-Tenant Emergency Intervention
  # ----------------------------------------------------------------------------
  kill_ephemeral_containers "label=brainsos.tenant=${TARGET_TENANT}"

  CONTAINER_NAME="brainsos-agent-${TARGET_TENANT}"
  if command -v docker >/dev/null 2>&1; then
    RUNNING_CONTAINERS="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    if printf '%s\n' "${RUNNING_CONTAINERS}" | grep -xF -- "${CONTAINER_NAME}" >/dev/null; then
      log_info "Pausing agent container '${CONTAINER_NAME}'..."
      docker pause "${CONTAINER_NAME}" || docker stop "${CONTAINER_NAME}"
      log_success "Agent container '${CONTAINER_NAME}' paused/halted."
    elif printf '%s\n' "${RUNNING_CONTAINERS}" | grep -xF -- "brainsos-${TARGET_TENANT}" >/dev/null; then
      docker pause "brainsos-${TARGET_TENANT}" || docker stop "brainsos-${TARGET_TENANT}"
      log_success "Agent container 'brainsos-${TARGET_TENANT}' paused/halted."
    else
      log_info "Warm container for tenant '${TARGET_TENANT}' is not currently running."
    fi
  fi

  # Resolve tenant virtual key safely via printenv (#387)
  UPPER_TENANT=$(echo "${TARGET_TENANT}" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
  TENANT_VAR_NAME="${UPPER_TENANT}_LITELLM_KEY"
  KEY_VAL=""
  if [[ "${TENANT_VAR_NAME}" =~ ^[A-Z0-9_]+$ ]]; then
    KEY_VAL="$(printenv "${TENANT_VAR_NAME}" 2>/dev/null || true)"
  fi
  if [ -n "${KEY_VAL}" ]; then
    revoke_key "${KEY_VAL}"
  fi

  log_success "Targeted emergency intervention complete for '${TARGET_TENANT}'."
  echo ""
  echo "To resume operations for '${TARGET_TENANT}':"
  MEM_PATH="${BRAINSOS_AGENTS_DIR:-${BRAINSOS_DATA_DIR:-./data}/agents}/${TARGET_TENANT}/memories"
  echo "  1. Audit memories: ${MEM_PATH}"
  echo "  2. Unpause warm container (if paused): docker unpause ${CONTAINER_NAME} (or docker start ${CONTAINER_NAME})"
  echo "  3. Resume control plane: ./scripts/control/start-control-plane.sh restart"
  echo ""

else
  # ----------------------------------------------------------------------------
  # Fleet-Wide Emergency Intervention (All Agents)
  # ----------------------------------------------------------------------------
  stop_host_worker
  kill_ephemeral_containers "label=brainsos.tenant"

  ACTIVE_AGENTS=""
  if command -v docker >/dev/null 2>&1; then
    ACTIVE_AGENTS=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-(agent-|hermes)' || true)
  fi

  if [ -n "${ACTIVE_AGENTS}" ]; then
    for c in ${ACTIVE_AGENTS}; do
      log_info "Pausing agent container '${c}'..."
      docker pause "${c}" 2>/dev/null || docker stop "${c}" 2>/dev/null || true
      log_success "Agent container '${c}' paused/halted."
    done
  else
    log_info "No active warm agent containers detected."
  fi

  # Revoke primary key if defined
  PRIMARY_VKEY="${TERRASTELLA_LITELLM_KEY:-${HERMES_LITELLM_KEY:-}}"
  if [ -n "${PRIMARY_VKEY}" ]; then
    revoke_key "${PRIMARY_VKEY}"
  fi

  # Resolve canonical agents manifest: ${BRAINSOS_DATA_DIR}/settings/agents.yaml -> config/default_settings/agents.yaml
  MANIFEST_PATH=""
  SETTINGS_MANIFEST="${BRAINSOS_SETTINGS_DIR:-${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/settings}/agents.yaml"
  if [ -f "${SETTINGS_MANIFEST}" ]; then
    MANIFEST_PATH="${SETTINGS_MANIFEST}"
  elif [ -f "${REPO_ROOT}/config/default_settings/agents.yaml" ]; then
    MANIFEST_PATH="${REPO_ROOT}/config/default_settings/agents.yaml"
  fi

  # Revoke all manifest keys if possible
  if [ -n "${MANIFEST_PATH}" ] && command -v python3 >/dev/null 2>&1; then
    BRAINSOS_ESTOP_MANIFEST="${MANIFEST_PATH}" \
    BRAINSOS_ESTOP_MASTER_KEY="${MASTER_KEY}" \
    BRAINSOS_ESTOP_LITELLM_URL="${LITELLM_URL}" \
    python3 - << 'EOF' 2>/dev/null || true
import json
import os
import urllib.request
import yaml

manifest_path = os.environ.get("BRAINSOS_ESTOP_MANIFEST", "")
master_key = os.environ.get("BRAINSOS_ESTOP_MASTER_KEY", "")
litellm_url = os.environ.get("BRAINSOS_ESTOP_LITELLM_URL", "")
if os.path.exists(manifest_path) and master_key and litellm_url:
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for a in data.get("agents", []):
        if not isinstance(a, dict) or not a.get("id"):
            continue
        aid = a["id"]
        default_key_name = aid.upper().replace("-", "_") + "_LITELLM_KEY"
        key_name = a.get("routing", {}).get("virtual_key", default_key_name)
        key_val = os.environ.get(key_name, "").strip()
        if not key_val:
            continue
        req = urllib.request.Request(
            f"{litellm_url}/key/delete",
            data=json.dumps({"keys": [key_val]}).encode("utf-8"),
            headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    print(f"[SUCCESS] Revoked key for {aid}")
        except Exception:
            pass
EOF
  fi

  log_success "Fleet-wide emergency intervention complete. Core platform remains intact."
  echo ""
  echo "To resume fleet operations:"
  echo "  1. Verify memories: bash scripts/control/snapshot-memories.sh"
  echo "  2. Unpause containers: docker compose unpause"
  echo "  3. Resume control plane: ./scripts/control/start-control-plane.sh restart"
  echo ""
fi
