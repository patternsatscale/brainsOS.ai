#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Environment Synchronization & Reload Utility (reload-env.sh)
#
# Reloads and applies all .env configuration across all planes without data loss:
#   1. Synchronizes PostgreSQL user passwords in LiteLLM DB & SOGo DB & Langfuse DB
#   2. Recreates Docker containers with updated environment variables & extra_hosts
#   3. Restarts host control plane (LiteLLM, Ollama, Langfuse, Queue Worker)
#   4. Reloads Caddy ingress reverse proxy
#   5. Verifies service health
#   6. Displays updated service directory & credentials (show-urls.sh)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
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
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Parse arguments
FORMAT_ENV=false
SKIP_URLS=false
URLS_ARGS=()

show_help() {
  echo -e "${BOLD}brainsOS Environment Reload & Password Synchronization${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --format, --clean Clean and format .env before reloading"
  echo "  --mask-secrets    Mask passwords and API tokens in the service directory output"
  echo "  --apply-hosts     Automatically apply missing /etc/hosts mappings (requires sudo)"
  echo "  --no-hosts        Skip checking or updating /etc/hosts"
  echo "  --no-urls         Skip displaying the service directory table after reloading"
  echo "  -h, --help        Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format|--clean)
      FORMAT_ENV=true
      shift
      ;;
    --no-urls|--skip-urls)
      SKIP_URLS=true
      shift
      ;;
    --mask-secrets|--apply-hosts|--no-hosts)
      URLS_ARGS+=("$1")
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      URLS_ARGS+=("$1")
      shift
      ;;
  esac
done

echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}brainsOS: Environment Reload & Password Synchronization${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

if [ "${FORMAT_ENV}" = true ]; then
  "${SCRIPT_DIR}/format-env.sh"
fi

if [ ! -f "${ENV_FILE}" ]; then
  log_error "No .env file found at ${ENV_FILE}. Cannot reload."
  exit 1
fi

# Load variables
set -a
. "${ENV_FILE}"
set +a


# ------------------------------------------------------------------------------
# 1. Synchronize LiteLLM PostgreSQL Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 1/6: Checking LiteLLM database credentials..."

DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(infra-)?litellm-db$' | head -n 1 || true)"
if [ -n "${DB_CONTAINER}" ]; then
  LITELLM_DB_USER="${LITELLM_DB_USER:-litellm}"
  LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"
  LITELLM_DB_PASSWORD="${LITELLM_DB_PASSWORD:-brainsos_litellm_secret_change_me}"

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
# 2. Synchronize SOGo Groupware Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 2/6: Checking SOGo database credentials..."

SOGO_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-sogo-db$' | head -n 1 || true)"
if [ -n "${SOGO_DB_CONTAINER}" ]; then
  SOGO_DB_USER="${SOGO_DB_USER:-sogo}"
  SOGO_DB_NAME="${SOGO_DB_NAME:-sogo}"
  SOGO_DB_PASSWORD="${SOGO_DB_PASSWORD:-sogo_secret_pass}"

  log_info "Synchronizing database password for user '${SOGO_DB_USER}' in ${SOGO_DB_CONTAINER}..."
  if docker exec "${SOGO_DB_CONTAINER}" psql -U "${SOGO_DB_USER}" -d "${SOGO_DB_NAME}" \
      -c "ALTER USER \"${SOGO_DB_USER}\" WITH PASSWORD '${SOGO_DB_PASSWORD}';" >/dev/null 2>&1; then
    log_success "SOGo database password synchronized with .env (Zero data loss)."
  else
    if docker exec "${SOGO_DB_CONTAINER}" psql -U postgres \
        -c "ALTER USER \"${SOGO_DB_USER}\" WITH PASSWORD '${SOGO_DB_PASSWORD}';" >/dev/null 2>&1; then
      log_success "SOGo database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter SOGo password. Database may be initializing."
    fi
  fi
else
  log_info "SOGo database container is not running (skipping)."
fi

# ------------------------------------------------------------------------------
# 3. Synchronize Langfuse Database Password (if local container is running)
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-db$"; then
  log_info "Step 3/6: Synchronizing local Langfuse database credentials..."
  LANGFUSE_ENV_FILE="${REPO_ROOT}/docker/langfuse/.env"
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    LF_DB_PASS=$(grep "^LANGFUSE_DB_PASSWORD=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || true)
    LF_DB_USER=$(grep "^LANGFUSE_DB_USER=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    LF_DB_NAME=$(grep "^LANGFUSE_DB_NAME=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    if [ -n "${LF_DB_PASS}" ]; then
      docker exec brainsos-langfuse-db psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
        -c "ALTER USER \"${LF_DB_USER}\" WITH PASSWORD '${LF_DB_PASS}';" >/dev/null 2>&1 || true
      log_success "Langfuse database password synchronized."
    fi

    # Synchronize Langfuse Web admin user password if updated
    LF_ADMIN_PASS="${LANGFUSE_INIT_USER_PASSWORD:-}"
    LF_ADMIN_EMAIL="${LANGFUSE_INIT_USER_EMAIL:-admin@brainsos.local}"
    if [ -n "${LF_ADMIN_PASS}" ] && docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-web$"; then
      LF_HASH=$(docker exec -i brainsos-langfuse-web node -e "
        const p = process.argv[1];
        const bcrypt = require('/app/node_modules/.pnpm/bcryptjs@2.4.3/node_modules/bcryptjs/dist/bcrypt.js');
        console.log(bcrypt.hashSync(p, 12));
      " "${LF_ADMIN_PASS}" 2>/dev/null || true)
      if [ -n "${LF_HASH}" ]; then
        docker exec -i brainsos-langfuse-db psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
          -c "UPDATE users SET password = '${LF_HASH}', updated_at = NOW() WHERE email = '${LF_ADMIN_EMAIL}';" >/dev/null 2>&1 || true
        log_success "Langfuse admin user password synchronized."
      fi
    fi
  fi
else
  log_info "Step 3/6: Langfuse database is not running locally (skipping)."
fi

# ------------------------------------------------------------------------------
# 4. Recreate / Update Docker Compose Services
# ------------------------------------------------------------------------------
log_info "Step 4/6: Updating Docker container configurations..."
docker compose up -d
log_success "Docker services updated with current .env configurations."

# ------------------------------------------------------------------------------
# 5. Restart Control Plane Gateway & Host Services
# ------------------------------------------------------------------------------
log_info "Step 5/6: Restarting control plane (LiteLLM, Ollama, Langfuse, Queue)..."
"${SCRIPT_DIR}/start-control-plane.sh" restart

# ------------------------------------------------------------------------------
# 6. Reload Caddy Ingress Gateway
# ------------------------------------------------------------------------------
log_info "Step 6/6: Reloading Caddy ingress proxy..."
if docker ps --format '{{.Names}}' | grep -qE '^brainsos-(net-)?caddy$'; then
  docker compose restart caddy >/dev/null 2>&1
  log_success "Caddy ingress reloaded."
fi

# ------------------------------------------------------------------------------
# Summary & Health Status
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}brainsOS: Environment Successfully Reloaded${NC}"
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "All updated .env values, domains, and database credentials have been applied."
echo ""
"${SCRIPT_DIR}/start-control-plane.sh" status

# ------------------------------------------------------------------------------
# Display Service Directory & URLs
# ------------------------------------------------------------------------------
if [ "${SKIP_URLS}" = false ]; then
  echo ""
  "${SCRIPT_DIR}/show-urls.sh" "${URLS_ARGS[@]}"
fi
