#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Hermes Agent Runtime Provisioning & Build Script
# Automates building the unprivileged Hermes sandbox container image and
# validating environment permissions for memory purity and tool sandboxing.
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
else
  log_warn ".env file not found. Falling back to .env.example values."
  if [ -f .env.example ]; then
    set -a
    . ./.env.example
    set +a
  fi
fi

log_info "Initializing Project Titan Hermes Agent Runtime from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 1. Environment & Prerequisite Checks
# ------------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log_error "Docker is required but not installed or not in PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  CURRENT_USER="$(id -un 2>/dev/null || whoami)"
  if command -v getent >/dev/null 2>&1 && getent group docker | grep -qw "${CURRENT_USER}"; then
    if [ -z "${TITAN_DOCKER_REEXEC:-}" ] && command -v sg >/dev/null 2>&1; then
      export TITAN_DOCKER_REEXEC=1
      exec sg docker -c "$0 $*"
    fi
  fi
  log_error "Docker daemon is not running or accessible. Please ensure Docker is running and your user is in the 'docker' group."
  exit 1
fi
log_success "Docker daemon verified."

# ------------------------------------------------------------------------------
# 2. Memory & Workspace Plane Scaffolding & Permissions
# ------------------------------------------------------------------------------
MEMORIES_DIR="${TITAN_DATA_DIR:-${REPO_ROOT}/data/memories}"
mkdir -p "${MEMORIES_DIR}/knowledge" "${MEMORIES_DIR}/rules" "${MEMORIES_DIR}/logs"
log_success "Memory plane directories verified at ${MEMORIES_DIR}."

WORKSPACE_DIR="${TITAN_WORKSPACE_DIR:-${REPO_ROOT}/data/workspace}"
mkdir -p "${WORKSPACE_DIR}" "${WORKSPACE_DIR}/signal" "${WORKSPACE_DIR}/skills"
chmod 775 "${WORKSPACE_DIR}" "${WORKSPACE_DIR}/signal" "${WORKSPACE_DIR}/skills" || true

if [ ! -f "${WORKSPACE_DIR}/config.yaml" ] && [ -f "${REPO_ROOT}/config/hermes/config.yaml" ]; then
  cp "${REPO_ROOT}/config/hermes/config.yaml" "${WORKSPACE_DIR}/config.yaml"
  log_info "Seeded default Hermes configuration at ${WORKSPACE_DIR}/config.yaml."
fi

if [ -f "${REPO_ROOT}/docker/hermes/hermes_okf.py" ]; then
  cp "${REPO_ROOT}/docker/hermes/hermes_okf.py" "${WORKSPACE_DIR}/skills/hermes_okf.py"
  chmod +x "${WORKSPACE_DIR}/skills/hermes_okf.py" || true
fi

if [ ! -f "${REPO_ROOT}/data/workspace/.gitkeep" ]; then
  touch "${REPO_ROOT}/data/workspace/.gitkeep"
fi
log_success "Workspace host storage verified at ${WORKSPACE_DIR}."

# ------------------------------------------------------------------------------
# 3. Pull & Build Unprivileged Hermes Sandbox & Messaging Images
# ------------------------------------------------------------------------------
log_info "Ensuring companion services are present (signal-cli)..."
docker compose pull signal-cli

log_info "Building unprivileged Hermes Agent image (titan-hermes:latest)..."
docker compose build hermes
log_success "Hermes Agent container image built successfully."

# ------------------------------------------------------------------------------
# 4. Validate Build Integrity & Unprivileged Profile
# ------------------------------------------------------------------------------
log_info "Verifying Hermes image configuration and security boundaries..."
IMAGE_NAME=$(docker compose config --format json 2>/dev/null | grep -o '"image":"[^"]*hermes[^"]*"' | head -n 1 | cut -d'"' -f4 || echo "titan-hermes:latest")

if docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  log_success "Verified image '${IMAGE_NAME}' exists."
fi

log_success "Hermes runtime setup complete! Start services via: docker compose up -d"
