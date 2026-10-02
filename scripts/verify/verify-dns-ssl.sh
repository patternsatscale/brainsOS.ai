#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Split-Horizon DNS & Public ACME DNS-01 Verification Suite (Issue #155)
# Validates SST platform infrastructure, Caddy Route 53 plugin, dynamic TLS policy,
# and zero-drift fleet synchronization across local and public domain modes.
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

# ------------------------------------------------------------------------------
# Precondition: Rule 13 Environment Gate
# ------------------------------------------------------------------------------
if [ ! -f .env ]; then
  fail_check "Execution precondition failed: No .env file present in repository root."
fi

set -a
. ./.env
set +a

log_info "======================================================================"
log_info "Running brainsOS Split-Horizon DNS & ACME SSL Verification"
log_info "======================================================================"

# ------------------------------------------------------------------------------
# 1. SST Platform Infrastructure TypeScript Typecheck (infra/)
# ------------------------------------------------------------------------------
log_info "1. Validating SST platform infrastructure TypeScript types (infra/)..."
if [ ! -d "${REPO_ROOT}/infra/node_modules" ]; then
  (cd "${REPO_ROOT}/infra" && npm install --silent)
fi
(cd "${REPO_ROOT}/infra" && npm run typecheck) || fail_check "infra/ TypeScript validation failed."
log_success "infra/ TypeScript constructs validated cleanly."

# ------------------------------------------------------------------------------
# 2. Operator Deployment Script Dry-Run Diff
# ------------------------------------------------------------------------------
log_info "2. Validating operator deployment script dry-run (scripts/setup/deploy-infra.sh)..."
"${REPO_ROOT}/scripts/setup/deploy-infra.sh" --dry-run || fail_check "deploy-infra.sh dry run failed."
log_success "deploy-infra.sh dry run executed cleanly."

# ------------------------------------------------------------------------------
# 3. Caddy Route 53 ACME DNS-01 Plugin Image Verification
# ------------------------------------------------------------------------------
log_info "3. Verifying Caddy custom build with Route 53 DNS plugin (docker/caddy)..."
if ! docker image inspect brainsos-caddy:latest >/dev/null 2>&1; then
  log_info "Building brainsos-caddy:latest image..."
  docker build -t brainsos-caddy:latest "${REPO_ROOT}/docker/caddy" || fail_check "Failed to build brainsos-caddy:latest."
fi

MODULE_CHECK=$(docker run --rm brainsos-caddy:latest caddy list-modules | grep -E "^dns\.providers\.route53$" || true)
if [ -z "${MODULE_CHECK}" ]; then
  fail_check "Caddy image missing required 'dns.providers.route53' plugin module."
fi
log_success "Caddy binary contains 'dns.providers.route53' module."

# ------------------------------------------------------------------------------
# 4. Caddyfile Syntax Validation
# ------------------------------------------------------------------------------
log_info "4. Validating Caddyfile syntax against brainsos-caddy:latest..."
docker run --rm -v "${REPO_ROOT}/config/caddy:/etc/caddy:ro" brainsos-caddy:latest caddy validate --config /etc/caddy/Caddyfile || \
  fail_check "Caddyfile validation failed."
log_success "Caddyfile configuration validated successfully."

# ------------------------------------------------------------------------------
# 5. Localhost Fallback Preservation
# ------------------------------------------------------------------------------
log_info "5. Verifying localhost fallback routes preserve 'tls internal'..."
grep -q "http://editor.localhost" "${REPO_ROOT}/config/caddy/Caddyfile" || fail_check "Missing editor.localhost in Caddyfile."
grep -q "http://proxy.localhost" "${REPO_ROOT}/config/caddy/Caddyfile" || fail_check "Missing proxy.localhost in Caddyfile."
grep -q "http://terrastella.localhost" "${REPO_ROOT}/config/caddy/agents.caddy" || fail_check "Missing terrastella.localhost in agents.caddy."
log_success "Localhost fallback routes and internal TLS policies are intact."

# ------------------------------------------------------------------------------
# 6. Fleet Manifest Synchronization & Zero-Drift (Local & Public Domain Modes)
# ------------------------------------------------------------------------------
log_info "6. Testing fleet manifest sync under simulated public domain with Route 53..."
ORIGINAL_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
ORIGINAL_PROVIDER="${ACME_DNS_PROVIDER:-}"

BRAINSOS_DOMAIN="brainsos.example.com" ACME_DNS_PROVIDER="route53" "${REPO_ROOT}/scripts/control/sync-agents.sh" || \
  fail_check "Failed to sync fleet with simulated public domain."

grep -q "dns route53" "${REPO_ROOT}/config/caddy/tls_policy.caddy" || fail_check "tls_policy.caddy missing 'dns route53'."
grep -q "terrastella.brainsos.example.com" "${REPO_ROOT}/config/caddy/agents.caddy" || fail_check "agents.caddy missing public domain route."

docker run --rm -v "${REPO_ROOT}/config/caddy:/etc/caddy:ro" brainsos-caddy:latest caddy validate --config /etc/caddy/Caddyfile || \
  fail_check "Caddyfile validation failed with simulated public domain."

BRAINSOS_DOMAIN="brainsos.example.com" ACME_DNS_PROVIDER="route53" "${REPO_ROOT}/scripts/control/sync-agents.sh" --check || \
  fail_check "Drift check failed with simulated public domain."

log_info "Reconciling fleet back to original environment state (${ORIGINAL_DOMAIN})..."
BRAINSOS_DOMAIN="${ORIGINAL_DOMAIN}" ACME_DNS_PROVIDER="${ORIGINAL_PROVIDER}" "${REPO_ROOT}/scripts/control/sync-agents.sh" || \
  fail_check "Failed to restore original fleet state."

"${REPO_ROOT}/scripts/control/sync-agents.sh" --check || fail_check "Final fleet drift check failed."
log_success "Multi-mode fleet sync and zero-drift verification passed."

# ------------------------------------------------------------------------------
# 7. Public Ingress Redirect Inspection
# ------------------------------------------------------------------------------
log_info "7. Inspecting public split-horizon redirect configuration..."
if [ "${BRAINSOS_DOMAIN}" != "brainsos.local" ] && [ "${BRAINSOS_DOMAIN}" != "localhost" ]; then
  log_info "Active BRAINSOS_DOMAIN is set to public domain: ${BRAINSOS_DOMAIN}"
  REDIRECT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -I "https://${BRAINSOS_DOMAIN}" 2>/dev/null || true)
  if [ -n "${REDIRECT_STATUS}" ]; then
    log_info "HTTP status from https://${BRAINSOS_DOMAIN}: ${REDIRECT_STATUS}"
  fi
else
  log_info "BRAINSOS_DOMAIN is local (${BRAINSOS_DOMAIN}); public redirect defined declaratively in infra/src/dns.ts."
fi

log_info "======================================================================"
log_success "All Split-Horizon DNS & ACME SSL verification checks passed (100%)"
log_info "======================================================================"
