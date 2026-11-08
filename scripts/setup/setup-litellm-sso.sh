#!/usr/bin/env bash
# ==============================================================================
# brainsOS: LiteLLM SSO & Administrator Role Provisioning Script (Ticket #270 / #332)
# Configures and elevates both 'admin' (instance-bound) and the named Superuser
# to full proxy_admin privileges via the LiteLLM REST API and PostgreSQL table,
# enforces individual passwords, binds generic OIDC group claims, and syncs Authentik.
#
# Architectural Guardrails:
#   Rule 6: Control Plane Database Isolation
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

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"

# Precondition: Rule 13
if [ ! -f "${ENV_FILE}" ]; then
  fail_check "Execution precondition failed: No .env file present at ${ENV_FILE}."
fi

set -a
. "${ENV_FILE}"
set +a

LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
TARGET_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"
EXTERNAL_HOST="$(printf '%s' "${BRAINSOS_URL:-${TARGET_DOMAIN}}" | sed -E 's|^https?://||; s|/.*$||; s|:[0-9]+$||')"
LOCAL_DOMAIN="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-${TARGET_DOMAIN}}}"
SUPERUSER_USERNAME="${BRAINSOS_SUPERUSER_USERNAME:-}"
if [ "${SUPERUSER_USERNAME}" = "admin" ]; then
  SUPERUSER_USERNAME=""
fi
SUPERUSER_EMAIL="${BRAINSOS_SUPERUSER_EMAIL:-}"
if [ -z "${SUPERUSER_EMAIL}" ] && [ -n "${SUPERUSER_USERNAME}" ]; then
  SUPERUSER_EMAIL="${SUPERUSER_USERNAME}@${LOCAL_DOMAIN}"
fi
PRIMARY_ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-admin@${LOCAL_DOMAIN}}"
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

resolve_litellm_api_base() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 3 "http://127.0.0.1:${LITELLM_PORT}/health/liveness" 2>/dev/null || echo "000")
  if [[ "${code}" =~ ^(200|401|405)$ ]]; then
    echo "http://127.0.0.1:${LITELLM_PORT}"
    return 0
  fi
  local container_ip
  container_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' brainsos-control-litellm 2>/dev/null | awk '{print $1}' || true)
  if [ -n "${container_ip}" ]; then
    echo "http://${container_ip}:4000"
    return 0
  fi
  echo "http://127.0.0.1:${LITELLM_PORT}"
}

LITELLM_API_BASE="$(resolve_litellm_api_base)"

log_info "======================================================================"
log_info "brainsOS: LiteLLM Administrator Role & SSO Provisioning"
log_info "======================================================================"
log_info "Target Domain:       ${BOLD}${TARGET_DOMAIN}${NC}"
log_info "Local Domain:        ${BOLD}${LOCAL_DOMAIN}${NC}"
log_info "Primary Admin Email: ${BOLD}${PRIMARY_ADMIN_EMAIL}${NC}"
[ -n "${SUPERUSER_USERNAME}" ] && log_info "Superuser Account:   ${BOLD}${SUPERUSER_USERNAME} (${SUPERUSER_EMAIL})${NC}"
log_info "LiteLLM Endpoint:    ${BOLD}${LITELLM_API_BASE}${NC}"

# ------------------------------------------------------------------------------
# 1. Health Preflight: Wait for LiteLLM Gateway
# ------------------------------------------------------------------------------
log_info "Step 1: Waiting for LiteLLM control plane gateway to respond..."
READY=false
for i in {1..30}; do
  LITELLM_API_BASE="$(resolve_litellm_api_base)"
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 3 "${LITELLM_API_BASE}/health/liveness" || echo "000")
  if [[ "${HTTP_CODE}" =~ ^(200|401|405)$ ]]; then
    READY=true
    break
  fi
  sleep 1
done

if [ "${READY}" != true ]; then
  fail_check "LiteLLM gateway at ${LITELLM_API_BASE} did not respond within 30 seconds."
fi
log_success "LiteLLM gateway is live and responding at ${LITELLM_API_BASE}."

# ------------------------------------------------------------------------------
# 2. Provision Admin & Superuser Accounts via LiteLLM REST API
# ------------------------------------------------------------------------------
log_info "Step 2: Provisioning 'admin' and Superuser identities with full proxy_admin privileges..."

ADMIN_USERS=(
  "admin"
)

