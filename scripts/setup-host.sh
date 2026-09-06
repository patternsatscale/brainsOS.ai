#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Idempotent Host Baseline Setup Script
# Configures host dependencies, permissions, memory directories, and model seeding
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
    log_info "Linux Distribution: ${NAME} ${VERSION_ID}"
  fi

  # DGX OS / Ubuntu Hardware Package Pinning
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
elif [[ "${OS}" == "Darwin" ]]; then
  log_info "Running on macOS (Apple Silicon). Skipping Linux-specific apt holds."
fi

# ------------------------------------------------------------------------------
# 2. Docker & Docker Compose Verification
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

# ------------------------------------------------------------------------------
# 3. Environment Template Verification
# ------------------------------------------------------------------------------
cd "${REPO_ROOT}"
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
# 4. Storage Directories & Permissions Setup
# ------------------------------------------------------------------------------
# Read TITAN_DATA_DIR from .env if present, fallback to ./data/memories
DATA_DIR=$(grep -E '^TITAN_DATA_DIR=' .env 2>/dev/null | cut -d '=' -f2- || echo "./data/memories")
DATA_DIR="${DATA_DIR:-./data/memories}"

# If path is relative, resolve from REPO_ROOT
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

log_success "Storage layout and OKF directory scaffolding initialized."

# ------------------------------------------------------------------------------
# 5. Optional Model Seeding
# ------------------------------------------------------------------------------
if [ "${PULL_MODEL}" = true ]; then
  MODEL_NAME=$(grep -E '^INFERENCE_MODEL=' .env 2>/dev/null | cut -d '=' -f2- || echo "gemma2:2b")
  MODEL_NAME="${MODEL_NAME:-gemma2:2b}"
  log_info "Pulling initial model '${MODEL_NAME}' into Ollama..."
  
  # Ensure Ollama service is running
  docker compose up -d ollama
  log_info "Waiting for Ollama to become ready..."
  
  READY=false
  for i in {1..30}; do
    if docker compose exec -T ollama ollama list >/dev/null 2>&1; then
      READY=true
      break
    fi
    sleep 1
  done
  
  if [ "$READY" = true ]; then
    docker compose exec -T ollama ollama pull "${MODEL_NAME}"
    log_success "Successfully pulled model: ${MODEL_NAME}"
  else
    log_error "Timed out waiting for Ollama service."
  fi
fi

log_success "Project Titan host baseline setup complete!"
echo ""
echo "Next steps:"
echo "  1. Review .env and set your preferred keys and domain."
echo "  2. Start the appliance: docker compose up -d"
echo "  3. Check logs: docker compose logs -f"
echo ""
