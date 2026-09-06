#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Idempotent Host Baseline Setup Script
# Configures host dependencies, native inference (Ollama), LiteLLM control plane,
# memory storage directories, and model seeding across macOS and Ubuntu/DGX OS.
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

PULL_MODEL=false
for arg in "$@"; do
  case "$arg" in
    --pull-model)
      PULL_MODEL=true
      shift
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log_info "Initializing Project Titan host baseline from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 1. OS & Architecture Detection
# ------------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
log_info "Detected OS: ${OS} (${ARCH})"

if [[ "${OS}" == "Linux" ]]; then
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    log_info "Linux Distribution: ${NAME:-Linux} ${VERSION_ID:-}"
  fi

  # DGX OS / Ubuntu Hardware Package Pinning on ASUS GX10
  if command -v apt-mark >/dev/null 2>&1; then
    log_info "Enforcing package holds on NVIDIA drivers and container toolkits..."
    for pkg in linux-nvidia-hwe-24.04 nvidia-container-toolkit; do
      if dpkg -l "${pkg}" >/dev/null 2>&1; then
        sudo apt-mark hold "${pkg}"
        log_success "Held package: ${pkg}"
      else
        log_warn "Package ${pkg} not yet installed; skipping hold."
      fi
    done
  fi

  # Native Ollama installation on Linux (Ubuntu / DGX OS)
  if ! command -v ollama >/dev/null 2>&1; then
    log_info "Installing native Ollama on Linux host..."
    curl -fsSL https://ollama.com/install.sh | sh
    log_success "Ollama installed on Linux."
  else
    log_info "Ollama is already installed on host."
  fi

elif [[ "${OS}" == "Darwin" ]]; then
  log_info "Running on macOS (${ARCH}). Skipping Linux-specific apt holds."

  # Native Ollama installation on macOS
  if ! command -v ollama >/dev/null 2>&1; then
    log_info "Ollama not found. Checking Homebrew..."
    if command -v brew >/dev/null 2>&1; then
      log_info "Installing Ollama via Homebrew..."
      brew install ollama
      log_success "Ollama installed via Homebrew."
    else
      log_error "Homebrew is not installed. Please install Ollama from https://ollama.com or install Homebrew."
      exit 1
    fi
  else
    log_info "Ollama is already installed on macOS host."
  fi
fi

# Verify Ollama is available
if ! command -v ollama >/dev/null 2>&1; then
  log_error "Ollama could not be located in PATH."
  exit 1
fi
log_success "Ollama verified: $(ollama --version 2>/dev/null || echo 'installed')"

# ------------------------------------------------------------------------------
# 2. Python Environment & LiteLLM Gateway Setup
# ------------------------------------------------------------------------------
cd "${REPO_ROOT}"

# Locate or install `uv` for ultra-fast, reproducible python virtual environment
UV_BIN=""
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "${HOME}/.local/bin/uv" ]; then
  UV_BIN="${HOME}/.local/bin/uv"
elif [ -x "/usr/local/bin/uv" ]; then
  UV_BIN="/usr/local/bin/uv"
elif [ -x "/opt/homebrew/bin/uv" ]; then
  UV_BIN="/opt/homebrew/bin/uv"
fi

if [ -z "${UV_BIN}" ]; then
  log_info "Installing uv for Python environment management..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  if [ -x "${HOME}/.local/bin/uv" ]; then
    UV_BIN="${HOME}/.local/bin/uv"
  fi
fi

if [ -n "${UV_BIN}" ] && [ -x "${UV_BIN}" ]; then
  log_info "Using uv (${UV_BIN}) to manage LiteLLM virtualenv..."
  if [ ! -d ".venv" ]; then
    log_info "Creating .venv virtual environment..."
    "${UV_BIN}" venv .venv
  fi
  log_info "Ensuring 'litellm[proxy]' and 'prisma' are installed in .venv..."
  "${UV_BIN}" pip install --python .venv/bin/python "litellm[proxy]" "prisma" >/dev/null 2>&1
else
  log_info "Using system python3 to manage LiteLLM virtualenv..."
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  .venv/bin/pip install --upgrade pip >/dev/null 2>&1 || true
  .venv/bin/pip install "litellm[proxy]" "prisma" >/dev/null 2>&1
fi

if [ -x ".venv/bin/litellm" ]; then
  log_success "LiteLLM control plane gateway installed in .venv."
else
  log_error "Failed to verify LiteLLM binary in .venv/bin/litellm"
  exit 1
fi

# Pre-generate Prisma client Python bindings for LiteLLM database operations
LITELLM_SCHEMA=$(find .venv -name "schema.prisma" 2>/dev/null | head -n 1)
if [ -n "${LITELLM_SCHEMA}" ] && [ -f "${LITELLM_SCHEMA}" ]; then
  log_info "Pre-generating Prisma client bindings from ${LITELLM_SCHEMA}..."
  PATH="${REPO_ROOT}/.venv/bin:${PATH}" .venv/bin/prisma generate --schema "${LITELLM_SCHEMA}" >/dev/null 2>&1 || true
  log_success "Prisma client bindings pre-generated."
fi

# ------------------------------------------------------------------------------
# 3. Docker & Docker Compose Verification
# ------------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log_error "Docker is not installed or not in PATH. Please install Docker first."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  log_error "Docker Compose (v2) is not installed. Please install docker-compose-plugin."
  exit 1
fi
log_success "Docker and Docker Compose verified."

