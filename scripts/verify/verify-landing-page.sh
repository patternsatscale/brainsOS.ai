#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Landing Page & Ingress Routing Verification Suite (Ticket #138)
# Validates the L1–L7 hardware stack model, side-by-side agent fleet cards,
# zero legacy debt, and direct ingress reverse-proxy container routing.
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

log_info "======================================================================"
log_info "Running Project Titan Landing Page & Ingress Routing Verification"
log_info "======================================================================"

# ------------------------------------------------------------------------------
# 1. Fleet Manifest Synchronization & Zero Drift Check
# ------------------------------------------------------------------------------
if [ -z "${MANIFEST_FILE:-}" ]; then
  if [ -f "${REPO_ROOT}/config/agents.local.yaml" ]; then
    MANIFEST_FILE="${REPO_ROOT}/config/agents.local.yaml"
  elif [ -f "${REPO_ROOT}/config/agents.override.yaml" ]; then
    MANIFEST_FILE="${REPO_ROOT}/config/agents.override.yaml"
  else
    MANIFEST_FILE="${REPO_ROOT}/config/agents.yaml"
  fi
fi
MANIFEST_FILE="${MANIFEST_FILE}" "${REPO_ROOT}/scripts/control/sync-agents.sh" --check || \
  fail_check "Fleet manifest drift detected. Run sync-agents.sh."
docker compose config -q || fail_check "Docker Compose topology configuration invalid."
log_success "Fleet manifest and compose topology are 100% in sync with zero drift."

# ------------------------------------------------------------------------------
# 2. Caddy Configuration Syntax Validation
# ------------------------------------------------------------------------------
CADDY_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^titan-(net-)?caddy$' | head -n 1 || echo 'titan-net-caddy')"
docker exec "${CADDY_CONTAINER}" caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 || \
  fail_check "Caddyfile syntax validation failed."
log_success "Caddyfile configuration syntax validated successfully."

# ------------------------------------------------------------------------------
# 3. Landing Page Content & Architecture Stack Verification
# ------------------------------------------------------------------------------
log_info "Step 3: Fetching titan.local portal and asserting L1–L7 architecture stack..."
LANDING_HTML=$(curl -s --retry 5 --retry-connrefused --retry-delay 1 -H "Host: titan.local" http://127.0.0.1:80)

if [ -z "${LANDING_HTML}" ]; then
  fail_check "Failed to fetch titan.local landing page (empty response)."
fi

# Assert Page Title
if ! grep "<title>ASUS Ascent GX10 - Project Titan Control Center</title>" <<< "${LANDING_HTML}" >/dev/null; then
  fail_check "Landing page title missing or incorrect."
fi
log_success "Verified page title: ASUS Ascent GX10 - Project Titan Control Center"

# Assert L1–L7 Stack Layers
grep "Levels 6 &amp; 7" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Levels 6 & 7 section header."
grep "Level 5" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Level 5 section header."
grep "Level 4" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Level 4 section header."
grep "Levels 2 &amp; 3" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Levels 2 & 3 section header."
grep "Level 1" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Level 1 section header."
grep "Cross-Cutting" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Cross-Cutting section header."
log_success "Verified all architectural tiers (L1–L7 + Cross-Cutting) present in visual hierarchy."

# Assert Side-by-Side Agent Cards
grep "Terrastella" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Terrastella card in landing page."
grep "Cindy Pawford" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Cindy Pawford card in landing page."
grep "Football Dan" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing Football Dan card in landing page."
log_success "Verified side-by-side agent cards: Terrastella, Cindy Pawford, and Football Dan."

# Assert Zero Legacy Debt
if grep -i "hermes.localhost" <<< "${LANDING_HTML}" >/dev/null; then
  fail_check "Found legacy hermes.localhost reference in landing page."
fi
if grep -i "hermes.titan.local" <<< "${LANDING_HTML}" >/dev/null; then
  fail_check "Found legacy hermes.titan.local reference in landing page."
fi
log_success "Verified zero legacy hermes URLs in landing page (clean zero-debt architecture)."

# Assert /etc/hosts Snippet
grep "terrastella.titan.local" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing terrastella in /etc/hosts snippet."
grep "cindypawford.titan.local" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing cindypawford in /etc/hosts snippet."
grep "football-dan.titan.local" <<< "${LANDING_HTML}" >/dev/null || fail_check "Missing football-dan in /etc/hosts snippet."
log_success "Verified /etc/hosts snippet contains all active multi-agent fleet subdomains."

# ------------------------------------------------------------------------------
# 4. Ingress Reverse-Proxy Container Routing Assertions
# ------------------------------------------------------------------------------
log_info "Step 4: Testing direct ingress routing to agent containers..."

# 4a. Terrastella (Primary Operations Agent)
TERRA_RESP=$(curl -s -I -H "Host: terrastella.titan.local" http://127.0.0.1:80)
grep -i "Server: uvicorn" <<< "${TERRA_RESP}" >/dev/null || fail_check "terrastella.titan.local did not route to uvicorn container."
grep -i "Location: /login" <<< "${TERRA_RESP}" >/dev/null || fail_check "terrastella.titan.local unexpected response."
log_success "Routing: terrastella.titan.local -> titan-agent-terrastella:9119 (uvicorn) [PASS]"

TERRA_LOCAL_RESP=$(curl -s -I -H "Host: terrastella.localhost" http://127.0.0.1:80)
grep -i "Server: uvicorn" <<< "${TERRA_LOCAL_RESP}" >/dev/null || fail_check "terrastella.localhost did not route to uvicorn container."
log_success "Routing: terrastella.localhost -> titan-agent-terrastella:9119 (uvicorn) [PASS]"

# 4b. Cindy Pawford (Creative Director)
CINDY_RESP=$(curl -s -I -H "Host: cindypawford.titan.local" http://127.0.0.1:80)
grep -i "Server: uvicorn" <<< "${CINDY_RESP}" >/dev/null || fail_check "cindypawford.titan.local did not route to uvicorn container."
log_success "Routing: cindypawford.titan.local -> titan-agent-cindy-pawford:9121 (uvicorn) [PASS]"

# 4c. Football Dan (Sports Analytics)
DAN_RESP=$(curl -s -I -H "Host: football-dan.titan.local" http://127.0.0.1:80)
grep -i "Server: uvicorn" <<< "${DAN_RESP}" >/dev/null || fail_check "football-dan.titan.local did not route to uvicorn container."
log_success "Routing: football-dan.titan.local -> titan-agent-football-dan:9120 (uvicorn) [PASS]"

# 4d. Titan Operator IDE (Layer 7 / Layer 5 Operator Console)
EDITOR_RESP=$(curl -s -I -H "Host: editor.titan.local" http://127.0.0.1:80)
grep -E "401 Unauthorized|200 OK|302 Found" <<< "${EDITOR_RESP}" >/dev/null || fail_check "editor.titan.local did not route to Operator IDE (expected 401/200/302)."
log_success "Routing: editor.titan.local -> titan-app-code-server:8443 (Basic Auth Gate) [PASS]"

# 4e. LiteLLM Gateway (Layer 4)
PROXY_RESP=$(curl -s -I -H "Host: proxy.titan.local" http://127.0.0.1:80/ui)
grep -i "Server: uvicorn" <<< "${PROXY_RESP}" >/dev/null || fail_check "proxy.titan.local did not route to LiteLLM container."
log_success "Routing: proxy.titan.local/ui -> LiteLLM Control Plane:4000 [PASS]"

log_info "======================================================================"
log_success "All Project Titan Landing Page & Ingress Routing verifications passed!"
log_info "======================================================================"
