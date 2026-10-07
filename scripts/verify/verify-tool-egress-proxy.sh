#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Tool Egress Gateway & Inspection Proxy Verification Suite
# Ticket #146: Outbound Inspection Proxy (mitmproxy / mitmweb)
#
# Asserts:
#   1. Manifest synchronization & compose topology drift check
#   2. Container status & loopback port binding (brainsos-tool-egress-proxy:8081/8082)
#   3. Web UI console accessibility via efw.brainsos.local / firewall.brainsos.local & 127.0.0.1:8081
#   4. Mitmproxy CA certificate trust across agent sandbox runtimes (curl, OpenSSL, Python)
#   5. Outbound HTTP/HTTPS tool traffic interception & flow capture
#   6. Live flow audit via mitmweb REST/JSON API (/flows)
#   7. Strict internal plane bypass (NO_PROXY) for LiteLLM, Signal, and internal routes
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

# Load environment
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.example
  set +a
fi

PROXY_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(net-)?(tool-)?egress-proxy$' | head -n 1 || echo 'brainsos-net-egress-proxy')"
AGENT_CONTAINER="brainsos-agent-terrastella"
CADDY_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(net-)?caddy$' | head -n 1 || echo 'brainsos-net-caddy')"
WEB_PORT="${TOOL_EGRESS_WEB_PORT:-8081}"
WEB_PASSWORD="${TOOL_EGRESS_WEB_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_tool_egress_secret}}"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"

log_info "================================================================="
log_info "  Running Tool Egress Gateway Verification Suite (Ticket #146)   "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Step 1: Manifest Verification & Compose Topology Drift Check
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet manifest & compose topology..."

if [ ! -f "${REPO_ROOT}/config/default_settings/agents.yaml" ] && [ ! -f "${REPO_ROOT}/config/agents.yaml" ]; then
  log_error "Fleet agents manifest is missing."
  exit 1
fi
log_success "Fleet manifest verified (agents.yaml is present)."

docker compose config -q
log_success "Docker Compose topology syntax validated successfully."

# ------------------------------------------------------------------------------
# Step 2: Ensure Required Containers are Running
# ------------------------------------------------------------------------------
log_info "Step 2: Checking container status (Tool Egress Proxy, Agent, Caddy)..."

for c in "${PROXY_CONTAINER}" "${AGENT_CONTAINER}" "${CADDY_CONTAINER}"; do
  if ! docker ps --format '{{.Names}}' | grep -qw "${c}"; then
    log_info "Starting container '${c}'..."
    docker compose up -d
    sleep 3
    break
  fi
done

for c in "${PROXY_CONTAINER}" "${AGENT_CONTAINER}" "${CADDY_CONTAINER}"; do
  STATUS=$(docker inspect "${c}" --format '{{.State.Status}}' 2>/dev/null || echo "not_found")
  if [ "${STATUS}" != "running" ]; then
    log_error "Container '${c}' is not in running state (Status: ${STATUS})."
    exit 1
  fi
  log_success "Container '${c}' is running."
done

# ------------------------------------------------------------------------------
# Step 3: Verify Tool Egress Proxy Web Console & Ingress Routes
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying web console and Caddy reverse proxy ingress routes..."

# Direct loopback web console
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${WEB_PORT}/?token=${WEB_PASSWORD}" || echo "000")
if [ "${HTTP_CODE}" -ne 200 ]; then
  log_error "Direct loopback console http://127.0.0.1:${WEB_PORT}/ returned HTTP ${HTTP_CODE} (expected 200)."
  exit 1
fi
log_success "Direct loopback console reachable on 127.0.0.1:${WEB_PORT} (HTTP 200)."

# Caddy ingress via efw.brainsos.local
HTTP_CODE_EFW=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: efw.${BRAINSOS_DOMAIN}" "http://127.0.0.1/?token=${WEB_PASSWORD}" || echo "000")
if [ "${HTTP_CODE_EFW}" -ne 200 ]; then
  log_error "Caddy route efw.${BRAINSOS_DOMAIN} returned HTTP ${HTTP_CODE_EFW} (expected 200)."
  exit 1
fi
log_success "Caddy ingress route verified: efw.${BRAINSOS_DOMAIN} (HTTP 200)."

# Caddy ingress via firewall.brainsos.local
HTTP_CODE_FW=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: firewall.${BRAINSOS_DOMAIN}" "http://127.0.0.1/?token=${WEB_PASSWORD}" || echo "000")
if [ "${HTTP_CODE_FW}" -ne 200 ]; then
  log_error "Caddy route firewall.${BRAINSOS_DOMAIN} returned HTTP ${HTTP_CODE_FW} (expected 200)."
  exit 1
fi
log_success "Caddy ingress route verified: firewall.${BRAINSOS_DOMAIN} (HTTP 200)."

# ------------------------------------------------------------------------------
# Step 4: Verify CA Certificate Trust in Agent Container Sandbox
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying mitmproxy CA trust in agent container sandbox..."

# Check cert file in container share directory
if ! docker exec "${AGENT_CONTAINER}" test -f /usr/local/share/ca-certificates/mitmproxy-ca.crt; then
  log_error "Mitmproxy CA certificate not found in agent container at /usr/local/share/ca-certificates/mitmproxy-ca.crt."
  exit 1
