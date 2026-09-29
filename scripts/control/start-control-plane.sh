#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Native Host Control Plane Service Manager
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
  if [ -n "${GITHUB_TOKEN_CINDY:-}" ] && [ -z "${GITHUB_BASIC_AUTH_CINDY:-}" ]; then
    GITHUB_BASIC_AUTH_CINDY="$(printf 'x-access-token:%s' "${GITHUB_TOKEN_CINDY}" | base64 | tr -d '\r\n')"
    export GITHUB_BASIC_AUTH_CINDY
    if grep -q "^GITHUB_BASIC_AUTH_CINDY=" .env; then
      sed -i.bak "s|^GITHUB_BASIC_AUTH_CINDY=.*|GITHUB_BASIC_AUTH_CINDY=${GITHUB_BASIC_AUTH_CINDY}|" .env && rm -f .env.bak
    else
      echo "GITHUB_BASIC_AUTH_CINDY=${GITHUB_BASIC_AUTH_CINDY}" >> .env
    fi
  fi
fi

PID_DIR="${REPO_ROOT}/data/control_plane"
mkdir -p "${PID_DIR}"

OLLAMA_PID_FILE="${PID_DIR}/ollama.pid"
LITELLM_PID_FILE="${PID_DIR}/litellm.pid"
DGX_BRIDGE_PID_FILE="${PID_DIR}/dgx_bridge.pid"
QUEUE_WORKER_PID_FILE="${PID_DIR}/queue_worker.pid"
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_DB_PORT="${LITELLM_DB_PORT:-5432}"
DGX_BRIDGE_PORT="${DGX_BRIDGE_PORT:-11001}"
DGX_BRIDGE_BIND="${DGX_BRIDGE_BIND:-}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
HERMES_LITELLM_KEY="${HERMES_LITELLM_KEY:-}"
DATABASE_URL="${DATABASE_URL:-}"
INFERENCE_NUM_CTX="${INFERENCE_NUM_CTX:-4096}"

SETSID_CMD=""
if command -v setsid >/dev/null 2>&1; then
  SETSID_CMD="setsid"
fi

# Observability Plane (Langfuse & OpenTelemetry)
LANGFUSE_AUTO_START="${LANGFUSE_AUTO_START:-false}"
LANGFUSE_PORT="${LANGFUSE_PORT:-3001}"
LANGFUSE_HOST="${LANGFUSE_HOST:-http://langfuse.brainsos.local:${LANGFUSE_PORT}}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
LANGFUSE_OTEL_AUTH="${LANGFUSE_OTEL_AUTH:-}"

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
  log_info "Stopping brainsOS host control plane..."
  
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

  # Stop Unified Queue Worker if running
  if [ -f "${QUEUE_WORKER_PID_FILE}" ]; then
    PID=$(cat "${QUEUE_WORKER_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping Unified Queue Worker (PID: ${PID})..."
      kill "${PID}" 2>/dev/null || true
    fi
    rm -f "${QUEUE_WORKER_PID_FILE}"
    log_success "Unified Queue Worker stopped."
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

  # Stop local Langfuse stack only if explicitly requested (e.g., STOP_LANGFUSE=true)
  if [[ "${STOP_LANGFUSE:-false}" =~ ^(true|1|yes)$ ]]; then
    log_info "Stopping local Langfuse container stack..."
    "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" stop 2>/dev/null || true
  fi
}

