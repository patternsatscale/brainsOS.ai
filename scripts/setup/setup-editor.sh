#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Operator IDE Setup & Provisioning Script
# Provisions storage directories, registers operator virtual key in LiteLLM,
# builds the native ARM64/AMD64 code-server image, and launches the service.
# ==============================================================================

set -euo pipefail

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

cd "${REPO_ROOT}"

# Load environment variables
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
else
  log_warn ".env file not found. Using defaults."
  if [ -f .env.example ]; then
    set -a
    . ./.env.example
    set +a
  fi
fi

log_info "Setting up Project Titan Operator IDE from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 1. Scaffold Storage Directories
# ------------------------------------------------------------------------------
CONFIG_DIR="${TITAN_CODE_SERVER_CONFIG:-./data/control_plane/vscode_config}"
DATA_DIR="${TITAN_CODE_SERVER_DATA:-./data/control_plane/vscode_data}"

if [[ "$CONFIG_DIR" != /* ]]; then
  CONFIG_DIR="${REPO_ROOT}/${CONFIG_DIR#./}"
fi
if [[ "$DATA_DIR" != /* ]]; then
  DATA_DIR="${REPO_ROOT}/${DATA_DIR#./}"
fi

mkdir -p "${CONFIG_DIR}" "${DATA_DIR}"
chmod -R 775 "${CONFIG_DIR}" "${DATA_DIR}" 2>/dev/null || true
log_success "Scaffolded operator configuration and data directories:"
log_info "  - Config: ${CONFIG_DIR}"
log_info "  - Data:   ${DATA_DIR}"

# Ensure canvas site directory exists
mkdir -p "${REPO_ROOT}/apps/cindypawford/site"

# ------------------------------------------------------------------------------
# 2. Register Operator Virtual Key in LiteLLM Control Plane Database
# ------------------------------------------------------------------------------
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
OPERATOR_LITELLM_KEY="${OPERATOR_LITELLM_KEY:-sk-titan-operator-virtual-key}"

if [ -n "${LITELLM_MASTER_KEY}" ] && curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
  log_info "Checking operator virtual key in LiteLLM DB..."
  KEY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X GET "http://127.0.0.1:${LITELLM_PORT}/key/info?key=${OPERATOR_LITELLM_KEY}" \
    -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "000")

  if [ "${KEY_STATUS}" != "200" ]; then
    log_info "Provisioning dedicated operator virtual key in LiteLLM DB..."
    curl -s -o /dev/null \
      -X POST "http://127.0.0.1:${LITELLM_PORT}/key/generate" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"key\": \"${OPERATOR_LITELLM_KEY}\", \"key_alias\": \"titan-operator\", \"max_budget\": 100.0, \"models\": []}" || true
    log_success "Operator virtual key provisioned in LiteLLM control plane."
  else
    log_info "Operator virtual key is already registered in LiteLLM control plane."
  fi
else
  log_info "LiteLLM control plane standby or master key unset; skipping live key provisioning."
fi

# ------------------------------------------------------------------------------
# 3. Retire Obsolete SilverBullet Service
# ------------------------------------------------------------------------------
if docker ps -a --format '{{.Names}}' | grep -q "^titan-silverbullet$"; then
  log_info "Retiring obsolete titan-silverbullet container..."
  docker stop titan-silverbullet >/dev/null 2>&1 || true
  docker rm -f titan-silverbullet >/dev/null 2>&1 || true
  log_success "Obsolete titan-silverbullet service cleanly retired."
fi

# ------------------------------------------------------------------------------
# 4. Build & Launch Containerized Operator IDE
# ------------------------------------------------------------------------------
log_info "Building native titan-code-server container image..."
docker compose build code-server

log_info "Starting titan-code-server service..."
docker compose up -d code-server

# Ensure Caddy is recreated or updated with the new titan-operator-net
log_info "Ensuring Caddy gateway is connected to operator network..."
docker compose up -d caddy

log_success "======================================================================"
log_success "Titan Operator IDE is running!"
log_success "Access URLs:"
log_success "  - Ingress:      http://editor.localhost (or http://editor.titan.local)"
log_success "  - Alternate:    http://code.localhost   (or http://code.titan.local)"
log_success "  - Direct Port:  http://127.0.0.1:${CODE_SERVER_PORT:-8443}"
log_success "Credentials:"
log_success "  - HTTP Basic Auth: ${OPERATOR_USER:-operator} / ${CODE_SERVER_PASSWORD:-titan_operator_secret}"
log_success "  - IDE Password:    ${CODE_SERVER_PASSWORD:-titan_operator_secret}"
log_success "======================================================================"
