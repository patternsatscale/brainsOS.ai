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

log_info "Initializing Project Titan host baseline from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 0. Host Hygiene & Security Prechecks
# ------------------------------------------------------------------------------
# 0A. Repository Directory Permission Hardening
log_info "Securing repository permissions (chmod 750 ${REPO_ROOT})..."
chmod 750 "${REPO_ROOT}"
chmod 750 "${REPO_ROOT}/.git" 2>/dev/null || true

# 0B. Docker Daemon & Group Membership Precheck
if command -v docker >/dev/null 2>&1; then
  if ! docker info >/dev/null 2>&1; then
    CURRENT_USER="$(id -un 2>/dev/null || whoami)"
    if command -v getent >/dev/null 2>&1 && getent group docker | grep -qw "${CURRENT_USER}"; then
      if [ -z "${TITAN_DOCKER_REEXEC:-}" ] && command -v sg >/dev/null 2>&1; then
        export TITAN_DOCKER_REEXEC=1
        log_info "Refreshing active group permissions for 'docker' via sg..."
        exec sg docker -c "$0 $*"
      fi
    else
      log_warn "Current user '${CURRENT_USER}' cannot communicate with Docker daemon."
      log_warn "If you encounter permission issues, ensure your user is in the 'docker' group:"
      log_warn "  sudo usermod -aG docker ${CURRENT_USER} && newgrp docker"
    fi
  fi
fi

# 0C. External LiteLLM & Port Conflict Precheck
EXTERNAL_LITELLM="$(command -v litellm 2>/dev/null || true)"
if [ -n "${EXTERNAL_LITELLM}" ] && [[ "${EXTERNAL_LITELLM}" != "${REPO_ROOT}/.venv/*" ]]; then
  log_warn "Detected external LiteLLM binary at: ${EXTERNAL_LITELLM}"
  log_warn "Project Titan encapsulates its control plane in ${REPO_ROOT}/.venv."
  log_warn "Ensure external LiteLLM processes (e.g. from pipx) are not actively running."
fi

# Check for residual process on LiteLLM port (default 4000)
CHECK_PORT="${LITELLM_PORT:-4000}"
if (echo > /dev/tcp/127.0.0.1/"${CHECK_PORT}") >/dev/null 2>&1 || \
   (command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "${CHECK_PORT}" >/dev/null 2>&1); then
  log_warn "Port ${CHECK_PORT} is already listening on localhost. Verify it is not occupied by an external service."
fi

# ------------------------------------------------------------------------------
# 1. OS & Architecture Detection
# ------------------------------------------------------------------------------
# 1A. Hardware Profile & OS Detection (ASUS Ascent GX10 vs macOS Workstation)
# ------------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
log_info "Detected OS: ${OS} (${ARCH})"

