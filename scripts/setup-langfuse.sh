#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Standalone Langfuse Observability Service Manager
# Automates provisioning, key generation, startup, and lifecycle management
# for Langfuse on this machine or a remote laptop on the LAN.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
  log_info "Configuring Langfuse standalone environment..."

  mkdir -p "${LANGFUSE_DB_DATA_DIR}"

  if [ ! -f "${LANGFUSE_ENV_FILE}" ]; then
    log_info "Creating ${LANGFUSE_ENV_FILE} from template..."
    if [ -f "${LANGFUSE_ENV_EXAMPLE}" ]; then
      cp "${LANGFUSE_ENV_EXAMPLE}" "${LANGFUSE_ENV_FILE}"
    else
      touch "${LANGFUSE_ENV_FILE}"
    fi

    # Generate cryptographically secure keys
    log_info "Generating secure cryptographic keys for Langfuse..."
    SEC_NEXTAUTH="$(openssl rand -base64 32)"
    SEC_SALT="$(openssl rand -base64 32)"
    SEC_ENCRYPT="$(openssl rand -hex 32)"
    if [ -f "${LANGFUSE_DB_DATA_DIR}/PG_VERSION" ]; then
      SEC_DB_PASS="${LANGFUSE_DB_PASSWORD:-titan_langfuse_secret_change_me}"
    else
      SEC_DB_PASS="$(openssl rand -hex 16)"
    fi

    # Safely write or replace in .env
    sed -i.bak "s|^NEXTAUTH_SECRET=.*|NEXTAUTH_SECRET=${SEC_NEXTAUTH}|" "${LANGFUSE_ENV_FILE}" 2>/dev/null || \
      echo "NEXTAUTH_SECRET=${SEC_NEXTAUTH}" >> "${LANGFUSE_ENV_FILE}"
    sed -i.bak "s|^SALT=.*|SALT=${SEC_SALT}|" "${LANGFUSE_ENV_FILE}" 2>/dev/null || \
      echo "SALT=${SEC_SALT}" >> "${LANGFUSE_ENV_FILE}"
    sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${SEC_ENCRYPT}|" "${LANGFUSE_ENV_FILE}" 2>/dev/null || \
      echo "ENCRYPTION_KEY=${SEC_ENCRYPT}" >> "${LANGFUSE_ENV_FILE}"
    sed -i.bak "s|^LANGFUSE_DB_PASSWORD=.*|LANGFUSE_DB_PASSWORD=${SEC_DB_PASS}|" "${LANGFUSE_ENV_FILE}" 2>/dev/null || \
      echo "LANGFUSE_DB_PASSWORD=${SEC_DB_PASS}" >> "${LANGFUSE_ENV_FILE}"
    rm -f "${LANGFUSE_ENV_FILE}.bak"

    log_success "Generated new Langfuse security secrets in ${LANGFUSE_ENV_FILE}."
  else
    log_info "Langfuse environment file already exists at ${LANGFUSE_ENV_FILE}."
  fi
}

# ------------------------------------------------------------------------------
# Action: Start
# ------------------------------------------------------------------------------
start_langfuse() {
  setup_langfuse

  log_info "Starting Langfuse container stack (Web on :${LANGFUSE_PORT}, Postgres)..."
  compose_cmd up -d

  log_info "Waiting for Langfuse web service to report healthy on http://localhost:${LANGFUSE_PORT}..."
  READY=false
  for i in {1..45}; do
    STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" || echo "000")
    if [ "${STATUS_CODE}" = "200" ]; then
      READY=true
      break
    fi
    sleep 1
  done

  if [ "${READY}" = true ]; then
    log_success "Langfuse is running and healthy!"
    echo ""
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "${GREEN}${BOLD}Langfuse Observability Platform Ready${NC}"
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "  - Web Dashboard:     ${BOLD}http://localhost:${LANGFUSE_PORT}${NC} (or http://langfuse.titan.local:${LANGFUSE_PORT})"
    echo -e "  - OTel Ingestion:    ${BOLD}http://localhost:${LANGFUSE_PORT}/api/public/otel${NC}"
    echo -e "  - Data Directory:    ${LANGFUSE_DB_DATA_DIR}"
    echo ""
    echo -e "Next steps:"
    echo -e "  1. Open ${BOLD}http://localhost:${LANGFUSE_PORT}${NC} in your browser and create your admin account."
    echo -e "  2. Create a new Project (e.g. 'Titan')."
    echo -e "  3. Go to Project Settings -> API Keys -> Create new API Keys."
    echo -e "  4. Run ${BOLD}./scripts/setup-langfuse.sh keys${NC} to configure Titan's .env automatically."
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
  else
    log_warn "Langfuse containers started, but /api/public/health did not return 200 within 45s."
    log_info "Check service logs via: ./scripts/setup-langfuse.sh logs"
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
  compose_cmd logs -f
}

# ------------------------------------------------------------------------------
# Action: Keys / Creds Generator
# ------------------------------------------------------------------------------
generate_keys_helper() {
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  echo -e "${BLUE}${BOLD}Project Titan: Langfuse API Key & Telemetry Header Helper${NC}"
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  echo "Paste the API keys generated from your Langfuse Web Console:"
  echo ""

  read -r -p "Enter Langfuse Public Key (pk-lf-...): " USER_PK
  read -r -p "Enter Langfuse Secret Key (sk-lf-...): " USER_SK

  if [ -z "${USER_PK}" ] || [ -z "${USER_SK}" ]; then
    log_error "Both Public Key and Secret Key are required."
    exit 1
  fi

  # Compute Base64 Basic auth header: Basic <base64(pk:sk)>
  BASE64_AUTH="Basic $(echo -n "${USER_PK}:${USER_SK}" | base64)"

  echo ""
  echo -e "${GREEN}${BOLD}Add the following lines to your Project Titan .env file on the GX10 appliance:${NC}"
  echo "------------------------------------------------------------------------------"
  echo "LANGFUSE_HOST=http://langfuse.titan.local:${LANGFUSE_PORT}"
  echo "LANGFUSE_PUBLIC_KEY=${USER_PK}"
  echo "LANGFUSE_SECRET_KEY=${USER_SK}"
  echo "LANGFUSE_OTEL_AUTH=${BASE64_AUTH}"
  echo "------------------------------------------------------------------------------"
  echo ""
  log_info "If running Langfuse on a separate laptop, also set LANGFUSE_HOST_IP=<laptop-ip> in Titan's .env."
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
    logs_langfuse
    ;;
  keys|creds)
    generate_keys_helper
    ;;
  *)
    echo "Usage: $0 {setup|start|stop|restart|status|logs|keys}"
    exit 1
    ;;
esac