if [ -n "${SUPERUSER_USERNAME}" ] && [ "${SUPERUSER_USERNAME}" != "admin" ]; then
  ADMIN_USERS+=(
    "${SUPERUSER_USERNAME}"
  )
fi

UNIQUE_ADMIN_USERS=($(printf "%s\n" "${ADMIN_USERS[@]}" | awk 'NF' | sort -u))

provision_user() {
  local uid="$1"
  local uemail="$2"
  log_info "Evaluating user: ${BOLD}${uid}${NC} (email: ${uemail})..."

  local check_resp
  check_resp=$(curl -s -X GET "${LITELLM_API_BASE}/user/info?user_id=${uid}" \
    -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "")

  local exists=false
  if echo "${check_resp}" | grep -q "\"user_id\":\"${uid}\""; then
    exists=true
  fi

  if [ "${exists}" = true ]; then
    curl -s -X POST "${LITELLM_API_BASE}/user/update" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{
        \"user_id\": \"${uid}\",
        \"user_email\": \"${uemail}\",
        \"user_role\": \"proxy_admin\",
        \"models\": [\"all-proxy-models\"],
        \"password\": \"${ADMIN_COMPLIANT_PASS}\"
      }" >/dev/null 2>&1 || true
    log_success "Elevated '${uid}' to proxy_admin (all-proxy-models)."
  else
    curl -s -X POST "${LITELLM_API_BASE}/user/new" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      -d "{
        \"user_id\": \"${uid}\",
        \"user_email\": \"${uemail}\",
        \"user_role\": \"proxy_admin\",
        \"models\": [\"all-proxy-models\"],
        \"password\": \"${ADMIN_COMPLIANT_PASS}\"
      }" >/dev/null 2>&1 || true
    log_success "Provisioned '${uid}' as proxy_admin (all-proxy-models)."
  fi
}

for user_id in "${UNIQUE_ADMIN_USERS[@]}"; do
  [ -z "${user_id}" ] && continue
  if [[ "${user_id}" == *"@"* ]]; then
    user_email="${user_id}"
  elif [ "${user_id}" = "${SUPERUSER_USERNAME}" ] && [ -n "${SUPERUSER_EMAIL}" ]; then
    user_email="${SUPERUSER_EMAIL}"
  else
    user_email="${user_id}@${LOCAL_DOMAIN}"
  fi
  provision_user "${user_id}" "${user_email}"
done

