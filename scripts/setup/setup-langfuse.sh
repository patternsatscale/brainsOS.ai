#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Observability Plane Manager (Langfuse v4.38.0)
# Automates provisioning, key generation, startup, and lifecycle management
# for Langfuse distributed stack (Web, Worker, ClickHouse, Redis, MinIO, Postgres).
# ==============================================================================

set -euo pipefail

# Visual styling
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
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

COMPOSE_FILE="${REPO_ROOT}/docker/langfuse/docker-compose.yml"
LANGFUSE_DIR="${REPO_ROOT}/docker/langfuse"
LANGFUSE_ENV_FILE="${LANGFUSE_DIR}/.env"
LANGFUSE_ENV_EXAMPLE="${LANGFUSE_DIR}/.env.example"

# Load parent .env if present for project-level overrides
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Load langfuse-specific .env if present (takes precedence for Langfuse container)
if [ -f "${LANGFUSE_ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${LANGFUSE_ENV_FILE}"
  set +a
fi

LANGFUSE_PORT="${LANGFUSE_PORT:-3001}"
LANGFUSE_DB_DATA_DIR="${LANGFUSE_DB_DATA_DIR:-${REPO_ROOT}/data/langfuse_db}"
LANGFUSE_CLICKHOUSE_DATA_DIR="${LANGFUSE_CLICKHOUSE_DATA_DIR:-${REPO_ROOT}/data/langfuse_clickhouse}"
LANGFUSE_REDIS_DATA_DIR="${LANGFUSE_REDIS_DATA_DIR:-${REPO_ROOT}/data/langfuse_redis}"
LANGFUSE_MINIO_DATA_DIR="${LANGFUSE_MINIO_DATA_DIR:-${REPO_ROOT}/data/langfuse_minio}"

# Helper to run compose commands
compose_cmd() {
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    docker compose -f "${COMPOSE_FILE}" --env-file "${LANGFUSE_ENV_FILE}" "$@"
  else
    docker compose -f "${COMPOSE_FILE}" "$@"
  fi
}

# ------------------------------------------------------------------------------
# Action: Setup
# ------------------------------------------------------------------------------
setup_langfuse() {
  log_info "Configuring Langfuse v4.38.0 distributed observability environment..."

  mkdir -p "${LANGFUSE_DB_DATA_DIR}" "${LANGFUSE_CLICKHOUSE_DATA_DIR}" "${LANGFUSE_REDIS_DATA_DIR}" "${LANGFUSE_MINIO_DATA_DIR}"

  if [ ! -f "${LANGFUSE_ENV_FILE}" ]; then
    log_info "Creating ${LANGFUSE_ENV_FILE} from template..."
    if [ -f "${LANGFUSE_ENV_EXAMPLE}" ]; then
      cp "${LANGFUSE_ENV_EXAMPLE}" "${LANGFUSE_ENV_FILE}"
    else
      touch "${LANGFUSE_ENV_FILE}"
    fi
  fi

  # Generate cryptographically secure keys
  log_info "Verifying secure cryptographic keys and auto-initialization credentials..."
  SEC_NEXTAUTH="${NEXTAUTH_SECRET:-$(openssl rand -base64 32)}"
  SEC_SALT="${SALT:-$(openssl rand -base64 32)}"
  SEC_ENCRYPT="${ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
  SEC_DB_PASS="${LANGFUSE_DB_PASSWORD:-$(openssl rand -hex 16)}"
  SEC_REDIS="${REDIS_AUTH:-$(openssl rand -hex 16)}"
  SEC_MINIO="${MINIO_ROOT_PASSWORD:-$(openssl rand -hex 16)}"

  # Ensure API Keys exist (or auto-generate for zero-click fleet setup)
  SEC_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-pk-lf-$(openssl rand -hex 16)}"
  SEC_SECRET_KEY="${LANGFUSE_SECRET_KEY:-sk-lf-$(openssl rand -hex 16)}"
  SEC_OTEL_AUTH="Basic $(echo -n "${SEC_PUBLIC_KEY}:${SEC_SECRET_KEY}" | base64)"

  # Helper to set or update key-value in a file safely
  update_env_var() {
    local key="$1"
    local val="$2"
    local file="$3"
    if grep -q "^${key}=" "${file}" 2>/dev/null; then
      sed -i.bak "s|^${key}=.*|${key}=${val}|" "${file}" && rm -f "${file}.bak"
    else
      echo "${key}=${val}" >> "${file}"
    fi
  }

  # Write keys to Langfuse .env
  update_env_var "NEXTAUTH_SECRET" "${SEC_NEXTAUTH}" "${LANGFUSE_ENV_FILE}"
  update_env_var "SALT" "${SEC_SALT}" "${LANGFUSE_ENV_FILE}"
  update_env_var "ENCRYPTION_KEY" "${SEC_ENCRYPT}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_DB_PASSWORD" "${SEC_DB_PASS}" "${LANGFUSE_ENV_FILE}"
  update_env_var "REDIS_AUTH" "${SEC_REDIS}" "${LANGFUSE_ENV_FILE}"
  update_env_var "MINIO_ROOT_PASSWORD" "${SEC_MINIO}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_PUBLIC_KEY" "${SEC_PUBLIC_KEY}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_SECRET_KEY" "${SEC_SECRET_KEY}" "${LANGFUSE_ENV_FILE}"

  # Also ensure root .env has these keys for LiteLLM and Agent Fleet synchronization
  if [ -f "${REPO_ROOT}/.env" ]; then
    update_env_var "LANGFUSE_HOST" "http://langfuse.titan.local:${LANGFUSE_PORT}" "${REPO_ROOT}/.env"
    update_env_var "LANGFUSE_PUBLIC_KEY" "${SEC_PUBLIC_KEY}" "${REPO_ROOT}/.env"
    update_env_var "LANGFUSE_SECRET_KEY" "${SEC_SECRET_KEY}" "${REPO_ROOT}/.env"
    update_env_var "LANGFUSE_OTEL_AUTH" "${SEC_OTEL_AUTH}" "${REPO_ROOT}/.env"
  fi

  export LANGFUSE_HOST="http://langfuse.titan.local:${LANGFUSE_PORT}"
  export LANGFUSE_PUBLIC_KEY="${SEC_PUBLIC_KEY}"
  export LANGFUSE_SECRET_KEY="${SEC_SECRET_KEY}"
  export LANGFUSE_OTEL_AUTH="${SEC_OTEL_AUTH}"

  log_success "Langfuse v4.38.0 configuration synchronized."
}

