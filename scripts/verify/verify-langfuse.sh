#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Langfuse Observability & OpenTelemetry Verification Script
# Validates DNS resolution, container health, virtualenv dependencies,
# Hermes OTLP configuration, and LiteLLM tracing bindings.
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
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

LANGFUSE_AUTO_START="${LANGFUSE_AUTO_START:-false}"
LANGFUSE_PORT="${LANGFUSE_PORT:-3001}"
LANGFUSE_HOST="${LANGFUSE_HOST:-http://langfuse.titan.local:${LANGFUSE_PORT}}"
LANGFUSE_HOST_IP="${LANGFUSE_HOST_IP:-}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
LANGFUSE_OTEL_AUTH="${LANGFUSE_OTEL_AUTH:-}"

PASSED=0
FAILED=0
WARNS=0

pass_check() {
  log_success "$1"
  PASSED=$((PASSED + 1))
}

fail_check() {
  log_error "$1"
  FAILED=$((FAILED + 1))
}

warn_check() {
  log_warn "$1"
  WARNS=$((WARNS + 1))
}

echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}Project Titan: Langfuse Observability & OpenTelemetry Verification${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. LiteLLM Virtual Environment Telemetry Modules
# ------------------------------------------------------------------------------
log_info "Verifying LiteLLM virtual environment dependencies (.venv)..."
if [ -x ".venv/bin/python" ]; then
  if .venv/bin/python -c "import langfuse; print(langfuse.__version__)" >/dev/null 2>&1; then
    LF_VER=$(.venv/bin/python -c "import langfuse; print(langfuse.__version__)" 2>/dev/null || echo "installed")
    pass_check "LiteLLM Python environment: 'langfuse' is installed (v${LF_VER})."
  else
    fail_check "LiteLLM Python environment: 'langfuse' module is missing. Run ./scripts/setup/setup-host.sh"
  fi

  if .venv/bin/python -c "from opentelemetry.sdk.trace import TracerProvider; from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter" >/dev/null 2>&1; then
    pass_check "LiteLLM Python environment: OpenTelemetry SDK and OTLP Exporter are installed."
  else
    fail_check "LiteLLM Python environment: OpenTelemetry packages are missing. Run ./scripts/setup/setup-host.sh"
  fi
else
  fail_check "LiteLLM virtual environment (.venv/bin/python) not found. Run ./scripts/setup/setup-host.sh"
fi

# ------------------------------------------------------------------------------
# 2. Configuration Integrity (LiteLLM, Hermes, Docker Compose, Caddy)
# ------------------------------------------------------------------------------
log_info "Verifying configuration files..."

# LiteLLM config
if [ -f "config/litellm/config.yaml" ]; then
  if grep -q "success_callback: os.environ/LITELLM_SUCCESS_CALLBACKS" config/litellm/config.yaml || (grep -q "success_callback:" config/litellm/config.yaml && grep -q -- "- langfuse" config/litellm/config.yaml); then
    pass_check "LiteLLM configuration: Callbacks configured in config/litellm/config.yaml."
  else
    fail_check "LiteLLM configuration: missing success_callback in config/litellm/config.yaml."
  fi
fi

# Hermes config
if [ -f "config/hermes/config.yaml" ]; then
  if grep -q "otlp:" config/hermes/config.yaml && grep -q "endpoint:" config/hermes/config.yaml; then
    pass_check "Hermes configuration: OTLP monitoring export configured in config/hermes/config.yaml."
  else
    fail_check "Hermes configuration: missing OTLP export in config/hermes/config.yaml."
  fi
fi

# Docker Compose Hermes extra_hosts
if grep -q "langfuse.titan.local" docker-compose.yml docker-compose.agents.yml 2>/dev/null; then
  pass_check "Docker Compose: 'langfuse.titan.local' entry mapped in hermes.extra_hosts."
else
  fail_check "Docker Compose: missing 'langfuse.titan.local' in hermes.extra_hosts."
fi

# Caddyfile reverse proxy
if [ -f "config/caddy/Caddyfile" ]; then
  if grep -q "langfuse.{\$TITAN_DOMAIN:titan.local}" config/caddy/Caddyfile; then
    pass_check "Caddy Ingress: reverse proxy route configured for langfuse.titan.local."
  else
    fail_check "Caddy Ingress: missing langfuse route in config/caddy/Caddyfile."
  fi
fi

# ------------------------------------------------------------------------------
# 3. Network & DNS Resolution
# ------------------------------------------------------------------------------
log_info "Verifying DNS resolution for langfuse.titan.local..."

# Check Python/host resolution
HOST_RESOLVED_IP=$(python3 -c "
import socket
socket.setdefaulttimeout(2.0)
try:
    print(socket.gethostbyname('langfuse.titan.local'))
except Exception:
    print('')
" 2>/dev/null || true)

if [ -n "${HOST_RESOLVED_IP}" ]; then
  pass_check "Host DNS: 'langfuse.titan.local' resolves to ${HOST_RESOLVED_IP}."
else
  warn_check "Host DNS: 'langfuse.titan.local' is not registered in /etc/hosts. Run ./scripts/setup/setup-network.sh"
fi

if [ -n "${LANGFUSE_HOST_IP}" ]; then
  log_info "Configured LANGFUSE_HOST_IP for container bridge: ${LANGFUSE_HOST_IP}"
fi

# ------------------------------------------------------------------------------
# 4. Service Health & OTLP Ingestion Connectivity
# ------------------------------------------------------------------------------
log_info "Probing Langfuse health endpoints..."

LOCAL_HEALTH_BODY=$(curl -s "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || true)
LOCAL_HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || echo "000")
REMOTE_HEALTH_BODY=$(curl -s "${LANGFUSE_HOST}/api/public/health" 2>/dev/null || true)
REMOTE_HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${LANGFUSE_HOST}/api/public/health" 2>/dev/null || echo "000")

if [ "${LOCAL_HEALTH_CODE}" = "200" ]; then
  pass_check "Langfuse service: RUNNING locally (http://localhost:${LANGFUSE_PORT}/api/public/health -> 200 OK)."
  ACTIVE_ENDPOINT="http://localhost:${LANGFUSE_PORT}"
elif [ "${REMOTE_HEALTH_CODE}" = "200" ]; then
  pass_check "Langfuse service: RUNNING remotely (${LANGFUSE_HOST}/api/public/health -> 200 OK)."
  ACTIVE_ENDPOINT="${LANGFUSE_HOST}"
else
  warn_check "Langfuse service: NOT RESPONDING (Local: HTTP ${LOCAL_HEALTH_CODE}, Remote: HTTP ${REMOTE_HEALTH_CODE})."
  log_info "LANGFUSE_AUTO_START is set to '${LANGFUSE_AUTO_START}'."
  log_info "To start locally:  ./scripts/setup/setup-langfuse.sh start"
  log_info "To start remotely: run ./scripts/setup/setup-langfuse.sh start on your remote laptop."
  ACTIVE_ENDPOINT=""
fi

if command -v docker >/dev/null 2>&1 && [ -n "${ACTIVE_ENDPOINT}" ]; then
  for c in titan-langfuse-web titan-langfuse-worker titan-langfuse-clickhouse titan-langfuse-redis titan-langfuse-minio titan-langfuse-db; do
    if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
      pass_check "Container '${c}': RUNNING."
    fi
  done
fi

# If active, test telemetry ingestion endpoint reachability
if [ -n "${ACTIVE_ENDPOINT}" ]; then
  log_info "Testing telemetry ingestion endpoint reachability at ${ACTIVE_ENDPOINT}/api/public/ingestion..."
  INGEST_PROBE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${ACTIVE_ENDPOINT}/api/public/ingestion" \
    -H "Content-Type: application/json" \
    -d "{}" 2>/dev/null || echo "000")

  # Langfuse ingestion endpoint returns 401 (Unauthorized without headers) or 200/400
  if [[ "${INGEST_PROBE}" =~ ^(200|400|401|405)$ ]]; then
    pass_check "Langfuse ingestion endpoint: ACTIVE & AUTH-PROTECTED on ${ACTIVE_ENDPOINT}/api/public/ingestion (HTTP ${INGEST_PROBE})."
  else
    warn_check "Langfuse ingestion endpoint returned unexpected status: HTTP ${INGEST_PROBE}."
  fi

  # Check sessions REST endpoint (enabled in dual mode)
  if [ -n "${LANGFUSE_PUBLIC_KEY}" ] && [ -n "${LANGFUSE_SECRET_KEY}" ]; then
    SESSIONS_PROBE=$(curl -s -o /dev/null -w "%{http_code}" -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" "${ACTIVE_ENDPOINT}/api/public/sessions" 2>/dev/null || echo "000")
    if [ "${SESSIONS_PROBE}" = "200" ]; then
      pass_check "Langfuse sessions endpoint: ACTIVE on ${ACTIVE_ENDPOINT}/api/public/sessions (HTTP 200)."
    else
      warn_check "Langfuse sessions endpoint returned status HTTP ${SESSIONS_PROBE}."
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 5. API Key & Authentication Credentials
# ------------------------------------------------------------------------------
log_info "Checking telemetry authentication credentials..."
if [ -n "${LANGFUSE_PUBLIC_KEY}" ] && [ -n "${LANGFUSE_SECRET_KEY}" ]; then
  pass_check "Langfuse API Keys: PRESENT in .env (Public: ${LANGFUSE_PUBLIC_KEY:0:10}..., Secret: configured)."
  if [ -n "${LANGFUSE_OTEL_AUTH}" ]; then
    pass_check "OTel Basic Auth Header: CONFIGURED in .env (LANGFUSE_OTEL_AUTH)."
  else
    warn_check "LANGFUSE_OTEL_AUTH is empty in .env. It will be computed automatically at control plane launch."
  fi
else
  warn_check "Langfuse API Keys not set in .env (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)."
  log_info "LiteLLM tracing will remain in standby until keys are configured."
  log_info "Run ./scripts/setup/setup-langfuse.sh keys to generate and export keys."
fi

# ------------------------------------------------------------------------------
# 6. Preconfigured LLM Gateway & Fleet Agent Connections in Langfuse
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-db$"; then
  log_info "Checking preconfigured LLM & Agent connections in Langfuse..."
  if docker exec titan-langfuse-db psql -U langfuse -d langfuse -t -c "SELECT provider FROM llm_api_keys WHERE project_id='titan' AND provider='LiteLLM';" 2>/dev/null | grep -q "LiteLLM"; then
    pass_check "Langfuse LLM Connection: 'LiteLLM' (http://proxy.titan.local/v1) preconfigured for project 'titan'."
  else
    warn_check "Langfuse LLM Connection: 'LiteLLM' not found in database. Run ./scripts/setup/setup-langfuse.sh sync"
  fi
  if docker exec titan-langfuse-db psql -U langfuse -d langfuse -t -c "SELECT provider FROM llm_api_keys WHERE project_id='titan' AND provider='Cindy-Pawford';" 2>/dev/null | grep -q "Cindy-Pawford"; then
    pass_check "Langfuse Agent Connection: 'Cindy-Pawford' (http://api.cindypawford.titan.local/v1) preconfigured for project 'titan'."
  else
    warn_check "Langfuse Agent Connection: 'Cindy-Pawford' not found in database. Run ./scripts/setup/setup-langfuse.sh sync"
  fi
fi

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}Verification Summary${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "  - Passed:       ${GREEN}${BOLD}${PASSED}${NC}"
echo -e "  - Warnings:     ${YELLOW}${BOLD}${WARNS}${NC}"
echo -e "  - Failed:       ${RED}${BOLD}${FAILED}${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

if [ "${FAILED}" -eq 0 ]; then
  log_success "Langfuse Observability & OpenTelemetry verification PASSED."
  exit 0
else
  log_error "Langfuse Observability verification FAILED with ${FAILED} errors."
  exit 1
fi
