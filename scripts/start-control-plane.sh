#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Native Host Control Plane Service Manager
# Manages the host inference engine (Ollama) and AI proxy gateway (LiteLLM)
# ==============================================================================

set -euo pipefail

# Visual styling
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

PID_DIR="${REPO_ROOT}/data/control_plane"
mkdir -p "${PID_DIR}"

OLLAMA_PID_FILE="${PID_DIR}/ollama.pid"
LITELLM_PID_FILE="${PID_DIR}/litellm.pid"
DGX_BRIDGE_PID_FILE="${PID_DIR}/dgx_bridge.pid"
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_DB_PORT="${LITELLM_DB_PORT:-5432}"
DGX_BRIDGE_PORT="${DGX_BRIDGE_PORT:-11001}"
DGX_BRIDGE_BIND="${DGX_BRIDGE_BIND:-}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
HERMES_LITELLM_KEY="${HERMES_LITELLM_KEY:-}"
DATABASE_URL="${DATABASE_URL:-}"
INFERENCE_NUM_CTX="${INFERENCE_NUM_CTX:-4096}"

# Ensure .venv/bin is in PATH for prisma and litellm
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
export DATABASE_URL="${DATABASE_URL}"
export INFERENCE_NUM_CTX="${INFERENCE_NUM_CTX}"

# Helper to detect Docker bridge gateway IP
get_docker_gateway() {
  local gw
  gw=$(ip -4 addr show docker0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)
  echo "${gw:-172.17.0.1}"
}

# Helper to check if database port is listening
check_db_ready() {
  (echo > /dev/tcp/127.0.0.1/"${LITELLM_DB_PORT}") >/dev/null 2>&1 || \
    (command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "${LITELLM_DB_PORT}" >/dev/null 2>&1)
}