# ------------------------------------------------------------------------------
# Action: Start
# ------------------------------------------------------------------------------
start_langfuse() {
  setup_langfuse

  log_info "Starting Langfuse v4.38.0 stack (Web on :${LANGFUSE_PORT}, Worker, ClickHouse, Redis, MinIO, Postgres)..."
  compose_cmd up -d

  log_info "Waiting for Langfuse web service to report healthy on http://localhost:${LANGFUSE_PORT}..."
  READY=false
  for i in {1..90}; do
    STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" || echo "000")
    if [ "${STATUS_CODE}" = "200" ]; then
      READY=true
      break
    fi
    sleep 1
  done

  if [ "${READY}" = true ]; then
    log_success "Langfuse v4.38.0 is running and healthy!"
    echo ""
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "${GREEN}${BOLD}Langfuse v4.38.0 Observability Platform Ready${NC}"
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "  - Web Dashboard:     ${BOLD}http://localhost:${LANGFUSE_PORT}${NC} (or http://langfuse.titan.local)"
    echo -e "  - OTel Ingestion:    ${BOLD}http://localhost:${LANGFUSE_PORT}/api/public/otel${NC}"
    echo -e "  - Public Key:        ${BOLD}${LANGFUSE_PUBLIC_KEY:-}${NC}"
    echo -e "  - Admin Email:       ${BOLD}admin@titan.local${NC}"
    echo -e "  - Admin Password:    ${BOLD}titan_admin_secret${NC}"
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
  else
    log_warn "Langfuse containers started, but /api/public/health did not return 200 within 90s."
    log_info "Check service logs via: ./scripts/setup/setup-langfuse.sh logs"
  fi
}

# ------------------------------------------------------------------------------
# Action: Stop
# ------------------------------------------------------------------------------
stop_langfuse() {
  log_info "Stopping Langfuse container stack..."
  compose_cmd down
  log_success "Langfuse container stack stopped."
}

# ------------------------------------------------------------------------------
# Action: Status
# ------------------------------------------------------------------------------
status_langfuse() {
  log_info "Checking Langfuse service status..."
  compose_cmd ps
  echo ""
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || echo "000")
  if [ "${STATUS_CODE}" = "200" ]; then
    log_success "Langfuse API Health: ONLINE (http://localhost:${LANGFUSE_PORT}/api/public/health -> 200 OK)"
  else
    log_warn "Langfuse API Health: OFFLINE or NOT RESPONDING (HTTP ${STATUS_CODE})"
  fi
}

# ------------------------------------------------------------------------------
# Action: Logs
# ------------------------------------------------------------------------------
logs_langfuse() {
  compose_cmd logs -f "$@"
}

# ------------------------------------------------------------------------------
# Action: Keys / Creds Display & Generator
# ------------------------------------------------------------------------------
generate_keys_helper() {
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  echo -e "${BLUE}${BOLD}Project Titan: Langfuse API Key & Telemetry Header Helper${NC}"
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  if [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
    echo "Currently active credentials:"
    echo "  LANGFUSE_HOST=http://langfuse.titan.local:${LANGFUSE_PORT}"
    echo "  LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}"
    echo "  LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}"
    echo "  LANGFUSE_OTEL_AUTH=${LANGFUSE_OTEL_AUTH:-Basic $(echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64)}"
    echo ""
  fi
}

case "${1:-status}" in
  setup)
    setup_langfuse
    ;;
  start)
    start_langfuse
    ;;
  stop)
    stop_langfuse
    ;;
  restart)
    stop_langfuse
    sleep 1
    start_langfuse
    ;;
  status)
    status_langfuse
    ;;
  logs)
    shift || true
    logs_langfuse "$@"
    ;;
  keys|creds)
    generate_keys_helper
    ;;
  *)
    echo "Usage: $0 {setup|start|stop|restart|status|logs|keys}"
    exit 1
    ;;
esac
