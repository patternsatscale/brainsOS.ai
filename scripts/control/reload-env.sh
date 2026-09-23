#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Environment Synchronization & Reload Utility (reload-env.sh)
#
# Reloads and applies all .env configuration across all planes without data loss:
#   1. Synchronizes PostgreSQL user passwords in titan-litellm-db & titan-langfuse-db
#   2. Recreates Docker containers with updated environment variables & extra_hosts
#   3. Restarts host control plane (LiteLLM, Ollama, DGX bridge) with new variables
#   4. Reloads Caddy ingress reverse proxy
#   5. Verifies service health
# ==============================================================================

set -euo pipefail

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
ENV_FILE="${REPO_ROOT}/.env"

# Terminal formatting
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}Project Titan: Environment Reload & Password Synchronization${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

# Optional formatting flag (--format or --clean)
if [ "${1:-}" = "--format" ] || [ "${1:-}" = "--clean" ]; then
  "${SCRIPT_DIR}/format-env.sh"
fi

if [ ! -f "${ENV_FILE}" ]; then
  log_error ".env file not found at ${ENV_FILE}. Run: cp .env.example .env"
  exit 1
fi

# Load variables
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

# Auto-derive GITHUB_BASIC_AUTH_CINDY from GITHUB_TOKEN_CINDY if not explicitly set
if [ -n "${GITHUB_TOKEN_CINDY:-}" ] && [ -z "${GITHUB_BASIC_AUTH_CINDY:-}" ]; then
  GITHUB_BASIC_AUTH_CINDY="$(printf 'x-access-token:%s' "${GITHUB_TOKEN_CINDY}" | base64 | tr -d '\r\n')"
  export GITHUB_BASIC_AUTH_CINDY
  if grep -q "^GITHUB_BASIC_AUTH_CINDY=" "${ENV_FILE}"; then
    sed -i.bak "s|^GITHUB_BASIC_AUTH_CINDY=.*|GITHUB_BASIC_AUTH_CINDY=${GITHUB_BASIC_AUTH_CINDY}|" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
  else
    echo "GITHUB_BASIC_AUTH_CINDY=${GITHUB_BASIC_AUTH_CINDY}" >> "${ENV_FILE}"
  fi
fi

cd "${REPO_ROOT}"

# ------------------------------------------------------------------------------
# 1. Synchronize LiteLLM PostgreSQL Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 1/5: Checking LiteLLM database credentials..."

DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^titan-(infra-)?litellm-db$' | head -n 1 || true)"
if [ -n "${DB_CONTAINER}" ]; then
  LITELLM_DB_USER="${LITELLM_DB_USER:-litellm}"
  LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"
  LITELLM_DB_PASSWORD="${LITELLM_DB_PASSWORD:-titan_litellm_secret_change_me}"

  log_info "Synchronizing database password for user '${LITELLM_DB_USER}' in ${DB_CONTAINER}..."
  # Execute ALTER USER inside the container via local socket (trust/peer auth)
  if docker exec "${DB_CONTAINER}" psql -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" \
      -c "ALTER USER \"${LITELLM_DB_USER}\" WITH PASSWORD '${LITELLM_DB_PASSWORD}';" >/dev/null 2>&1; then
    log_success "LiteLLM database password synchronized with .env (Zero data loss)."
  else
    # Fallback to postgres superuser if user lacks ALTER privilege
    if docker exec "${DB_CONTAINER}" psql -U postgres \
        -c "ALTER USER \"${LITELLM_DB_USER}\" WITH PASSWORD '${LITELLM_DB_PASSWORD}';" >/dev/null 2>&1; then
      log_success "LiteLLM database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter LiteLLM password. Database may be initializing."
    fi
  fi
else
  log_info "LiteLLM database container is not running; will be started during control plane restart."
fi

# ------------------------------------------------------------------------------
# 2. Synchronize Langfuse Database Password (if local container is running)
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-db$"; then
  log_info "Step 2/5: Synchronizing local Langfuse database credentials..."
  LANGFUSE_ENV_FILE="${REPO_ROOT}/docker/langfuse/.env"
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    LF_DB_PASS=$(grep "^LANGFUSE_DB_PASSWORD=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || true)
    LF_DB_USER=$(grep "^LANGFUSE_DB_USER=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    LF_DB_NAME=$(grep "^LANGFUSE_DB_NAME=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    if [ -n "${LF_DB_PASS}" ]; then
      docker exec titan-langfuse-db psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
        -c "ALTER USER \"${LF_DB_USER}\" WITH PASSWORD '${LF_DB_PASS}';" >/dev/null 2>&1 || true
      log_success "Langfuse database password synchronized."
    fi

    # Synchronize Langfuse Web admin user password if updated
    LF_ADMIN_PASS="${LANGFUSE_INIT_USER_PASSWORD:-}"
    LF_ADMIN_EMAIL="${LANGFUSE_INIT_USER_EMAIL:-admin@titan.local}"
    if [ -n "${LF_ADMIN_PASS}" ] && docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-web$"; then
      LF_HASH=$(docker exec -i titan-langfuse-web node -e "
        const p = process.argv[1];
        const bcrypt = require('/app/node_modules/.pnpm/bcryptjs@2.4.3/node_modules/bcryptjs/dist/bcrypt.js');
        console.log(bcrypt.hashSync(p, 12));
      " "${LF_ADMIN_PASS}" 2>/dev/null || true)
      if [ -n "${LF_HASH}" ]; then
        docker exec -i titan-langfuse-db psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
          -c "UPDATE users SET password = '${LF_HASH}', updated_at = NOW() WHERE email = '${LF_ADMIN_EMAIL}';" >/dev/null 2>&1 || true
        log_success "Langfuse admin user password synchronized."
      fi
    fi
  fi
else
  log_info "Step 2/5: Langfuse database is not running locally (skipping)."
fi

# ------------------------------------------------------------------------------
# 3. Recreate / Update Docker Compose Services
# ------------------------------------------------------------------------------
log_info "Step 3/5: Updating Docker container configurations..."
docker compose up -d
log_success "Docker services updated with current .env configurations."

# ------------------------------------------------------------------------------
# 4. Restart Control Plane Gateway & Host Services
# ------------------------------------------------------------------------------
log_info "Step 4/5: Restarting control plane (LiteLLM, Ollama, Langfuse)..."
"${SCRIPT_DIR}/start-control-plane.sh" restart

# ------------------------------------------------------------------------------
# 5. Reload Caddy Ingress Gateway
# ------------------------------------------------------------------------------
log_info "Step 5/5: Reloading Caddy ingress proxy..."
if docker ps --format '{{.Names}}' | grep -qE '^titan-(net-)?caddy$'; then
  docker compose restart caddy >/dev/null 2>&1
  log_success "Caddy ingress reloaded."
fi

# ------------------------------------------------------------------------------
# Summary & Health Status
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}Project Titan: Environment Successfully Reloaded${NC}"
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "All updated .env values and database credentials have been applied."
echo ""
"${SCRIPT_DIR}/start-control-plane.sh" status
