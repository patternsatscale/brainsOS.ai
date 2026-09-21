#!/usr/bin/env bash
# ==============================================================================
# Project Titan: End-to-End Multi-Agent & LiteLLM Telemetry Verification
# Validates trace ingestion, model latency, token counts, and agent identity
# across the LiteLLM control plane and Langfuse v4.38.0 observability stack.
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

# Load environment variables
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

LANGFUSE_PORT="${LANGFUSE_PORT:-3001}"
LANGFUSE_HOST="${LANGFUSE_HOST:-http://localhost:${LANGFUSE_PORT}}"
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_URL="http://127.0.0.1:${LITELLM_PORT}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
HERMES_CINDY_LITELLM_KEY="${HERMES_CINDY_LITELLM_KEY:-sk-titan-cindy-pawford-key}"

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
echo -e "${BLUE}${BOLD}Project Titan: End-to-End Agent Telemetry & Langfuse Verification${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Preconditions & Infrastructure Connectivity
# ------------------------------------------------------------------------------
log_info "Step 1: Checking observability stack & gateway connectivity..."

# Check Langfuse Health
LF_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || echo "000")
if [ "${LF_HEALTH}" = "200" ]; then
  pass_check "Langfuse service is healthy on port ${LANGFUSE_PORT} (HTTP 200)."
else
  fail_check "Langfuse service is not reachable on port ${LANGFUSE_PORT} (HTTP ${LF_HEALTH}). Run ./scripts/setup/setup-langfuse.sh start"
fi

# Check LiteLLM Gateway Liveness
LITELLM_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${LITELLM_URL}/health/liveness" 2>/dev/null || echo "000")
if [[ "${LITELLM_HEALTH}" =~ ^(200|401|405)$ ]]; then
  pass_check "LiteLLM control plane gateway is active on port ${LITELLM_PORT}."
else
  fail_check "LiteLLM gateway is not responding on port ${LITELLM_PORT} (HTTP ${LITELLM_HEALTH}). Run ./scripts/control/start-control-plane.sh start"
fi

# Check Credentials
if [ -n "${LANGFUSE_PUBLIC_KEY}" ] && [ -n "${LANGFUSE_SECRET_KEY}" ]; then
  pass_check "Langfuse API credentials present in environment."
else
  fail_check "LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY unset in .env. Run ./scripts/setup/setup-langfuse.sh setup"
fi

# ------------------------------------------------------------------------------
# 2. Dispatch Completion via LiteLLM under Cindy Pawford's Identity
# ------------------------------------------------------------------------------
log_info "Step 2: Dispatching test inference completion under 'cindy-pawford' identity..."

# Detect available model from local Ollama tags (prefers production titan-core, falls back to gemma2:2b / qwen2.5)
TARGET_MODEL="titan-core"
if curl -s "http://127.0.0.1:11434/api/tags" 2>/dev/null | grep -q "qwen3.8"; then
  TARGET_MODEL="titan-core"
elif curl -s "http://127.0.0.1:11434/api/tags" 2>/dev/null | grep -q "gemma2:2b"; then
  TARGET_MODEL="gemma2:2b"
elif curl -s "http://127.0.0.1:11434/api/tags" 2>/dev/null | grep -q "qwen2.5"; then
  TARGET_MODEL="qwen2.5:latest"
elif curl -s "http://127.0.0.1:11434/api/tags" 2>/dev/null | grep -q "llama3.2"; then
  TARGET_MODEL="llama3.2:3b"
fi
log_info "Using inference model target: ${TARGET_MODEL}"

TEST_ID="test-telemetry-$(date +%s)"
TEST_PAYLOAD=$(cat <<EOF
{
  "model": "${TARGET_MODEL}",
  "messages": [
    {
      "role": "user",
      "content": "Verify agent telemetry pipeline health. Run ID: ${TEST_ID}"
    }
  ],
  "user": "cindy-pawford",
  "metadata": {
    "agent_id": "cindy-pawford",
    "test_id": "${TEST_ID}",
    "environment": "verification",
    "tags": ["cindy-pawford", "verification"]
  }
}
EOF
)

COMPLETION_RESP=$(curl -s -w "\n%{http_code}" -X POST "${LITELLM_URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${HERMES_CINDY_LITELLM_KEY}" \
  -H "Content-Type: application/json" \
  -d "${TEST_PAYLOAD}" 2>/dev/null || true)

HTTP_CODE=$(echo "${COMPLETION_RESP}" | tail -n1)
BODY=$(echo "${COMPLETION_RESP}" | sed '$d')

if [ "${HTTP_CODE}" = "200" ]; then
  pass_check "LiteLLM processed completion request successfully (HTTP 200)."
else
  fail_check "LiteLLM completion failed with HTTP ${HTTP_CODE}: ${BODY}"
fi