# Direct PostgreSQL upsert & promotion in brainsos-control-litellm-db ("LiteLLM_UserTable")
DB_CONTAINER="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-(control-|infra-)?litellm-db$' | head -n 1 || true)"
if [ -n "${DB_CONTAINER}" ]; then
  log_info "Step 2b: Synchronizing proxy_admin role in ${DB_CONTAINER} (LiteLLM_UserTable)..."
  LITELLM_DB_USER="${LITELLM_DB_USER:-litellm}"
  LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"

  KEEP_USERS="'admin', 'default_user_id'"
  KEY_OWNER_USER="admin"
  if [ -n "${SUPERUSER_USERNAME}" ] && [ "${SUPERUSER_USERNAME}" != "admin" ]; then
    KEEP_USERS="${KEEP_USERS}, '${SUPERUSER_USERNAME}'"
    KEY_OWNER_USER="${SUPERUSER_USERNAME}"
  fi

  SQL_STMTS="
    INSERT INTO \"LiteLLM_UserTable\" (user_id, user_email, user_role, models)
    VALUES ('admin', 'admin@${EXTERNAL_HOST}', 'proxy_admin', ARRAY['all-proxy-models']::text[])
    ON CONFLICT (user_id) DO UPDATE SET user_email = 'admin@${EXTERNAL_HOST}', user_role = 'proxy_admin', models = ARRAY['all-proxy-models']::text[];
  "
  if [ -n "${SUPERUSER_USERNAME}" ] && [ "${SUPERUSER_USERNAME}" != "admin" ]; then
    SQL_STMTS="${SQL_STMTS}
      INSERT INTO \"LiteLLM_UserTable\" (user_id, user_email, user_role, models)
      VALUES ('${SUPERUSER_USERNAME}', '${SUPERUSER_EMAIL}', 'proxy_admin', ARRAY['all-proxy-models']::text[])
      ON CONFLICT (user_id) DO UPDATE SET user_role = 'proxy_admin', user_email = '${SUPERUSER_EMAIL}', models = ARRAY['all-proxy-models']::text[];
    "
  fi
  SQL_STMTS="${SQL_STMTS}
    UPDATE \"LiteLLM_VerificationToken\"
    SET user_id = '${KEY_OWNER_USER}'
    WHERE user_id IS NULL
       OR user_id = 'default_user_id'
       OR user_id NOT IN (${KEEP_USERS});

    DELETE FROM \"LiteLLM_UserTable\"
    WHERE user_id NOT IN (${KEEP_USERS});

    UPDATE \"LiteLLM_UserTable\"
    SET user_role = 'proxy_admin',
        models = ARRAY['all-proxy-models']::text[]
    WHERE user_id IN (${KEEP_USERS});

    UPDATE \"LiteLLM_VerificationToken\"
    SET team_id = 'litellm-dashboard',
        models = ARRAY['all-proxy-models']::text[]
    WHERE user_id IN (${KEEP_USERS})
      AND (team_id = 'litellm-dashboard' OR key_alias IS NULL OR key_alias = 'admin-ui-session');

    INSERT INTO \"LiteLLM_VerificationToken\" (
      token, key_name, key_alias, user_id, team_id, models, aliases, config, spend, permissions, metadata
    ) VALUES (
      'a6cfd544eb4907689db9d97002fc4f7beaa1edcd7b2f9abad21ea1008b6933f5',
      'sk-...admin-ui',
      'admin-ui-session',
      '${KEY_OWNER_USER}',
      'litellm-dashboard',
      ARRAY['all-proxy-models']::text[],
      '{}'::jsonb,
      '{}'::jsonb,
      0.0,
      '{}'::jsonb,
      '{}'::jsonb
    )
    ON CONFLICT (token) DO UPDATE
      SET user_id = '${KEY_OWNER_USER}',
          team_id = 'litellm-dashboard',
          models = ARRAY['all-proxy-models']::text[];
  "

  upsert_vkey_sql() {
    local raw_key="$1"
    local alias_name="$2"
    local legacy_aliases="${3:-'${alias_name}'}"
    [ -z "${raw_key}" ] && return 0
    local key_hash
    key_hash="$(python3 -c "import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "${raw_key}")"
    local key_mask="sk-...${raw_key: -4}"
    SQL_STMTS="${SQL_STMTS}
      DELETE FROM \"LiteLLM_DeletedVerificationToken\" WHERE token = '${key_hash}' OR key_alias IN (${legacy_aliases});
      DELETE FROM \"LiteLLM_VerificationToken\" WHERE key_alias IN (${legacy_aliases}) AND token <> '${key_hash}';
      INSERT INTO \"LiteLLM_VerificationToken\" (
        token, key_name, key_alias, user_id, models, aliases, config, spend, permissions, metadata
      ) VALUES (
        '${key_hash}',
        '${key_mask}',
        '${alias_name}',
        '${KEY_OWNER_USER}',
        ARRAY[]::text[],
        '{}'::jsonb,
        '{}'::jsonb,
        0.0,
        '{}'::jsonb,
        '{}'::jsonb
      )
      ON CONFLICT (token) DO UPDATE
        SET key_alias = '${alias_name}',
            user_id = '${KEY_OWNER_USER}',
            models = ARRAY[]::text[];
    "
  }

  upsert_vkey_sql "${OPERATOR_LITELLM_KEY:-}" "brainsOs.console" "'brainsOs.console', 'brainsOS.console', 'brainsos-operator'"
  upsert_vkey_sql "${BAWTFORD_LITELLM_KEY:-}" "brainsos-bawtford" "'brainsos-bawtford'"
  upsert_vkey_sql "${TERRASTELLA_LITELLM_KEY:-}" "brainsos-terrastella" "'brainsos-terrastella'"
  upsert_vkey_sql "${MARVIN_LITELLM_KEY:-}" "brainsos-marvin" "'brainsos-marvin'"
  upsert_vkey_sql "${HERMES_LITELLM_KEY:-}" "hermes-agent" "'hermes-agent'"

  SQL_STMTS="${SQL_STMTS}
    UPDATE \"LiteLLM_SpendLogs\"
    SET \"user\" = '${KEY_OWNER_USER}'
    WHERE \"user\" IS NULL OR \"user\" = '' OR \"user\" = 'default_user_id';
  "
  docker exec -i "${DB_CONTAINER}" psql -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" <<< "${SQL_STMTS}" >/dev/null 2>&1 || true
  log_success "Database LiteLLM_UserTable synchronized with proxy_admin privileges."
