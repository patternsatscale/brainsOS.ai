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

# Load active .env to read BRAINSOS_DATA_DIR if not already provided in environment
_EXPLICIT_DATA_DIR="${BRAINSOS_DATA_DIR:-}"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  . "${REPO_ROOT}/.env"
  set +a
fi
if [ -n "${_EXPLICIT_DATA_DIR}" ]; then
  BRAINSOS_DATA_DIR="${_EXPLICIT_DATA_DIR}"
fi

DATA_ROOT="${BRAINSOS_DATA_DIR:-./data}"
if [[ "$DATA_ROOT" != /* ]]; then
  DATA_ROOT="${REPO_ROOT}/${DATA_ROOT#./}"
fi

log_info "Resolved target runtime data directory: ${DATA_ROOT}"

# Check if target data directory is an active Git repository
if [ -d "${DATA_ROOT}/.git" ]; then
  log_warn "Detected active Git repository in ${DATA_ROOT}. Operating in decoupled private repository mode."
  if [ ! -f "${DATA_ROOT}/.gitignore" ] && [ -f "${REPO_ROOT}/config/templates/data-repo.gitignore" ]; then
    log_info "Installing data-repo.gitignore into ${DATA_ROOT}/.gitignore..."
    cp "${REPO_ROOT}/config/templates/data-repo.gitignore" "${DATA_ROOT}/.gitignore"
  fi
fi

# 2. Host Storage Directories
log_info "Scaffolding runtime data directories in ${DATA_ROOT}..."
DATA_DIRS=(
  "${DATA_ROOT}/agent_memories"
  "${DATA_ROOT}/agent_workspaces"
  "${DATA_ROOT}/agent_logs"
  "${DATA_ROOT}/comms"
  "${DATA_ROOT}/comms/spool"
  "${DATA_ROOT}/comms/maildir"
  "${DATA_ROOT}/queue"
  "${DATA_ROOT}/runners"
  "${DATA_ROOT}/settings"
  "${DATA_ROOT}/control_plane"
  "${DATA_ROOT}/control_plane/litellm_db"
  "${DATA_ROOT}/control_plane/vscode_config"
  "${DATA_ROOT}/control_plane/vscode_data"
  "${DATA_ROOT}/souls"
  "${DATA_ROOT}/skills"
  "${DATA_ROOT}/agent_apps"
  "${DATA_ROOT}/telemetry"
  "${DATA_ROOT}/backups"
)

for dir in "${DATA_DIRS[@]}"; do
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}"
    log_info "Created directory: ${dir}"
  fi
done

# Touch .gitkeep files in comms, backups, and skills
touch "${DATA_ROOT}/comms/spool/.gitkeep" 2>/dev/null || true
touch "${DATA_ROOT}/comms/maildir/.gitkeep" 2>/dev/null || true
touch "${DATA_ROOT}/backups/.gitkeep" 2>/dev/null || true
touch "${DATA_ROOT}/skills/.gitkeep" 2>/dev/null || true

# Seed default settings into settings if not already present
if [ -d "${REPO_ROOT}/config/default_settings" ]; then
  log_info "Seeding default configuration manifests from config/default_settings into ${DATA_ROOT}/settings..."
  cp -n -R "${REPO_ROOT}/config/default_settings/"* "${DATA_ROOT}/settings/" 2>/dev/null || true
fi

# Seed default runner templates into runners if not already present
if [ -d "${REPO_ROOT}/config/default_runners" ]; then
  log_info "Seeding default runner templates from config/default_runners into ${DATA_ROOT}/runners..."
  cp -n -R "${REPO_ROOT}/config/default_runners/"* "${DATA_ROOT}/runners/" 2>/dev/null || true
fi

# Seed default souls into souls if not already present
if [ -d "${REPO_ROOT}/config/default_souls" ]; then
  log_info "Seeding default souls from config/default_souls into ${DATA_ROOT}/souls..."
  cp -n -R "${REPO_ROOT}/config/default_souls/"* "${DATA_ROOT}/souls/" 2>/dev/null || true
fi

# Seed default agent skills into skills if not already present
if [ -d "${REPO_ROOT}/config/default_skills" ]; then
  log_info "Seeding default agent skills from config/default_skills into ${DATA_ROOT}/skills..."
  cp -n -R "${REPO_ROOT}/config/default_skills/"* "${DATA_ROOT}/skills/" 2>/dev/null || true
fi

# Seed sample agent app templates into agent_apps if not already present
if [ -d "${REPO_ROOT}/config/sample_agent_app" ]; then
  log_info "Seeding sample agent app from config/sample_agent_app into ${DATA_ROOT}/agent_apps..."
  cp -n -R "${REPO_ROOT}/config/sample_agent_app/"* "${DATA_ROOT}/agent_apps/" 2>/dev/null || true
fi

# Seed backup and restore harness into backups if not already present
if [ -d "${REPO_ROOT}/config/templates/backups" ]; then
  log_info "Seeding standalone backup harness from config/templates/backups into ${DATA_ROOT}/backups..."
  cp -n -R "${REPO_ROOT}/config/templates/backups/"* "${DATA_ROOT}/backups/" 2>/dev/null || true
  chmod +x "${DATA_ROOT}/backups/"*.sh 2>/dev/null || true
fi

# Touch caddy_root.crt dummy file if not present so Docker doesn't mount it as a directory
if [ ! -f "${DATA_ROOT}/control_plane/caddy_root.crt" ]; then
  touch "${DATA_ROOT}/control_plane/caddy_root.crt"
  chmod 664 "${DATA_ROOT}/control_plane/caddy_root.crt" 2>/dev/null || true
  log_info "Initialized ${DATA_ROOT}/control_plane/caddy_root.crt placeholder"
fi

# 2.5 Initialize Langfuse Distributed Observability Configuration
if [ -f "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" ]; then
  log_info "Initializing Langfuse distributed observability configuration..."
  "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" setup >/dev/null 2>&1 || true
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

# 4. Synchronize Active Skills to Workspace for Antigravity IDE
if [ -f "${REPO_ROOT}/.venv/bin/brainsos-skills" ]; then
  log_info "Synchronizing active skills into .agents/skills for Antigravity IDE..."
  "${REPO_ROOT}/.venv/bin/brainsos-skills" sync --repo "${REPO_ROOT}" --data "${DATA_ROOT}/skills" --target "${REPO_ROOT}/.agents/skills" >/dev/null 2>&1 || true
elif [ -d "${DATA_ROOT}/skills" ]; then
  mkdir -p "${REPO_ROOT}/.agents/skills"
  cp -R "${DATA_ROOT}/skills/"* "${REPO_ROOT}/.agents/skills/" 2>/dev/null || true
fi

# 5. Configure Git Pre-Commit Hook (Rule 11 & Rule 14 Leakage Gate)
if [ -d "${REPO_ROOT}/.git" ]; then
  log_info "Configuring git pre-commit hook to prevent private fleet leakage..."
  mkdir -p "${REPO_ROOT}/.git/hooks"
  cat << 'HOOK' > "${REPO_ROOT}/.git/hooks/pre-commit"
#!/usr/bin/env bash
# brainsOS Git Pre-Commit Hook: Prevents Private Fleet Leakage
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -f "${REPO_ROOT}/scripts/verify/verify-no-private-refs.sh" ]; then
  "${REPO_ROOT}/scripts/verify/verify-no-private-refs.sh" --staged-only
fi
HOOK
  chmod +x "${REPO_ROOT}/.git/hooks/pre-commit"
  log_success "Git pre-commit hook installed!"
fi

log_success "brainsOS environment bootstrap complete!"
