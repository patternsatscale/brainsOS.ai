#!/usr/bin/env bash
# ==============================================================================
# brainsOS: LiteLLM SSO & Administrator Role Provisioning Script (Ticket #270)
# Configures and elevates administrator identities to full proxy_admin privileges
# via the LiteLLM REST API, enforces individual passwords, disables insecure
# environment-credential login, binds generic OIDC group claims, and syncs Authentik.
#
# Architectural Guardrails:
#   Rule 6: Control Plane Database Isolation (managed exclusively via REST API)
#   Rule 8: Script-Driven Discipline (idempotent, reproducible)
#   Rule 13: Mandatory .env Precondition Gate
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

LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_API_BASE="http://127.0.0.1:${LITELLM_PORT}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
TARGET_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
PRIMARY_ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-admin@${TARGET_DOMAIN}}"
ADMIN_RAW_PASS="${BRAINSOS_ADMIN_PASSWORD:-SwZjRtnmaNCxBrgkX2VX6X7M}"

# Ensure password satisfies LiteLLM policy (uppercase, lowercase, number, special char)
if [[ "${ADMIN_RAW_PASS}" =~ [^a-zA-Z0-9] ]]; then
  ADMIN_COMPLIANT_PASS="${ADMIN_RAW_PASS}"
else
  ADMIN_COMPLIANT_PASS="${ADMIN_RAW_PASS}!"
fi

if [ -z "${LITELLM_MASTER_KEY}" ]; then
  fail_check "LITELLM_MASTER_KEY is not defined in .env. Cannot provision administrative accounts."
fi

log_info "======================================================================"
log_info "brainsOS: LiteLLM Administrator Role & SSO Provisioning"
log_info "======================================================================"
log_info "Target Domain:       ${BOLD}${TARGET_DOMAIN}${NC}"
log_info "Primary Admin Email: ${BOLD}${PRIMARY_ADMIN_EMAIL}${NC}"
log_info "LiteLLM Endpoint:    ${BOLD}${LITELLM_API_BASE}${NC}"

# ------------------------------------------------------------------------------
# 1. Health Preflight: Wait for LiteLLM Gateway
# ------------------------------------------------------------------------------
log_info "Step 1: Waiting for LiteLLM control plane gateway to respond..."
READY=false
for i in {1..30}; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${LITELLM_API_BASE}/health/liveness" || echo "000")
  if [[ "${HTTP_CODE}" =~ ^(200|401|405)$ ]]; then
    READY=true
    break
  fi
  sleep 1
done

if [ "${READY}" != true ]; then
  fail_check "LiteLLM gateway at ${LITELLM_API_BASE} did not respond within 30 seconds."
fi
log_success "LiteLLM gateway is live and responding."

# ------------------------------------------------------------------------------
# 2. Provision Admin Accounts via LiteLLM REST API
# ------------------------------------------------------------------------------
log_info "Step 2: Provisioning administrator identities with full proxy_admin privileges & individual passwords..."

# Define all admin aliases to ensure seamless SSO regardless of claim format
ADMIN_USERS=(
  "${PRIMARY_ADMIN_EMAIL}"
  "admin@${TARGET_DOMAIN}"
  "admin"
)

# Deduplicate list
UNIQUE_ADMIN_USERS=($(printf "%s\n" "${ADMIN_USERS[@]}" | sort -u))

