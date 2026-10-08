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

PID_DIR="${BRAINSOS_CONTROL_PLANE_DIR:-${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/control_plane}"
mkdir -p "${PID_DIR}"

OLLAMA_PID_FILE="${PID_DIR}/ollama.pid"
LITELLM_PID_FILE="${PID_DIR}/litellm.pid"
DGX_BRIDGE_PID_FILE="${PID_DIR}/dgx_bridge.pid"
QUEUE_WORKER_PID_FILE="${PID_DIR}/queue_worker.pid"
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_DB_PORT="${LITELLM_DB_PORT:-5432}"
DGX_BRIDGE_PORT="${DGX_BRIDGE_PORT:-11001}"
DGX_BRIDGE_BIND="${DGX_BRIDGE_BIND:-}"
BRAINSOS_INGRESS_PORT="${BRAINSOS_INGRESS_PORT:-8000}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
HERMES_LITELLM_KEY="${HERMES_LITELLM_KEY:-}"
OPERATOR_LITELLM_KEY="${OPERATOR_LITELLM_KEY:-}"
TERRASTELLA_LITELLM_KEY="${TERRASTELLA_LITELLM_KEY:-}"
MARVIN_LITELLM_KEY="${MARVIN_LITELLM_KEY:-}"
BAWTFORD_LITELLM_KEY="${BAWTFORD_LITELLM_KEY:-}"
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

# Ensure .venv/bin is in PATH for dev tools
export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
export DATABASE_URL="${DATABASE_URL}"
export INFERENCE_NUM_CTX="${INFERENCE_NUM_CTX}"
export BRAINSOS_CORE_MODEL="${BRAINSOS_CORE_MODEL:-ollama_chat/llama3.2:3b}"

# Helper to detect Docker bridge gateway IP
get_docker_gateway() {
  local gw
  gw=$(ip -4 addr show docker0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 || true)
  echo "${gw:-172.17.0.1}"
}

# Helper to check if LiteLLM database container is running and healthy (Rule 6: isolated on brainsos-litellm-net)
check_db_ready() {
  local status
  status=$(docker inspect --format '{{.State.Health.Status}}' brainsos-infra-litellm-db 2>/dev/null || true)
  if [ "${status}" = "healthy" ]; then
    return 0
  fi
  docker compose exec -T litellm-db pg_isready -U "${LITELLM_DB_USER:-litellm}" -d "${LITELLM_DB_NAME:-litellm}" >/dev/null 2>&1
}