log_info "Ensuring PostgreSQL 16 Alpine container is cached..."
docker pull postgres:16-alpine >/dev/null 2>&1 || log_warn "Failed to pre-pull postgres:16-alpine (will pull during launch)."

# ------------------------------------------------------------------------------
# 4. Environment Template Verification
# ------------------------------------------------------------------------------
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    log_info "Creating .env from .env.example..."
    cp .env.example .env
    log_success "Created .env configuration file."
  else
    log_error ".env.example not found."
    exit 1
  fi
else
  log_info ".env file already exists."
fi

# ------------------------------------------------------------------------------
# 5. Storage Directories & Permissions Setup
# ------------------------------------------------------------------------------
DATA_DIR=$(grep -E '^TITAN_DATA_DIR=' .env 2>/dev/null | cut -d '=' -f2- || echo "./data/memories")
DATA_DIR="${DATA_DIR:-./data/memories}"

if [[ "$DATA_DIR" != /* ]]; then
  TARGET_MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  TARGET_MEMORIES_DIR="${DATA_DIR}"
fi

log_info "Target OKF memories directory: ${TARGET_MEMORIES_DIR}"

if [[ "$TARGET_MEMORIES_DIR" == /data/titan/* ]]; then
  log_info "Creating production system path with sudo: ${TARGET_MEMORIES_DIR}..."
  sudo mkdir -p "${TARGET_MEMORIES_DIR}"
  sudo chown -R 1000:1000 "${TARGET_MEMORIES_DIR}"
  sudo chmod -R 775 "${TARGET_MEMORIES_DIR}"
else
  mkdir -p "${TARGET_MEMORIES_DIR}"
  chmod -R 775 "${TARGET_MEMORIES_DIR}" || true
fi

# Ensure subdirectories for OKF organization exist
mkdir -p "${TARGET_MEMORIES_DIR}/knowledge"
mkdir -p "${TARGET_MEMORIES_DIR}/rules"
mkdir -p "${TARGET_MEMORIES_DIR}/logs"
mkdir -p "${REPO_ROOT}/data/backups"
mkdir -p "${REPO_ROOT}/data/control_plane"

# LiteLLM Dedicated Control Plane Database Storage (isolated from memories)
DB_DATA_DIR=$(grep -E '^LITELLM_DB_DATA_DIR=' .env 2>/dev/null | cut -d '=' -f2- || echo "./data/litellm_db")
DB_DATA_DIR="${DB_DATA_DIR:-./data/litellm_db}"

if [[ "$DB_DATA_DIR" != /* ]]; then
  TARGET_DB_DIR="${REPO_ROOT}/${DB_DATA_DIR#./}"
else
  TARGET_DB_DIR="${DB_DATA_DIR}"
fi

log_info "Target LiteLLM PostgreSQL directory: ${TARGET_DB_DIR}"

if [[ "$TARGET_DB_DIR" == /data/titan/* ]]; then
  log_info "Creating production database path with sudo: ${TARGET_DB_DIR}..."
  sudo mkdir -p "${TARGET_DB_DIR}"
  sudo chown -R 999:999 "${TARGET_DB_DIR}"
  sudo chmod -R 700 "${TARGET_DB_DIR}"
else
  mkdir -p "${TARGET_DB_DIR}"
  chmod -R 700 "${TARGET_DB_DIR}" || true
fi

log_success "Storage layout and OKF directory scaffolding initialized."

# ------------------------------------------------------------------------------
# 6. Native Model Seeding
# ------------------------------------------------------------------------------
if [ "${PULL_MODEL}" = true ]; then
  MODEL_NAME=$(grep -E '^INFERENCE_MODEL=' .env 2>/dev/null | cut -d '=' -f2- || echo "gemma2:2b")
  MODEL_NAME="${MODEL_NAME:-gemma2:2b}"
  log_info "Checking native Ollama daemon status for model seeding..."

  # Ensure Ollama daemon is running on 127.0.0.1:11434
  if ! curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    log_info "Starting host Ollama daemon in background..."
    OLLAMA_HOST="127.0.0.1:11434" ollama serve >"${REPO_ROOT}/data/control_plane/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    echo "${OLLAMA_PID}" > "${REPO_ROOT}/data/control_plane/ollama.pid"
    
    # Wait for Ollama daemon to respond
    READY=false
    for i in {1..30}; do
      if curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
        READY=true
        break
      fi
      sleep 1
    done

    if [ "$READY" != true ]; then
      log_error "Timed out waiting for host Ollama service to become ready on 127.0.0.1:11434."
      exit 1
    fi
  fi

  log_info "Pulling initial model '${MODEL_NAME}' natively into host Ollama..."
  ollama pull "${MODEL_NAME}"
  log_success "Successfully seeded model: ${MODEL_NAME}"
  log_info "Current local models:"
  ollama list
fi

# ------------------------------------------------------------------------------
# 7. Hermes Sandbox Image Build
# ------------------------------------------------------------------------------
if [ -f "${REPO_ROOT}/scripts/setup-hermes.sh" ]; then
  log_info "Invoking Hermes sandbox setup and image build..."
  "${REPO_ROOT}/scripts/setup-hermes.sh"
fi

log_success "Project Titan host baseline setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start host control plane: ./scripts/start-control-plane.sh"
echo "  2. Start container appliance: docker compose up -d"
echo "  3. Check status: curl http://127.0.0.1:4000/health"
echo ""