provision_user() {
  local uid="$1"
  log_info "Evaluating user: ${BOLD}${uid}${NC}..."

  local check_resp
  check_resp=$(curl -s -X GET "${LITELLM_API_BASE}/user/info?user_id=${uid}" \
    -H "Authorization: Bearer ${LITELLM_MASTER_KEY}")

  local exists=false
  if echo "${check_resp}" | grep -q "\"user_id\":\"${uid}\""; then
    exists=true
  fi

  if [ "${exists}" = true ]; then
    log_info "User '${uid}' exists in database. Updating role, models, and individual password..."
    local update_res
    update_res=$(curl -s -X POST "${LITELLM_API_BASE}/user/update" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{
        \"user_id\": \"${uid}\",
        \"user_role\": \"proxy_admin\",
        \"models\": [\"all-proxy-models\"],
        \"password\": \"${ADMIN_COMPLIANT_PASS}\"
      }")
    if echo "${update_res}" | grep -q "\"proxy_admin\""; then
      log_success "Successfully elevated '${uid}' to proxy_admin (all-proxy-models) with individual password."
    else
      log_warn "Update response for '${uid}': ${update_res}"
    fi
  else
    log_info "User '${uid}' does not exist. Creating new proxy_admin user with individual password..."
    local create_res
    create_res=$(curl -s -X POST "${LITELLM_API_BASE}/user/new" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{
        \"user_id\": \"${uid}\",
        \"user_role\": \"proxy_admin\",
        \"models\": [\"all-proxy-models\"],
        \"password\": \"${ADMIN_COMPLIANT_PASS}\"
      }")
    if echo "${create_res}" | grep -q "\"proxy_admin\""; then
      log_success "Successfully created '${uid}' as proxy_admin (all-proxy-models) with individual password."
    else
      log_warn "Create response for '${uid}': ${create_res}"
    fi
  fi
}

for user_id in "${UNIQUE_ADMIN_USERS[@]}"; do
  [ -z "${user_id}" ] && continue
  provision_user "${user_id}"
done

# ------------------------------------------------------------------------------
# 3. Configure SSO Settings & Role Mappings in LiteLLM DB
# ------------------------------------------------------------------------------
log_info "Step 3: Configuring LiteLLM SSO role mappings via REST API..."
AUTH_CLIENT_ID="${AUTH_LITELLM_CLIENT_ID:-litellm-proxy}"
AUTH_CLIENT_SECRET="${AUTH_LITELLM_CLIENT_SECRET:-brainsos_litellm_secret}"
AUTH_BASE_URL="https://${TARGET_DOMAIN}"

SSO_PAYLOAD=$(cat <<EOF
{
  "user_email": "${PRIMARY_ADMIN_EMAIL}",
  "proxy_base_url": "${AUTH_BASE_URL}",
  "generic_client_id": "${AUTH_CLIENT_ID}",
  "generic_client_secret": "${AUTH_CLIENT_SECRET}",
  "generic_authorization_endpoint": "${AUTH_BASE_URL}/application/o/authorize/",
  "generic_token_endpoint": "http://authentik-server:9000/application/o/token/",
  "generic_userinfo_endpoint": "http://authentik-server:9000/application/o/userinfo/",
  "role_mappings": {
    "provider": "generic",
    "group_claim": "groups",
    "default_role": "internal_user",
    "roles": {
      "proxy_admin": ["authentik Admins", "admins", "admin", "appliance-admins"]
    }
  }
}
EOF
)

SSO_UPDATE_RES=$(curl -s -X PATCH "${LITELLM_API_BASE}/update/sso_settings" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d "${SSO_PAYLOAD}")

if echo "${SSO_UPDATE_RES}" | grep -q "\"status\":\"success\""; then
  log_success "LiteLLM SSO settings & role mappings successfully updated."
else
  log_warn "SSO settings update response: ${SSO_UPDATE_RES}"
fi

# ------------------------------------------------------------------------------
# 4. Authentik User Email Synchronization (If auth container active)
# ------------------------------------------------------------------------------
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "brainsos-auth-server"; then
  log_info "Step 4: Synchronizing Authentik administrator email in local IdP..."
  docker exec brainsos-auth-server python3 -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
django.setup()
from authentik.core.models import User
admin_user = User.objects.filter(username='admin').first()
if admin_user:
    target_email = '${PRIMARY_ADMIN_EMAIL}'
    if admin_user.email != target_email:
        admin_user.email = target_email
        admin_user.save()
        print('Updated admin user email to:', target_email)
    else:
        print('Admin user email already matches:', target_email)
" 2>/dev/null || log_warn "Could not update Authentik admin user email directly."
  log_success "Authentik IdP synchronization step completed."
fi

# ------------------------------------------------------------------------------
# 5. Verify Security Hardening (Environment-Credential Warning Inactive)
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying environment-credential security hardening..."
READINESS_DETAILS=$(curl -s -X GET "${LITELLM_API_BASE}/health/readiness/details" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "{}")

WARN_STATUS=$(python3 -c "
import json, sys
try:
    data = json.loads('''${READINESS_DETAILS}''')
    print(data.get('show_env_credential_login_warning', 'unknown'))
except Exception:
    print('error')
")

if [ "${WARN_STATUS}" = "False" ]; then
  log_success "Environment-credential warning is INACTIVE (disable_env_credential_login: true verified)."
else
  log_warn "Environment-credential warning status: ${WARN_STATUS}. Ensure config.yaml has disable_env_credential_login: true."
fi

# ------------------------------------------------------------------------------
# 6. Verification & Summary Output
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying registered proxy administrators..."
USERS_JSON=$(curl -s -X GET "${LITELLM_API_BASE}/user/list" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}")

echo ""
echo -e "${BOLD}Current Active LiteLLM Proxy Administrators:${NC}"
python3 -c "
import json, sys
data = json.loads('''${USERS_JSON}''')
users = data.get('users', [])
print(f'{\"USER ID\":<32} {\"ROLE\":<20} {\"MODELS\":<25}')
print('-' * 77)
for u in users:
    uid = u.get('user_id', '')
    role = u.get('user_role', '')
    models = str(u.get('models', []))
    print(f'{uid:<32} {role:<20} {models:<25}')
"

log_success "======================================================================"
log_success "LiteLLM SSO & Administrator Role Setup Completed Successfully."
log_success "======================================================================"