# ------------------------------------------------------------------------------
# Action: Status
# ------------------------------------------------------------------------------
status_services() {
  log_info "Checking brainsOS host control plane status..."
  
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

  # Langfuse Observability status
  LOCAL_LF_BODY=$(curl -s "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || true)
  REMOTE_LF_BODY=$(curl -s "${LANGFUSE_HOST}/api/public/health" 2>/dev/null || true)

  if [ -n "${LOCAL_LF_BODY}" ] && echo "${LOCAL_LF_BODY}" | grep -q '"status":"OK"'; then
    log_success "Langfuse: RUNNING locally on http://localhost:${LANGFUSE_PORT} (http://langfuse.brainsos.local:${LANGFUSE_PORT})"
  elif [ -n "${REMOTE_LF_BODY}" ] && echo "${REMOTE_LF_BODY}" | grep -q '"status":"OK"'; then
    log_success "Langfuse: RUNNING remotely at ${LANGFUSE_HOST}"
  else
    log_info "Langfuse: NOT RUNNING (LANGFUSE_AUTO_START=${LANGFUSE_AUTO_START})"
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

  # Unified Queue Worker status
  if [ -f "${QUEUE_WORKER_PID_FILE}" ] && kill -0 "$(cat "${QUEUE_WORKER_PID_FILE}")" 2>/dev/null; then
    log_success "Queue Worker: RUNNING (PID: $(cat "${QUEUE_WORKER_PID_FILE}"))"
  else
    log_info "Queue Worker: NOT RUNNING"
  fi

  # Shared Stateless Hermes Runner status
  if docker compose ps hermes-runner 2>/dev/null | grep -qE "(Up|running)"; then
    log_success "Hermes Runner: RUNNING (brainsos-agent-hermes-runner:8642)"
  else
    log_info "Hermes Runner: NOT RUNNING (Run: docker compose up -d hermes-runner)"
  fi
}

# ------------------------------------------------------------------------------
# Action: Start
# ------------------------------------------------------------------------------
start_services() {
  log_info "Starting brainsOS host control plane..."

  # 1. Start Ollama if not already responding
  if curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log_info "Ollama is already running on http://127.0.0.1:11434."
  else
    log_info "Starting host Ollama daemon (bound strictly to 127.0.0.1:11434)..."
    OLLAMA_HOST="127.0.0.1:11434" nohup ${SETSID_CMD} ollama serve </dev/null >"${PID_DIR}/ollama.log" 2>&1 &
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
    log_info "Starting dedicated LiteLLM PostgreSQL database (brainsos-infra-litellm-db)..."
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

  # 2.5. Optional: Start Langfuse Observability Stack if LANGFUSE_AUTO_START is enabled
  if [[ "${LANGFUSE_AUTO_START}" =~ ^(true|1|yes)$ ]]; then
    if curl -s "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null | grep -q '"status":"OK"' || \
       curl -s "http://localhost:3001/api/public/health" 2>/dev/null | grep -q '"status":"OK"'; then
      log_info "Langfuse observability stack is already running."
    else
      log_info "LANGFUSE_AUTO_START=true: Launching Langfuse observability stack..."
      "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" start
    fi
  fi

  # Dynamic LiteLLM Observability Configuration
  LITELLM_SUCCESS_CALLBACKS=""
  LITELLM_FAILURE_CALLBACKS=""
  OTEL_EXPORTER_OTLP_ENDPOINT=""
  OTEL_EXPORTER_OTLP_HEADERS=""

  if [ -n "${LANGFUSE_PUBLIC_KEY}" ] && [ -n "${LANGFUSE_SECRET_KEY}" ]; then
    LITELLM_SUCCESS_CALLBACKS="langfuse,otel"
    LITELLM_FAILURE_CALLBACKS="langfuse,otel"
    
    # Resolve host-level endpoint: if LANGFUSE_HOST points to brainsos.local and does not resolve natively on host, use loopback
    HOST_LANGFUSE_URL="${LANGFUSE_HOST}"
    if [[ "${HOST_LANGFUSE_URL}" == *"langfuse.brainsos.local"* ]] && ! curl -s -m 1 "${HOST_LANGFUSE_URL}/api/public/health" >/dev/null 2>&1; then
      HOST_LANGFUSE_URL="http://127.0.0.1:${LANGFUSE_PORT}"
    fi

    OTEL_EXPORTER_OTLP_ENDPOINT="${HOST_LANGFUSE_URL}/api/public/otel"
    if [ -z "${LANGFUSE_OTEL_AUTH}" ] || [ "${LANGFUSE_OTEL_AUTH}" = "Basic" ] || [[ "${LANGFUSE_OTEL_AUTH}" != *" "* ]]; then
      LANGFUSE_OTEL_AUTH="Basic $(echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64 | tr -d '\r\n')"
    fi
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=${LANGFUSE_OTEL_AUTH}"
    log_info "LiteLLM Observability: ENABLED (Langfuse & OTel -> ${HOST_LANGFUSE_URL})"
  else
    log_info "LiteLLM Observability: STANDBY (LANGFUSE_PUBLIC_KEY unset)"
  fi

  # 3. Start LiteLLM if not already responding
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
    log_info "LiteLLM is already running on http://127.0.0.1:${LITELLM_PORT}."
  else
    if [ ! -x ".venv/bin/litellm" ]; then
      log_error "LiteLLM not found in .venv/bin/litellm. Please run ./scripts/setup/setup-host.sh first."
      exit 1
    fi

    log_info "Starting LiteLLM proxy gateway on port ${LITELLM_PORT}..."
    DATABASE_URL="${DATABASE_URL}" \
    LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}" \
    LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}" \
    LANGFUSE_HOST="${HOST_LANGFUSE_URL:-${LANGFUSE_HOST}}" \
    LANGFUSE_BASE_URL="${HOST_LANGFUSE_URL:-${LANGFUSE_HOST}}" \
    LITELLM_SUCCESS_CALLBACKS="${LITELLM_SUCCESS_CALLBACKS}" \
    LITELLM_FAILURE_CALLBACKS="${LITELLM_FAILURE_CALLBACKS}" \
    OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}" \
    OTEL_EXPORTER_OTLP_HEADERS="${OTEL_EXPORTER_OTLP_HEADERS}" \
    nohup ${SETSID_CMD} .venv/bin/litellm \
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
    for i in {1..90}; do
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

  # 4. Provision fleet virtual keys in LiteLLM control plane database
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
    fi
  fi

  # 5. Start Shared Stateless Hermes Agent Runner container
  log_info "Ensuring shared stateless Hermes runner (hermes-runner) is running..."
  docker compose up -d hermes-runner 2>/dev/null || log_warn "Could not start hermes-runner container (Docker may be inactive)."

  # 6. Start Unified Asynchronous Queue Worker
  if [ -f "${QUEUE_WORKER_PID_FILE}" ] && kill -0 "$(cat "${QUEUE_WORKER_PID_FILE}")" 2>/dev/null; then
    log_info "Unified Queue Worker is already running (PID: $(cat "${QUEUE_WORKER_PID_FILE}"))."
  else
    log_info "Starting Unified Asynchronous Queue Worker..."
    PYTHONPATH="${REPO_ROOT}/packages/brainsOS-mail:${REPO_ROOT}/packages/brainsOS-queue:${REPO_ROOT}/packages/brainsOS-agent:${REPO_ROOT}/packages/brainsOS-telemetry:${PYTHONPATH:-}" \
    nohup ${SETSID_CMD} .venv/bin/python -m brainsos_agent.worker </dev/null >"${PID_DIR}/queue_worker.log" 2>&1 &
    QUEUE_WORKER_PID=$!
    disown "${QUEUE_WORKER_PID}" 2>/dev/null || true
    echo "${QUEUE_WORKER_PID}" > "${QUEUE_WORKER_PID_FILE}"
    log_success "Unified Queue Worker started (PID: ${QUEUE_WORKER_PID})."
  fi

  # 5. Start DGX Telemetry Reverse Proxy Bridge (ASUS GX10 appliance profile only)
  if is_gx10_hardware && curl -s "http://127.0.0.1:11000" >/dev/null 2>&1; then
    BRIDGE_BIND="${DGX_BRIDGE_BIND:-$(get_docker_gateway)}"
    if curl -s "http://${BRIDGE_BIND}:${DGX_BRIDGE_PORT}" >/dev/null 2>&1; then
      log_info "DGX Telemetry bridge is already running on ${BRIDGE_BIND}:${DGX_BRIDGE_PORT}."
    else
      if command -v socat >/dev/null 2>&1; then
        log_info "Starting DGX Telemetry reverse proxy bridge on ${BRIDGE_BIND}:${DGX_BRIDGE_PORT}..."
        nohup ${SETSID_CMD} socat "TCP-LISTEN:${DGX_BRIDGE_PORT},fork,reuseaddr,bind=${BRIDGE_BIND}" "TCP:127.0.0.1:11000" \
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