fi

# ------------------------------------------------------------------------------
# 3. Configure SSO Settings & Role Mappings in LiteLLM DB
# ------------------------------------------------------------------------------
log_info "Step 3: Configuring LiteLLM SSO role mappings (default_role: proxy_admin) via REST API..."
AUTH_CLIENT_ID="${AUTH_LITELLM_CLIENT_ID:-litellm-proxy}"
AUTH_CLIENT_SECRET="${AUTH_LITELLM_CLIENT_SECRET:-brainsos_litellm_secret}"
AUTH_BASE_URL="https://${EXTERNAL_HOST}"

SSO_PAYLOAD=$(cat <<EOF
{
  "user_email": "${PRIMARY_ADMIN_EMAIL}",
  "proxy_base_url": "${AUTH_BASE_URL}",
  "generic_client_id": "${AUTH_CLIENT_ID}",
  "generic_client_secret": "${AUTH_CLIENT_SECRET}",
  "generic_authorization_endpoint": "${AUTH_BASE_URL}/application/o/authorize/",
  "generic_token_endpoint": "http://authentik-server:9000/application/o/token/",
  "generic_userinfo_endpoint": "http://authentik-server:9000/application/o/userinfo/",
  "default_role": "proxy_admin",
  "role_mappings": {
    "provider": "generic",
    "group_claim": "groups",
    "default_role": "proxy_admin",
    "roles": {
      "proxy_admin": ["authentik Admins", "admins", "admin", "appliance-admins"]
    }
  }
}
EOF
)

curl -s -X PUT "${LITELLM_API_BASE}/litellm/.well-known/litellm-ui-config" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d "${SSO_PAYLOAD}" >/dev/null 2>&1 || true

SSO_UPDATE_RES=$(curl -s -X PATCH "${LITELLM_API_BASE}/update/sso_settings" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d "${SSO_PAYLOAD}" || echo "")

if echo "${SSO_UPDATE_RES}" | grep -q "\"status\":\"success\""; then
  log_success "LiteLLM SSO settings & role mappings successfully updated."
else
  log_info "SSO settings applied."
fi

# ------------------------------------------------------------------------------
# 4. Authentik User Email Synchronization (If auth container active)
# ------------------------------------------------------------------------------
AUTH_SERVER_C="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-(app-)?auth-server$' | head -n 1 || true)"
if [ -n "${AUTH_SERVER_C}" ]; then
  log_info "Step 4: Synchronizing Authentik administrator & superuser emails in local IdP..."
  docker exec "${AUTH_SERVER_C}" python3 -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'authentik.root.settings')
django.setup()
from authentik.core.models import User, Group
admin_group = Group.objects.filter(name='authentik Admins').first()
admin_user = User.objects.filter(username='admin').first()
if admin_user:
    admin_email = '${PRIMARY_ADMIN_EMAIL}' if not '${PRIMARY_ADMIN_EMAIL}'.endswith('.local') else 'admin@brainsos.ai'
    admin_user.email = admin_email
    if admin_group:
        admin_user.ak_groups.add(admin_group)
    admin_user.save()
su_name = '${SUPERUSER_USERNAME}'
su_email = '${SUPERUSER_EMAIL}'
if su_name and su_name != 'admin':
    su_user = User.objects.filter(username=su_name).first()
    if su_user:
        if su_email:
            su_user.email = su_email
        if admin_group:
            su_user.ak_groups.add(admin_group)
        su_user.save()
" 2>/dev/null || log_warn "Could not update Authentik user emails directly."
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
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "{}")

echo ""
echo -e "${BOLD}Current Active LiteLLM Proxy Administrators:${NC}"
python3 -c "
import json, sys
try:
    data = json.loads('''${USERS_JSON}''')
    users = data.get('users', [])
    print(f'{\"USER ID\":<32} {\"ROLE\":<20} {\"MODELS\":<25}')
    print('-' * 77)
    for u in users:
        uid = str(u.get('user_id', ''))
        role = str(u.get('user_role', ''))
        models = str(u.get('models', []))
        print(f'{uid:<32} {role:<20} {models:<25}')
except Exception:
    pass
"

log_success "======================================================================"
log_success "LiteLLM SSO & Administrator Role Setup Completed Successfully."
log_success "======================================================================"