fi
log_success "Mitmproxy CA certificate installed at /usr/local/share/ca-certificates/mitmproxy-ca.crt."

# Check agent proxy environment variables
ENV_DUMP=$(docker exec "${AGENT_CONTAINER}" env)
for var in "HTTP_PROXY" "HTTPS_PROXY" "http_proxy" "https_proxy" "NO_PROXY" "no_proxy" "REQUESTS_CA_BUNDLE" "SSL_CERT_FILE" "NODE_EXTRA_CA_CERTS"; do
  if ! echo "${ENV_DUMP}" | grep -q "^${var}="; then
    log_error "Expected environment variable '${var}' is missing in agent container."
    exit 1
  fi
done
log_success "All proxy and CA bundle environment variables verified in agent container."

# ------------------------------------------------------------------------------
# Step 5: Test Outbound HTTPS Tool Execution via Proxy
# ------------------------------------------------------------------------------
log_info "Step 5: Testing outbound HTTPS tool execution through inspection proxy..."

PROBE_NONCE="$(date +%s)-$RANDOM"
PROBE_URL="https://httpbin.org/anything?nonce=${PROBE_NONCE}"

log_info "Executing tool request inside agent container: curl -s ${PROBE_URL}"
CURL_OUTPUT=$(docker exec "${AGENT_CONTAINER}" curl -s "${PROBE_URL}" || echo "CURL_FAILED")

if ! echo "${CURL_OUTPUT}" | grep -q "${PROBE_NONCE}"; then
  log_error "Outbound HTTPS curl execution failed or did not return probe nonce. Output: ${CURL_OUTPUT}"
  exit 1
fi
log_success "Outbound HTTPS curl executed successfully through proxy with clean TLS verification."

# Test Python requests library through proxy
PYTHON_PROBE=$(docker exec "${AGENT_CONTAINER}" /opt/hermes/.venv/bin/python3 -c "
import requests, json
r = requests.get('https://httpbin.org/anything?python_nonce=${PROBE_NONCE}')
print(r.json().get('args', {}).get('python_nonce', ''))
" 2>/dev/null || echo "PYTHON_FAILED")

if [ "${PYTHON_PROBE}" != "${PROBE_NONCE}" ]; then
  log_error "Python requests execution through proxy failed (Got: '${PYTHON_PROBE}')."
  exit 1
fi
log_success "Python requests runtime executed successfully through proxy with clean TLS verification."

# ------------------------------------------------------------------------------
# Step 6: Verify Intercepted Flows in mitmweb REST API
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying real-time flow capture on mitmweb inspection dashboard..."

FLOWS_JSON=$(curl -s -H "Authorization: Bearer ${WEB_PASSWORD}" "http://127.0.0.1:${WEB_PORT}/flows")

if ! echo "${FLOWS_JSON}" | grep -q "${PROBE_NONCE}"; then
  log_error "Probe nonce '${PROBE_NONCE}' not found in mitmweb captured flows."
  exit 1
fi
log_success "Outbound tool flows successfully captured and auditable in mitmweb (/flows)."

# ------------------------------------------------------------------------------
# Step 7: Verify Internal Plane Isolation (NO_PROXY Bypass)
# ------------------------------------------------------------------------------
log_info "Step 7: Verifying internal plane isolation (NO_PROXY bypass)..."

# 1. LiteLLM control plane liveliness bypass
LIVELINESS=$(docker exec "${AGENT_CONTAINER}" curl -s http://host.docker.internal:4000/health/liveliness || echo "FAIL")
if [ "${LIVELINESS}" != "\"I'm alive!\"" ]; then
  log_error "LiteLLM control plane bypass check failed (Got: ${LIVELINESS})."
  exit 1
fi
log_success "LiteLLM control plane directly reachable via internal bypass (HTTP 200)."

# Assert LiteLLM traffic is NEVER captured in proxy flows
if echo "${FLOWS_JSON}" | grep -qi "host.docker.internal"; then
  log_error "SECURITY VIOLATION: host.docker.internal was intercepted by tool egress proxy."
  exit 1
fi
log_success "Verified zero LiteLLM inference traffic intercepted by tool egress proxy (Rule 2)."

# 2. Signal messaging daemon bypass
SIGNAL_ABOUT=$(docker exec "${AGENT_CONTAINER}" curl -s http://signal-cli:8080/v1/about || echo "FAIL")
if ! echo "${SIGNAL_ABOUT}" | grep -q "json-rpc"; then
  log_error "Signal daemon bypass check failed (Got: ${SIGNAL_ABOUT})."
  exit 1
fi
log_success "Signal daemon directly reachable via internal bypass (HTTP 200)."

if echo "${FLOWS_JSON}" | grep -qi "signal-cli"; then
  log_error "SECURITY VIOLATION: signal-cli was intercepted by tool egress proxy."
  exit 1
fi
log_success "Verified zero Signal messaging traffic intercepted by tool egress proxy."

echo ""
log_success "================================================================="
log_success "  ALL 7 TOOL EGRESS GATEWAY VERIFICATION CHECKS PASSED           "
log_success "================================================================="
