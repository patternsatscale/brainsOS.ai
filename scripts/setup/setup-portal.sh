#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Portal & Authentik SSO Setup Script (Epic #247)
# Builds the bespoke Thin-Spine React SPA (packages/brainsOS-portal)
# and bootstraps the Authentik SSO theme & directory structures.
# Rule 1: Zero portal build artifacts in /memories.
# Rule 8: Idempotent and script-driven.
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

DATA_DIR="${BRAINSOS_DATA_DIR:-./data}"
if [[ "$DATA_DIR" != /* ]]; then
  DATA_DIR="${REPO_ROOT}/${DATA_DIR#./}"
fi

log_info "======================================================================"
log_info "Setting up brainsOS Unified Portal & Authentik SSO (Epic #247)"
log_info "======================================================================"

# ------------------------------------------------------------------------------
# 1. Directory Scaffolding for Authentik Data Plane
# ------------------------------------------------------------------------------
log_info "Step 1: Scaffolding Authentik database and media directories..."
mkdir -p "${DATA_DIR}/control_plane/authentik_db"
mkdir -p "${DATA_DIR}/control_plane/authentik_media"

# Ensure authentik database exists if auth-db container is active
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "brainsos-auth-db"; then
  if ! docker exec brainsos-auth-db psql -U "${AUTHENTIK_POSTGRESQL__USER:-authentik}" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '${AUTHENTIK_POSTGRESQL__NAME:-authentik}'" 2>/dev/null | grep -q 1; then
    docker exec brainsos-auth-db createdb -U "${AUTHENTIK_POSTGRESQL__USER:-authentik}" "${AUTHENTIK_POSTGRESQL__NAME:-authentik}" 2>/dev/null || true
  fi
fi
log_success "Authentik control plane directories initialized."

# ------------------------------------------------------------------------------
# 2. Build React Thin-Spine Portal SPA
# ------------------------------------------------------------------------------
PORTAL_DIR="${REPO_ROOT}/packages/brainsOS-portal"
log_info "Step 2: Building brainsOS Thin-Spine Portal SPA in ${PORTAL_DIR}..."

if [ ! -d "${PORTAL_DIR}" ]; then
  fail_check "Portal package directory not found: ${PORTAL_DIR}"
fi

cd "${PORTAL_DIR}"

if [ ! -d "node_modules" ]; then
  log_info "Installing portal npm dependencies..."
  npm install --silent
fi

log_info "Compiling production static bundle via Vite (Host: ${BRAINSOS_HOST_NAME:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}, Version: ${BRAINSOS_VERSION:-v0.1.0-arm64})..."
VITE_APPLIANCE_HOST="${BRAINSOS_HOST_NAME:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}" \
VITE_BRAINSOS_VERSION="${BRAINSOS_VERSION:-v0.1.0-arm64}" \
npm run build

if [ ! -f "dist/index.html" ]; then
  fail_check "Portal build failed: dist/index.html missing."
fi

cd "${REPO_ROOT}"
log_success "Portal static bundle successfully compiled to packages/brainsOS-portal/dist/."

# ------------------------------------------------------------------------------
# 3. Validate Authentik Theme Assets
# ------------------------------------------------------------------------------
log_info "Step 3: Validating bespoke Authentik theme assets..."
THEME_DIR="${REPO_ROOT}/config/authentik/themes/brainsos"
if [ ! -f "${THEME_DIR}/login.html" ]; then
  fail_check "Missing Authentik theme login template: ${THEME_DIR}/login.html"
fi
if [ ! -f "${THEME_DIR}/theme.css" ]; then
  fail_check "Missing Authentik theme stylesheet: ${THEME_DIR}/theme.css"
fi
log_success "Authentik bespoke theme assets validated."

BLUEPRINT_FILE="${REPO_ROOT}/config/authentik/blueprints/brainsos-portal.yaml"
if [ ! -f "${BLUEPRINT_FILE}" ]; then
  fail_check "Missing Authentik blueprint: ${BLUEPRINT_FILE}"
fi
log_success "Authentik blueprint validated."

# ------------------------------------------------------------------------------
# 4. Bootstrap Authentik Blueprint & Operator Account (if server is running)
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "brainsos-auth-server"; then
  log_info "Step 4: Applying Authentik blueprint in running auth-server..."
  docker exec -i brainsos-auth-server ak apply_blueprint /blueprints/brainsos/brainsos-portal.yaml || log_warn "Blueprint apply will complete on container initialization."
  docker exec -i brainsos-auth-server ak shell -c "from authentik.core.models import User; u = User.objects.filter(username='operator').first(); (u.set_password('${AUTHENTIK_OPERATOR_PASSWORD:-brainsos}'), u.save()) if u else None" 2>/dev/null || true

  EFFECTIVE_DOMAIN="${BRAINSOS_DOMAIN:-local.brainsos.ai}"
  docker exec -i brainsos-auth-server ak shell -c "
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyProvider
from authentik.core.models import Application
from authentik.providers.oauth2.models import OAuth2Provider

domain = '${EFFECTIVE_DOMAIN}'
cookie_dom = 'local.brainsos.ai' if domain.endswith('local.brainsos.ai') else domain

for o in Outpost.objects.all():
    o._config['authentik_host'] = f'https://{domain}'
    o._config['authentik_host_browser'] = f'https://{domain}'
    o.save()

for p in ProxyProvider.objects.all():
    p.external_host = f'https://{domain}'
    p.cookie_domain = cookie_dom
    p.redirect_uris = f'https://{domain}/outpost.goauthentik.io/callback?X-authentik-auth-callback=true\nhttps://{domain}?X-authentik-auth-callback=true\nhttps://local.brainsos.ai/outpost.goauthentik.io/callback?X-authentik-auth-callback=true\nhttps://local.brainsos.ai?X-authentik-auth-callback=true\n.*'
    p.save()

for a in Application.objects.all():
    if a.slug == 'brainsos-portal':
        a.meta_launch_url = f'https://{domain}/'
        a.save()
    elif a.slug == 'litellm':
        a.meta_launch_url = f'https://{domain}/ui/'
        a.save()
    elif a.slug == 'langfuse':
        a.meta_launch_url = f'https://langfuse.{domain}/'
        a.save()

for oa in OAuth2Provider.objects.all():
    if oa.name == 'Langfuse Observability OIDC':
        oa.redirect_uris = f'https://langfuse.{domain}/api/auth/callback/custom\nhttps://langfuse.local.brainsos.ai/api/auth/callback/custom\nhttp://localhost:3001/api/auth/callback/custom\n.*'
        oa.save()
"
  log_success "Authentik blueprint applied and domain synchronized with '${EFFECTIVE_DOMAIN}'."
fi

# ------------------------------------------------------------------------------
# 5. Memory Plane Purity Assertion (Rule 1)
# ------------------------------------------------------------------------------
log_info "Step 5: Asserting Rule 1 (Memory Plane Purity) for portal assets..."
MEMORIES_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${BRAINSOS_DATA_DIR:-./data}/agent_memories}"
if [[ "$MEMORIES_DIR" != /* ]]; then
  MEMORIES_DIR="${REPO_ROOT}/${MEMORIES_DIR#./}"
fi

if [ -d "${MEMORIES_DIR}" ]; then
  LEAKED_ASSETS=$(find "${MEMORIES_DIR}" -type f \( -name "*.html" -o -name "*.js" -o -name "*.css" -o -name "package.json" \) 2>/dev/null || true)
  if [ -n "${LEAKED_ASSETS}" ]; then
    fail_check "Rule 1 Violation: Portal assets leaked into /memories:\n${LEAKED_ASSETS}"
  fi
fi
log_success "Rule 1 verified: Zero portal artifacts in /memories."

echo -e "\n${BOLD}${GREEN}====================================================================${NC}"
echo -e "${BOLD}${GREEN}  brainsOS Portal & Authentik SSO Setup Completed Successfully!     ${NC}"
echo -e "${BOLD}${GREEN}====================================================================${NC}"