# Helper to identify ASUS Ascent GX10 / DGX OS hardware context
is_gx10_hardware() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    return 1
  fi
  if [ -f /sys/class/dmi/id/product_name ] && grep -qi "GX10" /sys/class/dmi/id/product_name 2>/dev/null; then
    return 0
  fi
  if [ -f /sys/class/dmi/id/sys_vendor ] && grep -qi "ASUS" /sys/class/dmi/id/sys_vendor 2>/dev/null && grep -qi "GX10" /sys/class/dmi/id/board_name 2>/dev/null; then
    return 0
  fi
  if [ -d "/opt/nvidia/dgx-dashboard-service" ] || uname -r | grep -qi "nvidia"; then
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------------------
# Action: Stop
# ------------------------------------------------------------------------------
stop_services() {
  log_info "Stopping Project Titan host control plane..."
  
  if [ -f "${LITELLM_PID_FILE}" ]; then
    PID=$(cat "${LITELLM_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping LiteLLM (PID: ${PID})..."
      kill "${PID}" || true
      for i in {1..20}; do
        if ! kill -0 "${PID}" 2>/dev/null; then
          break
        fi
        sleep 0.5
      done
      if kill -0 "${PID}" 2>/dev/null; then
        kill -9 "${PID}" 2>/dev/null || true
      fi
    fi
    rm -f "${LITELLM_PID_FILE}"
    log_success "LiteLLM stopped."
  fi

  # Fallback: terminate any residual process on LITELLM_PORT
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS=$(lsof -ti :"${LITELLM_PORT}" 2>/dev/null || true)
    if [ -n "${PORT_PIDS}" ]; then
      log_info "Stopping residual process on port ${LITELLM_PORT} (PID: ${PORT_PIDS})..."
      for p in ${PORT_PIDS}; do
        kill "${p}" 2>/dev/null || true
      done
      sleep 1
      REMAINING=$(lsof -ti :"${LITELLM_PORT}" 2>/dev/null || true)
      if [ -n "${REMAINING}" ]; then
        for p in ${REMAINING}; do
          kill -9 "${p}" 2>/dev/null || true
        done
      fi
      log_success "Port ${LITELLM_PORT} freed."
    fi
  fi

  # Stop DGX Telemetry bridge if running
  if [ -f "${DGX_BRIDGE_PID_FILE}" ]; then
    PID=$(cat "${DGX_BRIDGE_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping DGX Telemetry bridge (PID: ${PID})..."
      kill "${PID}" 2>/dev/null || true
    fi
    rm -f "${DGX_BRIDGE_PID_FILE}"
    log_success "DGX Telemetry bridge stopped."
  fi

  if command -v lsof >/dev/null 2>&1; then
    DGX_PIDS=$(lsof -ti :"${DGX_BRIDGE_PORT}" 2>/dev/null || true)
    if [ -n "${DGX_PIDS}" ]; then
      for p in ${DGX_PIDS}; do kill "${p}" 2>/dev/null || true; done
    fi
  fi

  if [ -f "${OLLAMA_PID_FILE}" ]; then
    PID=$(cat "${OLLAMA_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping host Ollama (PID: ${PID})..."
      kill "${PID}" || true
      for i in {1..20}; do
        if ! kill -0 "${PID}" 2>/dev/null; then
          break
        fi
        sleep 0.5
      done
      if kill -0 "${PID}" 2>/dev/null; then
        kill -9 "${PID}" 2>/dev/null || true
      fi
    fi
    rm -f "${OLLAMA_PID_FILE}"
    log_success "Host Ollama stopped."
  fi
}

# ------------------------------------------------------------------------------
# Action: Status
# ------------------------------------------------------------------------------
status_services() {
  log_info "Checking Project Titan host control plane status..."
  
  # Ollama status
  if curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log_success "Ollama: RUNNING on http://127.0.0.1:11434"
  else
    log_warn "Ollama: NOT RUNNING on http://127.0.0.1:11434"
  fi

  # Database status
  if check_db_ready; then
    log_success "Database (PostgreSQL): RUNNING on 127.0.0.1:${LITELLM_DB_PORT}"
  else
    log_warn "Database (PostgreSQL): NOT RUNNING on 127.0.0.1:${LITELLM_DB_PORT}"
  fi

  # LiteLLM status
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
    log_success "LiteLLM: RUNNING on http://127.0.0.1:${LITELLM_PORT} (UI: /ui)"
  else
    log_warn "LiteLLM: NOT RUNNING on http://127.0.0.1:${LITELLM_PORT}"
  fi

  # DGX Telemetry Bridge status (ASUS GX10 hardware profile only)
  if is_gx10_hardware && curl -s "http://127.0.0.1:11000" >/dev/null 2>&1; then
    BRIDGE_BIND="${DGX_BRIDGE_BIND:-$(get_docker_gateway)}"
    if curl -s "http://${BRIDGE_BIND}:${DGX_BRIDGE_PORT}" >/dev/null 2>&1; then
      log_success "DGX Bridge: RUNNING on http://${BRIDGE_BIND}:${DGX_BRIDGE_PORT} -> 127.0.0.1:11000"
    else
      log_warn "DGX Bridge: NOT RUNNING on http://${BRIDGE_BIND}:${DGX_BRIDGE_PORT}"
    fi
  fi
}

# ------------------------------------------------------------------------------
# Action: Start
# ------------------------------------------------------------------------------
start_services() {
  log_info "Starting Project Titan host control plane..."

  # 1. Start Ollama if not already responding
  if curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log_info "Ollama is already running on http://127.0.0.1:11434."
  else
    log_info "Starting host Ollama daemon (bound strictly to 127.0.0.1:11434)..."
    OLLAMA_HOST="127.0.0.1:11434" nohup setsid ollama serve </dev/null >"${PID_DIR}/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    disown "${OLLAMA_PID}" 2>/dev/null || true
    echo "${OLLAMA_PID}" > "${OLLAMA_PID_FILE}"
    
    # Wait for Ollama
    READY=false
    for i in {1..30}; do
      if curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
        READY=true
        break
      fi
      sleep 1
    done

    if [ "${READY}" != true ]; then
      log_error "Failed to start Ollama on http://127.0.0.1:11434."
      exit 1
    fi
    log_success "Host Ollama started (PID: ${OLLAMA_PID})."
  fi

  # 2. Verify or start dedicated LiteLLM PostgreSQL database container
  if check_db_ready; then
    log_info "LiteLLM PostgreSQL database is already responding on 127.0.0.1:${LITELLM_DB_PORT}."
  else
    log_info "Starting dedicated LiteLLM PostgreSQL database (titan-litellm-db)..."
    docker compose up -d litellm-db
    
    DB_READY=false
    for i in {1..30}; do
      if check_db_ready; then
        DB_READY=true
        break
      fi
      sleep 1
    done

    if [ "${DB_READY}" != true ]; then
      log_error "Failed to start LiteLLM PostgreSQL database on 127.0.0.1:${LITELLM_DB_PORT}."
      exit 1
    fi
    log_success "LiteLLM PostgreSQL database started and responding."
  fi

  # 3. Start LiteLLM if not already responding
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
    log_info "LiteLLM is already running on http://127.0.0.1:${LITELLM_PORT}."
  else
    if [ ! -x ".venv/bin/litellm" ]; then
      log_error "LiteLLM not found in .venv/bin/litellm. Please run ./scripts/setup-host.sh first."
      exit 1
    fi

    log_info "Starting LiteLLM proxy gateway on port ${LITELLM_PORT}..."
    DATABASE_URL="${DATABASE_URL}" \
    nohup setsid .venv/bin/litellm \
      --config "${REPO_ROOT}/config/litellm/config.yaml" \
      --host "0.0.0.0" \
      --port "${LITELLM_PORT}" \
      --num_workers 1 \
      </dev/null >"${PID_DIR}/litellm.log" 2>&1 &
    LITELLM_PID=$!
    disown "${LITELLM_PID}" 2>/dev/null || true
    echo "${LITELLM_PID}" > "${LITELLM_PID_FILE}"

    # Wait for LiteLLM
    READY=false
    for i in {1..60}; do
      if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
        READY=true
        break
      fi
      sleep 1
    done

    if [ "${READY}" != true ]; then
      log_error "Failed to start LiteLLM on port ${LITELLM_PORT}."
      log_error "Check logs at: ${PID_DIR}/litellm.log"
      exit 1
    fi
    log_success "LiteLLM gateway started (PID: ${LITELLM_PID})."
  fi

  # 4. Provision Hermes virtual key in database if not already provisioned
  if [ -n "${HERMES_LITELLM_KEY}" ] && [ -n "${LITELLM_MASTER_KEY}" ]; then
    KEY_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
      -X GET "http://127.0.0.1:${LITELLM_PORT}/key/info?key=${HERMES_LITELLM_KEY}" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "000")

    if [ "${KEY_CHECK}" != "200" ]; then
      log_info "Registering Hermes virtual key in database..."
      curl -s -o /dev/null \
        -X POST "http://127.0.0.1:${LITELLM_PORT}/key/generate" \
        -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"key\": \"${HERMES_LITELLM_KEY}\", \"key_alias\": \"hermes-agent\", \"models\": []}" || true
      log_success "Hermes virtual key initialized in database."
    else
      log_info "Hermes virtual key is already registered in database."
    fi
  fi

  # 5. Start DGX Telemetry Reverse Proxy Bridge (ASUS GX10 appliance profile only)
  if is_gx10_hardware && curl -s "http://127.0.0.1:11000" >/dev/null 2>&1; then
    BRIDGE_BIND="${DGX_BRIDGE_BIND:-$(get_docker_gateway)}"
    if curl -s "http://${BRIDGE_BIND}:${DGX_BRIDGE_PORT}" >/dev/null 2>&1; then
      log_info "DGX Telemetry bridge is already running on ${BRIDGE_BIND}:${DGX_BRIDGE_PORT}."
    else
      if command -v socat >/dev/null 2>&1; then
        log_info "Starting DGX Telemetry reverse proxy bridge on ${BRIDGE_BIND}:${DGX_BRIDGE_PORT}..."
        nohup setsid socat "TCP-LISTEN:${DGX_BRIDGE_PORT},fork,reuseaddr,bind=${BRIDGE_BIND}" "TCP:127.0.0.1:11000" \
          </dev/null >"${PID_DIR}/dgx_bridge.log" 2>&1 &
        DGX_BRIDGE_PID=$!
        disown "${DGX_BRIDGE_PID}" 2>/dev/null || true
        echo "${DGX_BRIDGE_PID}" > "${DGX_BRIDGE_PID_FILE}"
        log_success "DGX Telemetry bridge started (PID: ${DGX_BRIDGE_PID}, bound to ${BRIDGE_BIND})."
      else
        log_warn "socat is not installed; DGX Telemetry bridge cannot be started."
      fi
    fi
  fi

  status_services
}

case "${1:-start}" in
  start)
    start_services
    ;;
  stop)
    stop_services
    ;;
  status)
    status_services
    ;;
  restart)
    stop_services
    sleep 2
    start_services
    ;;
  *)
    echo "Usage: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