# Helper to check if containerized LiteLLM gateway is responding
check_litellm_ready() {
  curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'
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
  
  # 1. Stop containerized LiteLLM gateway
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "brainsos-infra-litellm"; then
    log_info "Stopping containerized LiteLLM gateway..."
    docker compose stop litellm 2>/dev/null || true
    log_success "LiteLLM stopped."
  fi

  # Fallback: terminate legacy host PID if present
  if [ -f "${LITELLM_PID_FILE}" ]; then
    PID=$(cat "${LITELLM_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping legacy host LiteLLM (PID: ${PID})..."
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
  fi

  # Fallback: terminate any residual host process on LITELLM_PORT (excluding docker containers)
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS=$(lsof -ti :"${LITELLM_PORT}" 2>/dev/null || true)
    if [ -n "${PORT_PIDS}" ]; then
      for p in ${PORT_PIDS}; do
        if ! ps -p "${p}" -o comm= 2>/dev/null | grep -qE "(docker|containerd)"; then
          log_info "Stopping residual host process on port ${LITELLM_PORT} (PID: ${p})..."
          kill "${p}" 2>/dev/null || true
        fi
      done
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

  if command -v lsof >/dev/null 2>&1; then
    INGRESS_PIDS=$(lsof -ti :"${BRAINSOS_INGRESS_PORT}" 2>/dev/null || true)
    if [ -n "${INGRESS_PIDS}" ]; then
      for p in ${INGRESS_PIDS}; do kill "${p}" 2>/dev/null || true; done
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

  # Database status (Rule 6: isolated on brainsos-litellm-net)
  if check_db_ready; then
    log_success "Database (PostgreSQL): RUNNING (brainsos-infra-litellm-db: healthy, Rule 6 isolated)"
  else
    log_warn "Database (PostgreSQL): NOT RUNNING (brainsos-infra-litellm-db)"
  fi

  # LiteLLM status (Containerized)
  if check_litellm_ready; then
    log_success "LiteLLM: RUNNING (brainsos-infra-litellm on http://127.0.0.1:${LITELLM_PORT})"
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

  # Unified Queue Worker & Ingress status
  if [ -f "${QUEUE_WORKER_PID_FILE}" ] && kill -0 "$(cat "${QUEUE_WORKER_PID_FILE}")" 2>/dev/null; then
    if curl -s "http://127.0.0.1:${BRAINSOS_INGRESS_PORT}/health/liveness" >/dev/null 2>&1; then
      log_success "Queue Worker & Ingress: RUNNING (PID: $(cat "${QUEUE_WORKER_PID_FILE}"), http://127.0.0.1:${BRAINSOS_INGRESS_PORT})"
    else
      log_success "Queue Worker: RUNNING (PID: $(cat "${QUEUE_WORKER_PID_FILE}"))"
    fi
  else
    log_info "Queue Worker: NOT RUNNING"
  fi

  # Shared Stateless Hermes Runner status
  if docker compose ps runner-hermes 2>/dev/null | grep -qE "(Up|running)"; then
    log_success "Hermes Runner: RUNNING (runner-hermes:8642)"
  else
    log_info "Hermes Runner: NOT RUNNING (Run: docker compose up -d runner-hermes)"
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

  # 1.5. Ensure required LLM weights are seeded in Ollama
  if [ -f "${REPO_ROOT}/scripts/setup/setup-models.sh" ]; then
    log_info "Verifying required LLM model weights in Ollama..."
    "${REPO_ROOT}/scripts/setup/setup-models.sh" || log_warn "Model seeding encountered a warning."
  fi

  # 2. Verify or start dedicated LiteLLM PostgreSQL database container (Rule 6: isolated)
  if check_db_ready; then
    log_info "LiteLLM PostgreSQL database is already responding (brainsos-infra-litellm-db)."
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
      log_error "Failed to start LiteLLM PostgreSQL database container (brainsos-infra-litellm-db)."
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

  # 3. Verify or start containerized LiteLLM gateway
  if check_litellm_ready; then
    log_info "LiteLLM gateway is already running on http://127.0.0.1:${LITELLM_PORT}."
  else
    log_info "Starting containerized LiteLLM gateway (brainsos-infra-litellm)..."
    docker compose up -d litellm

    READY=false
    for i in {1..45}; do
      if check_litellm_ready; then
        READY=true
        break
      fi
      sleep 1
    done

    if [ "${READY}" != true ]; then
      log_error "Failed to start LiteLLM on port ${LITELLM_PORT}."
      log_error "Check container logs with: docker compose logs litellm"
      exit 1
    fi
    log_success "LiteLLM gateway started."
  fi

  # 4. Provision fleet virtual keys in LiteLLM control plane database
  if [ -n "${LITELLM_MASTER_KEY}" ]; then
    provision_vkey() {
      local key="$1"
      local alias="$2"
      local budget="${3:-}"
      [ -z "${key}" ] && return 0

      local key_check
      key_check=$(curl -s -o /dev/null -w "%{http_code}" \
        -X GET "http://127.0.0.1:${LITELLM_PORT}/key/info?key=${key}" \
        -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "000")

      if [ "${key_check}" != "200" ]; then
        log_info "Registering LiteLLM virtual key '${alias}' in database..."
        local payload
        if [ -n "${budget}" ]; then
          payload="{\"key\": \"${key}\", \"key_alias\": \"${alias}\", \"max_budget\": ${budget}, \"models\": []}"
        else
          payload="{\"key\": \"${key}\", \"key_alias\": \"${alias}\", \"models\": []}"
        fi
        curl -s -o /dev/null \
          -X POST "http://127.0.0.1:${LITELLM_PORT}/key/generate" \
          -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
          -H "Content-Type: application/json" \
          -d "${payload}" || true
        log_success "LiteLLM virtual key '${alias}' initialized in database."
      fi
    }

    provision_vkey "${OPERATOR_LITELLM_KEY}" "brainsos-operator" 100.0
    provision_vkey "${TERRASTELLA_LITELLM_KEY}" "brainsos-terrastella"
    provision_vkey "${MARVIN_LITELLM_KEY}" "brainsos-marvin"
    provision_vkey "${BAWTFORD_LITELLM_KEY}" "brainsos-bawtford"
    provision_vkey "${HERMES_LITELLM_KEY}" "hermes-agent"
  fi

  # 5. Start Shared Stateless Hermes Agent Runner container
  log_info "Ensuring shared stateless Hermes runner (runner-hermes) is running..."
  docker compose up -d runner-hermes 2>/dev/null || log_warn "Could not start runner-hermes container (Docker may be inactive)."

  # 6. Start Unified Asynchronous Queue Worker & Mail Ingress
  if [ -f "${QUEUE_WORKER_PID_FILE}" ] && kill -0 "$(cat "${QUEUE_WORKER_PID_FILE}")" 2>/dev/null; then
    log_info "Unified Queue Worker is already running (PID: $(cat "${QUEUE_WORKER_PID_FILE}"))."
  else
    log_info "Starting Unified Asynchronous Queue Worker & Mail Ingress (port ${BRAINSOS_INGRESS_PORT})..."
    BRAINSOS_INGRESS_PORT="${BRAINSOS_INGRESS_PORT}" \
    PYTHONPATH="${REPO_ROOT}/packages/brainsOS-mail:${REPO_ROOT}/packages/brainsOS-queue:${REPO_ROOT}/packages/brainsOS-agent:${REPO_ROOT}/packages/brainsOS-telemetry:${PYTHONPATH:-}" \
    nohup ${SETSID_CMD} .venv/bin/python -m brainsos_agent.worker </dev/null >"${PID_DIR}/queue_worker.log" 2>&1 &
    QUEUE_WORKER_PID=$!
    disown "${QUEUE_WORKER_PID}" 2>/dev/null || true
    echo "${QUEUE_WORKER_PID}" > "${QUEUE_WORKER_PID_FILE}"

    # Wait for Ingress HTTP readiness
    READY=false
    for i in {1..30}; do
      if curl -s "http://127.0.0.1:${BRAINSOS_INGRESS_PORT}/health/liveness" >/dev/null 2>&1; then
        READY=true
        break
      fi
      sleep 0.5
    done
    if [ "${READY}" = true ]; then
      log_success "Unified Queue Worker & Mail Ingress started (PID: ${QUEUE_WORKER_PID}, port ${BRAINSOS_INGRESS_PORT})."
    else
      log_warn "Queue Worker started (PID: ${QUEUE_WORKER_PID}), ingress endpoint still pending."
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
