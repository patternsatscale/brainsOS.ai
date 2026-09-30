#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Developer Environment Bootstrap Script
# Provisions local .env, runtime data storage directories, and Python dependencies.
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

echo -e "${BOLD}brainsOS Environment Bootstrap${NC}"
echo -e "Target Root: ${REPO_ROOT}"

# 1. Environment Configuration (.env)
if [ ! -f "${REPO_ROOT}/.env" ]; then
  if [ -f "${REPO_ROOT}/.env.example" ]; then
    log_info "Creating .env from .env.example..."
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
    log_success "Created ${REPO_ROOT}/.env"
  else
    log_error "No .env.example found! Cannot generate .env."
    exit 1
  fi
else
  log_info ".env already exists. Preserving existing configuration."
fi

# 2. Host Storage Directories
log_info "Scaffolding local host runtime data directories..."
DATA_DIRS=(
  "${REPO_ROOT}/data/agent_memories"
  "${REPO_ROOT}/data/agent_workspaces"
  "${REPO_ROOT}/data/agent_logs"
  "${REPO_ROOT}/data/caddy"
  "${REPO_ROOT}/data/litellm"
  "${REPO_ROOT}/data/comms"
  "${REPO_ROOT}/data/queue"
  "${REPO_ROOT}/data/runners"
  "${REPO_ROOT}/data/settings"
  "${REPO_ROOT}/data/control_plane"
)

for dir in "${DATA_DIRS[@]}"; do
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}"
    log_info "Created directory: ${dir}"
  fi
done

# Seed default settings into data/settings if not already present
if [ -d "${REPO_ROOT}/config/default_settings" ]; then
  log_info "Seeding default configuration manifests from config/default_settings into data/settings..."
  cp -n -R "${REPO_ROOT}/config/default_settings/"* "${REPO_ROOT}/data/settings/" 2>/dev/null || true
fi

# Seed default runner templates into data/runners if not already present
if [ -d "${REPO_ROOT}/config/default_runners" ]; then
  log_info "Seeding default runner templates from config/default_runners into data/runners..."
  cp -n -R "${REPO_ROOT}/config/default_runners/"* "${REPO_ROOT}/data/runners/" 2>/dev/null || true
fi

# Touch caddy_root.crt dummy file if not present so Docker doesn't mount it as a directory
if [ ! -f "${REPO_ROOT}/data/control_plane/caddy_root.crt" ]; then
  touch "${REPO_ROOT}/data/control_plane/caddy_root.crt"
  chmod 664 "${REPO_ROOT}/data/control_plane/caddy_root.crt" 2>/dev/null || true
  log_info "Initialized ${REPO_ROOT}/data/control_plane/caddy_root.crt placeholder"
fi

# 3. Python Virtual Environment & Packages
if command -v uv >/dev/null 2>&1; then
  log_info "Found 'uv' package manager."
  if [ ! -d "${REPO_ROOT}/.venv" ]; then
    log_info "Creating virtual environment at .venv..."
    uv venv "${REPO_ROOT}/.venv"
  fi

  log_info "Installing dev tooling and brainsOS packages in editable mode..."
  uv pip install --python "${REPO_ROOT}/.venv/bin/python" pytest pytest-asyncio ruff mypy
  for pkg in "${REPO_ROOT}/packages/"*/; do
    if [ -f "${pkg}/pyproject.toml" ]; then
      log_info "Installing package: $(basename "${pkg}")..."
      uv pip install -e "${pkg}" --python "${REPO_ROOT}/.venv/bin/python"
    fi
  done
elif command -v python3 >/dev/null 2>&1; then
  log_warn "'uv' not found. Falling back to python3 venv/pip."
  if [ ! -d "${REPO_ROOT}/.venv" ]; then
    log_info "Creating virtual environment at .venv..."
    python3 -m venv "${REPO_ROOT}/.venv"
  fi

  log_info "Installing dev tooling and brainsOS packages in editable mode..."
  "${REPO_ROOT}/.venv/bin/pip" install --quiet pytest pytest-asyncio ruff mypy
  for pkg in "${REPO_ROOT}/packages/"*/; do
    if [ -f "${pkg}/pyproject.toml" ]; then
      log_info "Installing package: $(basename "${pkg}")..."
      "${REPO_ROOT}/.venv/bin/pip" install -e "${pkg}" --quiet
    fi
  done
else
  log_warn "Neither 'uv' nor 'python3' detected on host. Skipping local Python package bootstrap."
fi

log_success "brainsOS environment bootstrap complete!"
