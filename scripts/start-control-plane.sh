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
LITELLM_PORT="${LITELLM_PORT:-4000}"

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
    fi
    rm -f "${LITELLM_PID_FILE}"
    log_success "LiteLLM stopped."
  fi

  if [ -f "${OLLAMA_PID_FILE}" ]; then
    PID=$(cat "${OLLAMA_PID_FILE}")
    if kill -0 "${PID}" 2>/dev/null; then
      log_info "Stopping host Ollama (PID: ${PID})..."
      kill "${PID}" || true
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

  # LiteLLM status
  if curl -s "http://127.0.0.1:${LITELLM_PORT}/health" >/dev/null 2>&1; then
    log_success "LiteLLM: RUNNING on http://127.0.0.1:${LITELLM_PORT}"
  else
    log_warn "LiteLLM: NOT RUNNING on http://127.0.0.1:${LITELLM_PORT}"
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
    OLLAMA_HOST="127.0.0.1:11434" ollama serve >"${PID_DIR}/ollama.log" 2>&1 &
    OLLAMA_PID=$!
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

  # 2. Start LiteLLM if not already responding
  if curl -s "http://127.0.0.1:${LITELLM_PORT}/health" >/dev/null 2>&1; then
    log_info "LiteLLM is already running on http://127.0.0.1:${LITELLM_PORT}."
  else
    if [ ! -x ".venv/bin/litellm" ]; then
      log_error "LiteLLM not found in .venv/bin/litellm. Please run ./scripts/setup-host.sh first."
      exit 1
    fi

    log_info "Starting LiteLLM proxy gateway on port ${LITELLM_PORT}..."
    .venv/bin/litellm \
      --config "${REPO_ROOT}/config/litellm/config.yaml" \
      --host "0.0.0.0" \
      --port "${LITELLM_PORT}" \
      --num_workers 1 \
      >"${PID_DIR}/litellm.log" 2>&1 &
    LITELLM_PID=$!
    echo "${LITELLM_PID}" > "${LITELLM_PID_FILE}"

    # Wait for LiteLLM
    READY=false
    for i in {1..30}; do
      if curl -s "http://127.0.0.1:${LITELLM_PORT}/health" >/dev/null 2>&1; then
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