is_gx10_hardware() {
  if [[ "${OS}" != "Linux" ]]; then
    return 1
  fi
  # Detect ASUS Ascent GX10 via DMI product/vendor or NVIDIA DGX service
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

IS_GX10=false
if is_gx10_hardware; then
  IS_GX10=true
fi

if [[ "${OS}" == "Linux" ]]; then
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    log_info "Linux Distribution: ${NAME:-Linux} ${VERSION_ID:-}"
  fi

  # DGX OS / Ubuntu Hardware Package Pinning (ASUS GX10 appliance only)
  if [ "${IS_GX10}" = true ] && command -v apt-mark >/dev/null 2>&1; then
    log_info "ASUS GX10 appliance hardware detected. Checking NVIDIA package holds..."
    for pkg in linux-nvidia-hwe-24.04 nvidia-container-toolkit; do
      if apt-mark showhold 2>/dev/null | grep -qx "${pkg}"; then
        log_success "Package ${pkg} is already pinned/held."
      elif dpkg -l "${pkg}" >/dev/null 2>&1; then
        log_info "Pinning package: ${pkg} via sudo apt-mark hold..."
        sudo apt-mark hold "${pkg}"
        log_success "Held package: ${pkg}"
      else
        log_warn "Package ${pkg} not yet installed; skipping hold."
      fi
    done
  else
    log_info "Non-GX10 Linux workstation detected. Skipping NVIDIA driver package holds."
  fi

  # Native Ollama installation on Linux (Ubuntu / DGX OS)
  if ! command -v ollama >/dev/null 2>&1; then
    log_info "Installing native Ollama on Linux host..."
    curl -fsSL https://ollama.com/install.sh | sh
    log_success "Ollama installed on Linux."
  else
    log_info "Ollama is already installed on host."
  fi

  # Ensure socat is installed on Linux (needed for DGX telemetry reverse proxy bridge)
  if ! command -v socat >/dev/null 2>&1; then
    log_info "Installing socat for hardware telemetry reverse proxy bridge..."
    sudo apt-get update -y && sudo apt-get install -y socat
    log_success "socat installed on Linux."
  fi

elif [[ "${OS}" == "Darwin" ]]; then
  log_info "Running on macOS (${ARCH}). Skipping Linux/GX10-specific apt holds."

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

  # Ensure socat is installed on macOS via Homebrew if available
  if ! command -v socat >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
    log_info "Installing socat via Homebrew..."
    brew install socat || true
  fi
fi

# ------------------------------------------------------------------------------
# 1B. Hardware-Adaptive Context Window Detection
# ------------------------------------------------------------------------------
if [ "${IS_GX10}" = true ]; then
  log_info "Detected production ASUS Ascent GX10 (GB10 / ~273 GB/s unified memory). Scaling context to 32k tokens."
  DETECTED_CTX=32768
else
  log_info "Workstation profile: macOS (Apple Silicon) or non-GX10 host. Pinned to safe 4k context window."
  DETECTED_CTX=4096
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
  log_info "Ensuring 'litellm[proxy]', 'prisma', 'langfuse', and 'opentelemetry' are installed in .venv..."
  "${UV_BIN}" pip install --python .venv/bin/python "litellm[proxy]" "prisma" "langfuse>=2.0.0" "opentelemetry-api" "opentelemetry-sdk" "opentelemetry-exporter-otlp" >/dev/null 2>&1
else
  log_info "Using system python3 to manage LiteLLM virtualenv..."
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  .venv/bin/pip install --upgrade pip >/dev/null 2>&1 || true
  .venv/bin/pip install "litellm[proxy]" "prisma" "langfuse>=2.0.0,<3.0.0" "opentelemetry-api" "opentelemetry-sdk" "opentelemetry-exporter-otlp" >/dev/null 2>&1
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
    chmod 600 .env
    log_success "Created .env configuration file (secured with chmod 600)."
  else
    log_error ".env.example not found."
    exit 1
  fi
else
  chmod 600 .env
  log_info ".env file already exists (enforced chmod 600)."
fi

# Ensure INFERENCE_NUM_CTX is adaptively set in .env
if [ -f .env ]; then
  if grep -q '^INFERENCE_NUM_CTX=' .env; then
    CURRENT_CTX=$(grep -E '^INFERENCE_NUM_CTX=' .env | cut -d '=' -f2-)
    if [ "${CURRENT_CTX}" != "${DETECTED_CTX}" ]; then
      sed -i.bak "s/^INFERENCE_NUM_CTX=.*/INFERENCE_NUM_CTX=${DETECTED_CTX}/" .env && rm -f .env.bak
      log_success "Updated INFERENCE_NUM_CTX=${DETECTED_CTX} in .env for detected hardware."
    fi
  else
    echo "" >> .env
    echo "# Inference Context Window (Tokens) - Hardware Adaptive" >> .env
    echo "INFERENCE_NUM_CTX=${DETECTED_CTX}" >> .env
    log_success "Appended INFERENCE_NUM_CTX=${DETECTED_CTX} to .env"
  fi
fi

# ------------------------------------------------------------------------------
# 5. Storage Directories & Permissions Setup
# ------------------------------------------------------------------------------
if [ -f "${REPO_ROOT}/scripts/setup/setup-memories.sh" ]; then
  log_info "Invoking Memory Plane setup and OKF scaffolding..."
  "${REPO_ROOT}/scripts/setup/setup-memories.sh"
fi

DATA_DIR=$(grep -E '^TITAN_DATA_DIR=' .env 2>/dev/null | cut -d '=' -f2- || echo "./data/memories")
DATA_DIR="${DATA_DIR:-./data/memories}"

if [[ "$DATA_DIR" != /* ]]; then
  TARGET_MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  TARGET_MEMORIES_DIR="${DATA_DIR}"
fi

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
  chmod -R 700 "${TARGET_DB_DIR}" 2>/dev/null || true
fi

# Hermes Agent Runtime Workspace Storage (tools, caches, packages, isolated from memories)
WORKSPACE_DIR=$(grep -E '^TITAN_WORKSPACE_DIR=' .env 2>/dev/null | cut -d '=' -f2- || echo "./data/workspace")
WORKSPACE_DIR="${WORKSPACE_DIR:-./data/workspace}"

if [[ "$WORKSPACE_DIR" != /* ]]; then
  TARGET_WORKSPACE_DIR="${REPO_ROOT}/${WORKSPACE_DIR#./}"
else
  TARGET_WORKSPACE_DIR="${WORKSPACE_DIR}"
fi

log_info "Target Hermes Agent workspace directory: ${TARGET_WORKSPACE_DIR}"

if [[ "$TARGET_WORKSPACE_DIR" == /data/titan/* ]]; then
  log_info "Creating production workspace path with sudo: ${TARGET_WORKSPACE_DIR}..."
  sudo mkdir -p "${TARGET_WORKSPACE_DIR}"
  sudo chown -R 1000:1000 "${TARGET_WORKSPACE_DIR}"
  sudo chmod 775 "${TARGET_WORKSPACE_DIR}"
else
  mkdir -p "${TARGET_WORKSPACE_DIR}"
  chmod 775 "${TARGET_WORKSPACE_DIR}" || true
fi

if [ ! -f "${REPO_ROOT}/data/workspace/.gitkeep" ]; then
  touch "${REPO_ROOT}/data/workspace/.gitkeep"
fi

log_success "Storage layout (memories, database, workspace) initialized."

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
if [ -f "${REPO_ROOT}/scripts/setup/setup-hermes.sh" ]; then
  log_info "Invoking Hermes sandbox setup and image build..."
  "${REPO_ROOT}/scripts/setup/setup-hermes.sh"
fi

# ------------------------------------------------------------------------------
# 8. Ingress, Container Stack & Endpoint Smoke Verification
# ------------------------------------------------------------------------------
log_info "Running baseline ingress and container stack verification..."

# 8A. Validate Docker Compose topology
log_info "Validating Docker Compose topology..."
docker compose config --quiet
log_success "Docker Compose configuration verified."

# 8B. Validate Caddy Reverse Proxy syntax
log_info "Validating Caddyfile syntax..."
docker run --rm -v "${REPO_ROOT}/config/caddy/Caddyfile:/etc/caddy/Caddyfile" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1
log_success "Caddyfile configuration validated."

# 8C. Verify local domain resolution (.titan.local vs .localhost)
log_info "Checking local domain resolution..."
if getent hosts "hermes.titan.local" >/dev/null 2>&1; then
  log_success "Domain hermes.titan.local resolves successfully."
else
  log_info "Notice: 'hermes.titan.local' is not yet configured in /etc/hosts."
  log_info "To use *.titan.local custom domains, run:"
  if [ "${IS_GX10}" = true ]; then
    log_info "  echo '127.0.0.1 titan.local hermes.titan.local api.hermes.titan.local proxy.titan.local memory.titan.local dgx.titan.local' | sudo tee -a /etc/hosts"
  else
    log_info "  echo '127.0.0.1 titan.local hermes.titan.local api.hermes.titan.local proxy.titan.local memory.titan.local' | sudo tee -a /etc/hosts"
  fi
  log_info "Zero-config fallback: *.localhost domains (e.g. http://hermes.localhost) work automatically without /etc/hosts."
fi

# 8D. Launch appliance containers & verify live endpoints
log_info "Ensuring appliance containers are started (docker compose up -d)..."
docker compose up -d

# 8E. Ensure host control plane services are running
if [ -f "${REPO_ROOT}/scripts/control/start-control-plane.sh" ]; then
  log_info "Ensuring host control plane services are running (start-control-plane.sh)..."
  "${REPO_ROOT}/scripts/control/start-control-plane.sh" start
fi

# Wait briefly for containers to become ready
log_info "Awaiting service readiness..."
for i in {1..30}; do
  if curl -s "http://127.0.0.1:80" >/dev/null 2>&1 && curl -s "http://127.0.0.1:8642/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Verify Ingress Landing Page
if curl -s "http://127.0.0.1:80" | grep -q "Project Titan"; then
  log_success "Ingress landing page verified on port 80 (http://localhost)."
else
  log_warn "Ingress landing page not responding as expected on port 80."
fi

# Verify Hermes Agent unprivileged API via Caddy reverse proxy
if curl -s "http://hermes.localhost/health" | grep -q "hermes-titan"; then
  log_success "Hermes unprivileged agent runtime verified via Caddy (http://hermes.localhost)."
elif curl -s -H "Host: hermes.titan.local" "http://127.0.0.1/health" | grep -q "hermes-titan"; then
  log_success "Hermes unprivileged agent runtime verified via Caddy (Host: hermes.titan.local)."
else
  log_warn "Hermes endpoint not yet responding via reverse proxy."
fi

# Verify SilverBullet PKM UI via Caddy reverse proxy
if curl -s -I "http://memory.localhost/" 2>&1 | grep -qE "HTTP/(1.1|2) 200"; then
  log_success "SilverBullet PKM verified via Caddy (http://memory.localhost)."
elif curl -s -I -H "Host: memory.titan.local" "http://127.0.0.1/" 2>&1 | grep -qE "HTTP/(1.1|2) 200"; then
  log_success "SilverBullet PKM verified via Caddy (Host: memory.titan.local)."
else
  log_warn "SilverBullet endpoint not yet responding via reverse proxy."
fi

# Verify LiteLLM Gateway & UI via Caddy reverse proxy
if curl -s -o /dev/null -w "%{http_code}" "http://proxy.localhost/ui/" | grep -q "200"; then
  log_success "LiteLLM Gateway & UI verified via Caddy (http://proxy.localhost/ui)."
elif curl -s -o /dev/null -w "%{http_code}" -H "Host: proxy.titan.local" "http://127.0.0.1/ui/" | grep -q "200"; then
  log_success "LiteLLM Gateway & UI verified via Caddy (Host: proxy.titan.local/ui)."
else
  log_warn "LiteLLM endpoint not yet responding via reverse proxy."
fi

# Verify DGX Dashboard via Caddy reverse proxy (ASUS GX10 appliance profile only)
if [ "${IS_GX10}" = true ] && curl -s "http://127.0.0.1:11000" >/dev/null 2>&1; then
  if curl -s -o /dev/null -w "%{http_code}" "http://dgx.localhost/" | grep -q "200"; then
    log_success "NVIDIA DGX Dashboard verified via Caddy (http://dgx.localhost)."
  elif curl -s -o /dev/null -w "%{http_code}" -H "Host: dgx.titan.local" "http://127.0.0.1/" | grep -q "200"; then
    log_success "NVIDIA DGX Dashboard verified via Caddy (Host: dgx.titan.local)."
  else
    log_warn "DGX Dashboard endpoint not yet responding via reverse proxy."
  fi
fi

log_success "Project Titan host baseline setup and verification complete!"
echo ""
echo "Appliance Endpoints:"
echo "  - Ingress Gateway:   http://localhost (or https://localhost)"
echo "  - Hermes Console:    http://hermes.localhost (or http://hermes.titan.local)"
echo "  - Hermes API:        http://api.hermes.localhost (or http://api.hermes.titan.local)"
echo "  - Memory Plane PKM:  http://memory.localhost (or http://memory.titan.local)"
echo "  - LiteLLM Admin UI:  http://proxy.localhost/ui (or http://proxy.titan.local/ui)"
if [ "${IS_GX10}" = true ]; then
  echo "  - DGX Dashboard:     http://dgx.localhost (or http://dgx.titan.local)"
fi
echo "  - LiteLLM Control:   ./scripts/control/start-control-plane.sh {start|stop|status}"
echo ""
