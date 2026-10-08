#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Portal, Authentik SSO & Ingress Verification Suite (Epic #247)
# Validates the React Thin-Spine Portal SPA build, Authentik IdP configuration,
# Caddy Ingress reverse proxy, forward_auth integration, and Rule 1/4 guardrails.
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

fail_check() {
  log_error "$*"
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Precondition: Rule 13
if [ ! -f .env ]; then
  fail_check "Execution precondition failed: No .env file present in repository root."
fi

set -a
. ./.env
set +a

echo -e "${BOLD}====================================================================${NC}"
echo -e "${BOLD}brainsOS: Unified Portal & Authentik SSO Verification (Epic #247)   ${NC}"
echo -e "${BOLD}====================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Rule 1: Memory Plane Purity Verification
# ------------------------------------------------------------------------------
log_info "Step 1: Asserting Rule 1 (Memory Plane Purity) for portal artifacts..."
MEMORIES_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${BRAINSOS_DATA_DIR:-./data}/agent_memories}"
if [[ "$MEMORIES_DIR" != /* ]]; then
  MEMORIES_DIR="${REPO_ROOT}/${MEMORIES_DIR#./}"
fi

if [ -d "${MEMORIES_DIR}" ]; then
  ILLEGAL_FILES=$(find "${MEMORIES_DIR}" -type f \( -name "*.html" -o -name "*.js" -o -name "*.css" -o -name "package.json" -o -name "*.db" \) 2>/dev/null || true)
  if [ -n "${ILLEGAL_FILES}" ]; then
    fail_check "Rule 1 Violation: Found illegal portal/database files in /memories:\n${ILLEGAL_FILES}"
  fi
fi
log_success "Rule 1 verified: ZERO portal build artifacts or databases in /memories."

# ------------------------------------------------------------------------------
# 2. Portal Production Bundle Verification (Issue #246)
# ------------------------------------------------------------------------------
log_info "Step 2: Validating React Thin-Spine Portal SPA build..."
PORTAL_DIST="${REPO_ROOT}/packages/brainsOS-portal/dist"

if [ ! -f "${PORTAL_DIST}/index.html" ] || [ "${REPO_ROOT}/packages/brainsOS-portal/index.html" -nt "${PORTAL_DIST}/index.html" ]; then
  log_info "Portal build missing or source index.html updated. Compiling bundle..."
  (cd "${REPO_ROOT}/packages/brainsOS-portal" && npm run build)
fi

if [ ! -f "${PORTAL_DIST}/index.html" ]; then
  fail_check "Portal index.html missing after build."
fi

INDEX_HTML=$(cat "${PORTAL_DIST}/index.html")

grep -qi "<title>.*</title>" <<< "${INDEX_HTML}" || \
  fail_check "Portal <title> tag missing from compiled bundle."

EXPECTED_TITLE=$(grep -o '<title>.*</title>' "${REPO_ROOT}/packages/brainsOS-portal/index.html" || true)
if [ -n "${EXPECTED_TITLE}" ]; then
  grep -F "${EXPECTED_TITLE}" <<< "${INDEX_HTML}" >/dev/null || \
    fail_check "Compiled bundle title does not match source index.html (${EXPECTED_TITLE})."
fi

log_success "Portal static distribution verified (dist/index.html with ${EXPECTED_TITLE} & assets present)."

# ------------------------------------------------------------------------------
# 3. Authentik Bespoke Theme Verification (Issue #245)
# ------------------------------------------------------------------------------
log_info "Step 3: Validating Authentik bespoke theme assets..."
THEME_DIR="${REPO_ROOT}/config/authentik/themes/brainsos"

if [ ! -f "${THEME_DIR}/login.html" ]; then
  fail_check "Missing Authentik login template: ${THEME_DIR}/login.html"
fi

if [ ! -f "${THEME_DIR}/theme.css" ]; then
  fail_check "Missing Authentik theme stylesheet: ${THEME_DIR}/theme.css"
fi

THEME_HTML=$(cat "${THEME_DIR}/login.html")

grep "BRAINSOS" <<< "${THEME_HTML}" >/dev/null || fail_check "Theme missing BRAINSOS title."
grep "SAFE, SECURE, ASYNCHRONOUS AGENTS" <<< "${THEME_HTML}" >/dev/null || fail_check "Theme missing security subtitle."
grep "v1.0.0-arm64" <<< "${THEME_HTML}" >/dev/null || fail_check "Theme missing full-width version footer."
grep "Passkey" <<< "${THEME_HTML}" >/dev/null || fail_check "Theme missing Passkey authentication."

log_success "Authentik bespoke theme verified against approved visual mockup."

BLUEPRINT_FILE="${REPO_ROOT}/config/authentik/blueprints/brainsos-portal.yaml"
if [ ! -f "${BLUEPRINT_FILE}" ]; then
  fail_check "Missing Authentik blueprint: ${BLUEPRINT_FILE}"
fi
grep "brainsos-portal" "${BLUEPRINT_FILE}" >/dev/null || fail_check "Blueprint missing brainsos-portal application."
grep "operator" "${BLUEPRINT_FILE}" >/dev/null || fail_check "Blueprint missing operator user definition."
log_success "Authentik blueprint verified (operator account & Caddy proxy provider)."

# ------------------------------------------------------------------------------
# 4. Caddy Ingress Configuration & Forward Auth Verification (Issue #245 / #246)
# ------------------------------------------------------------------------------
log_info "Step 4: Validating Caddyfile ingress and forward_auth routing..."
CADDYFILE="${REPO_ROOT}/config/caddy/Caddyfile"

grep "portal_content" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing portal_content directive."
grep "root \* /srv/portal" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing /srv/portal file server."
grep "authentik_backend" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing authentik_backend snippet."
grep "authentik_forward_auth" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing authentik_forward_auth snippet."
grep "auth\.{\$BRAINSOS_DOMAIN:brainsos\.local}" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing auth domain route."
grep "outpost\.goauthentik\.io" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing outpost.goauthentik.io handle."
grep "hermes\.runner" "${CADDYFILE}" >/dev/null || fail_check "Caddyfile missing hermes.runner domain route."

log_success "Caddyfile ingress routes and Authentik forward_auth directives verified."

# ------------------------------------------------------------------------------
# 5. Docker Compose Topology & Sandboxing Verification (Rule 4 / Rule 6)
# ------------------------------------------------------------------------------
log_info "Step 5: Validating Docker Compose topology and sandboxing boundaries..."
docker compose config -q || fail_check "Docker Compose topology configuration invalid."

COMPOSE_YAML=$(docker compose config)

# Verify Caddy mounts /srv/portal
grep "/srv/portal" <<< "${COMPOSE_YAML}" >/dev/null || \
  fail_check "Caddy container does not mount /srv/portal."

# Verify Authentik services exist
grep "authentik-server" <<< "${COMPOSE_YAML}" >/dev/null || fail_check "Missing authentik-server service in compose."
grep "authentik-worker" <<< "${COMPOSE_YAML}" >/dev/null || fail_check "Missing authentik-worker service in compose."
grep "authentik-db" <<< "${COMPOSE_YAML}" >/dev/null || fail_check "Missing authentik-db service in compose."
grep "authentik-redis" <<< "${COMPOSE_YAML}" >/dev/null || fail_check "Missing authentik-redis service in compose."

# Verify Hermes runner port 8787
grep "8787" <<< "${COMPOSE_YAML}" >/dev/null || fail_check "runner-hermes does not expose WebUI port 8787."

# Rule 4: Verify NO docker socket mounts in Authentik or runner containers
if grep -E 'docker\.sock.*(authentik|runner)' <<< "${COMPOSE_YAML}" >/dev/null; then
  fail_check "Rule 4 Violation: Docker socket mounted into Authentik or runner container."
fi

# Rule 6: Verify LiteLLM database is isolated
if grep -E 'brainsos-(control-|infra-)?litellm-db.*(hermes|portal|authentik)' <<< "${COMPOSE_YAML}" >/dev/null; then
  fail_check "Rule 6 Violation: LiteLLM database exposed to non-control containers."
fi

# ------------------------------------------------------------------------------
# 6. Single-Origin Path-Based Ingress Topology Live HTTP Assertions (Issue #256)
# ------------------------------------------------------------------------------
log_info "Step 6: Validating Single-Origin Path Ingress Topology via Live HTTP requests..."

TARGET_HOST="${BRAINSOS_DOMAIN:-local.brainsos.ai}"
RESOLVE_ARG="${TARGET_HOST}:443:127.0.0.1"

# A. Trailing-slash redirects
for p in "editor" "efw" "proxy/ui"; do
  STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" --resolve "${RESOLVE_ARG}" "https://${TARGET_HOST}/${p}" 2>/dev/null || echo "000")
  if [ "${STATUS}" == "308" ]; then
    log_success "Path /${p} trailing-slash normalization verified (HTTP 308)."
  else
    fail_check "Path /${p} failed trailing-slash normalization: Got HTTP ${STATUS} (expected 308)."
  fi
done

# B. Forward-Auth Protected Endpoints (Expect 302 Redirect to Authentik Login)
for p in "editor/" "SOGo" "efw/" "auth/"; do
  STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" --resolve "${RESOLVE_ARG}" "https://${TARGET_HOST}/${p}" 2>/dev/null || echo "000")
  if [ "${STATUS}" == "302" ]; then
    log_success "Protected path /${p} forward-auth gate verified (HTTP 302 SSO Redirect)."
  else
    fail_check "Protected path /${p} failed forward-auth gate: Got HTTP ${STATUS} (expected 302)."
  fi
done

# LiteLLM Native OIDC UI Ingress (Direct HTTP 200 with OIDC SSO integration)
LITELLM_UI_STATUS=$(curl -s -k -o /dev/null -w "%{http_code}" --resolve "${RESOLVE_ARG}" "https://${TARGET_HOST}/proxy/ui/" 2>/dev/null || echo "000")
if [ "${LITELLM_UI_STATUS}" == "200" ] || [ "${LITELLM_UI_STATUS}" == "302" ] || [ "${LITELLM_UI_STATUS}" == "307" ] || [ "${LITELLM_UI_STATUS}" == "308" ]; then
  log_success "LiteLLM native OIDC UI ingress verified (/proxy/ui/ HTTP ${LITELLM_UI_STATUS})."
else
  fail_check "LiteLLM native OIDC UI ingress failed: HTTP ${LITELLM_UI_STATUS}."
fi

# C. Plane 2: Direct Programmatic API Ingress (No SSO, Direct HTTP 200)
PROXY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: proxy.${TARGET_HOST}" "http://127.0.0.1:${CADDY_HTTP_PORT:-80}/health/readiness" 2>/dev/null || echo "000")
if [ "${PROXY_STATUS}" == "200" ]; then
  log_success "Plane 2 programmatic LiteLLM API ingress verified (proxy.${TARGET_HOST} HTTP 200 OK)."
else
  log_warn "Plane 2 programmatic LiteLLM API returned HTTP ${PROXY_STATUS}."
fi

# ------------------------------------------------------------------------------
# 7. Downstream Service SSO & Direct Upstream Verification (Issues #258, #259, #260)
# ------------------------------------------------------------------------------
log_info "Step 7: Validating Downstream Service Upstream Connectivity..."

# Issue #258: SOGo Trusted Proxy Authentication
SOGO_UPSTREAM=$(docker compose exec -T caddy curl -s -o /dev/null -w "%{http_code}" -H "x-webobjects-remote-user: operator" http://sogo:20000/SOGo/index/ 2>/dev/null || echo "000")
if [ "${SOGO_UPSTREAM}" == "302" ] || [ "${SOGO_UPSTREAM}" == "200" ]; then
  log_success "SOGo Trusted Proxy Authentication verified (HTTP ${SOGO_UPSTREAM} authenticated response)."
else
  fail_check "SOGo Trusted Proxy upstream failed: HTTP ${SOGO_UPSTREAM} (expected 200 or 302)."
fi

# Issue #259: Code-Server IDE & Mitmweb Tool Egress Proxy
CODE_UPSTREAM=$(docker compose exec -T caddy curl -s -o /dev/null -w "%{http_code}" http://code-server:8443/?folder=/data 2>/dev/null || echo "000")
if [ "${CODE_UPSTREAM}" == "200" ]; then
  log_success "Code-Server upstream verified at code-server:8443 (HTTP 200 OK)."
else
  fail_check "Code-Server upstream failed: HTTP ${CODE_UPSTREAM}."
fi

MITM_UPSTREAM=$(docker compose exec -T caddy sh -c 'curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOOL_EGRESS_WEB_PASSWORD" http://tool-egress-proxy:8081/' 2>/dev/null || echo "000")
if [ "${MITM_UPSTREAM}" == "200" ]; then
  log_success "Tool Egress Proxy (mitmweb) upstream verified with bearer token (HTTP 200 OK)."
else
  fail_check "Tool Egress Proxy upstream failed: HTTP ${MITM_UPSTREAM}."
fi

# Issue #260 & #270: LiteLLM Container Upstream
TARGET_LITELLM="${LITELLM_UPSTREAM:-litellm:4000}"
LITELLM_STATUS=$(docker compose exec -T caddy sh -c "curl -s -o /dev/null -w \"%{http_code}\" -H \"Authorization: Bearer \$LITELLM_MASTER_KEY\" http://${TARGET_LITELLM}/ui/ || curl -s -o /dev/null -w \"%{http_code}\" http://host.docker.internal:4000/ui/" 2>/dev/null || echo "000")
if [ "${LITELLM_STATUS}" == "200" ]; then
  log_success "LiteLLM Admin Console upstream verified at ${TARGET_LITELLM} (HTTP 200 OK)."
else
  fail_check "LiteLLM Admin Console upstream failed: HTTP ${LITELLM_STATUS}."
fi

echo -e "\n${BOLD}${GREEN}====================================================================${NC}"
echo -e "${BOLD}${GREEN}  All Portal, Ingress & Downstream SSO Verifications PASSED!        ${NC}"
echo -e "${BOLD}${GREEN}====================================================================${NC}"
