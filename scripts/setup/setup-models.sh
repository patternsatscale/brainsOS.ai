#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Host Model Seeding & Ollama Synchronization Script
# Idempotently pulls, verifies, and synchronizes required LLM weights in Ollama.
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
    if [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Load active .env if present
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  . "${REPO_ROOT}/.env"
  set +a
fi

OLLAMA_PORT="${OLLAMA_PORT:-11434}"
OLLAMA_HOST_URL="http://127.0.0.1:${OLLAMA_PORT}"

# Parse CLI arguments
CHECK_ONLY=false
PULL_ALL=false
SPECIFIC_MODEL=""

show_help() {
  echo -e "${BOLD}brainsOS Ollama Model Management${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --check               Probe and display current model status without pulling"
  echo "  --all                 Pull all standard brainsOS models (core, coding, fallback)"
  echo "  --model <name>        Pull a specific model by name (e.g. llama3.2:3b)"
  echo "  -h, --help            Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY=true
      shift
      ;;
    --all)
      PULL_ALL=true
      shift
      ;;
    --model)
      SPECIFIC_MODEL="$2"
      shift 2
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_warn "Unknown option: $1 (ignoring)"
      shift
      ;;
  esac
done

# Ensure ollama CLI is available on host
if ! command -v ollama >/dev/null 2>&1; then
  log_error "Ollama CLI ('ollama') is not installed or not in PATH."
  log_error "Please install Ollama on the host: curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi

# Ensure Ollama daemon is running
ensure_ollama_running() {
  if curl -s "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1; then
    return 0
  fi

  log_info "Ollama daemon not responding on ${OLLAMA_HOST_URL}. Starting in background..."
  local pid_dir="${BRAINSOS_CONTROL_PLANE_DIR:-${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/control_plane}"
  mkdir -p "${pid_dir}"

  OLLAMA_HOST="127.0.0.1:${OLLAMA_PORT}" nohup ollama serve >"${pid_dir}/ollama.log" 2>&1 &
  local pid=$!
  echo "${pid}" > "${pid_dir}/ollama.pid"
  disown "${pid}" 2>/dev/null || true

  for i in {1..30}; do
    if curl -s "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1; then
      log_success "Ollama daemon started (PID: ${pid})."
      return 0
    fi
    sleep 1
  done

  log_error "Timed out waiting for host Ollama service to become ready on ${OLLAMA_HOST_URL}."
  return 1
}

if ! ensure_ollama_running; then
  exit 1
fi

# Helper: check if a model exists in Ollama
model_is_present() {
  local target="$1"
  # Clean tag matching: match "target" or "target:latest"
  local clean_target="${target%:latest}"
  local tags_json
  tags_json=$(curl -s "${OLLAMA_HOST_URL}/api/tags" 2>/dev/null || echo "{}")
  if echo "${tags_json}" | grep -qE "\"name\": *\"(${target}|${clean_target}:latest|${clean_target})\""; then
    return 0
  fi
  return 1
}

# Determine target models to verify/pull
MODELS_TO_VERIFY=()

if [ -n "${SPECIFIC_MODEL}" ]; then
  MODELS_TO_VERIFY+=("${SPECIFIC_MODEL}")
elif [ "${PULL_ALL}" = true ]; then
  MODELS_TO_VERIFY+=("llama3.2:3b" "qwen2.5:latest" "gemma2:2b")
else
  # Default: derive from BRAINSOS_CORE_MODEL and INFERENCE_MODEL
  RAW_CORE_MODEL="${BRAINSOS_CORE_MODEL:-ollama_chat/llama3.2:3b}"
  CORE_MODEL="${RAW_CORE_MODEL#ollama_chat/}"
  CORE_MODEL="${CORE_MODEL#ollama/}"
  MODELS_TO_VERIFY+=("${CORE_MODEL}")

  RAW_INF_MODEL="${INFERENCE_MODEL:-}"
  if [ -n "${RAW_INF_MODEL}" ]; then
    INF_MODEL="${RAW_INF_MODEL#ollama_chat/}"
    INF_MODEL="${INF_MODEL#ollama/}"
    if [ "${INF_MODEL}" != "${CORE_MODEL}" ]; then
      MODELS_TO_VERIFY+=("${INF_MODEL}")
    fi
  fi
fi

echo -e "${BOLD}brainsOS Ollama Model Synchronization${NC}"
echo -e "Ollama Endpoint: ${OLLAMA_HOST_URL}"
echo -e "Target Models:   ${MODELS_TO_VERIFY[*]}"
echo ""

ALL_READY=true

for model in "${MODELS_TO_VERIFY[@]}"; do
  if model_is_present "${model}"; then
    log_success "Model '${model}' is ready in local Ollama."
  else
    ALL_READY=false
    if [ "${CHECK_ONLY}" = true ]; then
      log_warn "Model '${model}' is MISSING from local Ollama."
    else
      log_info "Pulling model '${model}' natively into Ollama..."
      if ollama pull "${model}"; then
        log_success "Successfully seeded model: ${model}"
      else
        log_error "Failed to pull model '${model}' into Ollama!"
        exit 1
      fi
    fi
  fi
done

echo ""
log_info "Current local models in Ollama:"
ollama list

if [ "${ALL_READY}" = true ]; then
  echo ""
  log_success "All required models are present and ready in Ollama!"
  exit 0
else
  if [ "${CHECK_ONLY}" = true ]; then
    echo ""
    log_warn "One or more target models are missing. Run './scripts/setup/setup-models.sh' to pull."
    exit 1
  else
    echo ""
    log_success "Model synchronization completed successfully."
    exit 0
  fi
fi