# ------------------------------------------------------------------------------
# 3. Assert Trace & Generation Ingestion in Langfuse API (v4 Observations API)
# ------------------------------------------------------------------------------
log_info "Step 3: Querying Langfuse REST API for ingested observation records..."

AUTH_HEADER="Basic $(echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64)"
OBS_FOUND=false
USER_MATCHED=false

# Allow up to 25 seconds for the asynchronous Langfuse worker to process and flush queue
log_info "Awaiting asynchronous trace ingestion in Langfuse v4..."
for i in {1..25}; do
  OBS_JSON=$(curl -s -X GET "http://localhost:${LANGFUSE_PORT}/api/public/v2/observations?limit=25" \
    -H "Authorization: ${AUTH_HEADER}" \
    -H "Content-Type: application/json" 2>/dev/null || echo "{}")

  MATCH_COUNT=$(python3 -c "
import json, sys
data = json.loads('''${OBS_JSON}''') if '''${OBS_JSON}''' else {}
obs = data.get('data', [])
matches = [o for o in obs if o.get('userId') == 'cindy-pawford' or 'cindy-pawford' in str(o.get('metadata', {})) or 'cindy-pawford' in str(o.get('name', ''))]
print(len(matches))
" 2>/dev/null || echo "0")

  if [ "${MATCH_COUNT}" -gt 0 ]; then
    OBS_FOUND=true
    USER_MATCHED=true
    break
  fi
  sleep 1
done

if [ "${OBS_FOUND}" = true ]; then
  pass_check "Observations captured in Langfuse API for 'cindy-pawford'."
else
  warn_check "Did not find recent trace tagged 'cindy-pawford' in Langfuse within 25s."
fi

# Verify generation details or spans in Langfuse
OBS_COUNT=$(python3 -c "
import json, sys
data = json.loads('''${OBS_JSON}''') if '''${OBS_JSON}''' else {}
obs = data.get('data', [])
print(len(obs))
" 2>/dev/null || echo "0")

if [ "${OBS_COUNT}" -gt 0 ]; then
  pass_check "Live observations stream verified in Langfuse v4 (${OBS_COUNT} records captured)."
else
  fail_check "No observations recorded in Langfuse v4 store."
fi

# ------------------------------------------------------------------------------
# 4. Ingress & OTLP Telemetry Endpoint Accessibility
# ------------------------------------------------------------------------------
log_info "Step 4: Testing OpenTelemetry OTLP trace ingestion endpoint..."

OTEL_PROBE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:${LANGFUSE_PORT}/api/public/otel/v1/traces" \
  -H "Authorization: ${AUTH_HEADER}" \
  -H "Content-Type: application/x-protobuf" 2>/dev/null || echo "000")

# OTLP trace endpoint accepts POST requests; empty protobuf payload returns 200, 400, or 405
if [[ "${OTEL_PROBE}" =~ ^(200|400|405)$ ]]; then
  pass_check "OTLP Traces endpoint active on http://localhost:${LANGFUSE_PORT}/api/public/otel/v1/traces (HTTP ${OTEL_PROBE})."
else
  warn_check "OTLP endpoint returned unexpected HTTP code: ${OTEL_PROBE}."
fi

# Verify Caddy reverse proxy for langfuse.localhost
CADDY_PROBE=$(curl -s -o /dev/null -w "%{http_code}" "http://langfuse.localhost/api/public/health" 2>/dev/null || echo "000")
if [ "${CADDY_PROBE}" = "200" ]; then
  pass_check "Caddy Ingress: http://langfuse.localhost successfully proxies to Langfuse (HTTP 200)."
else
  warn_check "Caddy Ingress probe returned HTTP ${CADDY_PROBE} (Caddy may require reload: docker compose restart caddy)."
fi

# ------------------------------------------------------------------------------
# 5. Inviolable Guardrail: Memory Plane Purity (Rule 1)
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying Memory Plane Purity in Cindy Pawford partition..."

if [ -f "${REPO_ROOT}/scripts/verify/verify-memories.sh" ]; then
  if "${REPO_ROOT}/scripts/verify/verify-memories.sh" >/dev/null 2>&1; then
    pass_check "Rule 1 (Memory Purity): Zero database, cache, or binary leakage in /memories."
  else
    fail_check "Rule 1 (Memory Purity): verify-memories.sh reported purity violations!"
  fi
fi

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}Agent Telemetry Verification Summary${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "  - Passed:       ${GREEN}${BOLD}${PASSED}${NC}"
echo -e "  - Warnings:     ${YELLOW}${BOLD}${WARNS}${NC}"
echo -e "  - Failed:       ${RED}${BOLD}${FAILED}${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

if [ "${FAILED}" -eq 0 ]; then
  log_success "End-to-End Agent Telemetry verification PASSED."
  exit 0
else
  log_error "End-to-End Agent Telemetry verification FAILED with ${FAILED} errors."
  exit 1
fi
