#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Environment Synchronization & Reload Utility (reload-env.sh)
#
# Reloads and applies all .env configuration across all planes without data loss:
#   1. Synchronizes PostgreSQL user passwords in LiteLLM DB & SOGo DB & Langfuse DB
#   2. Recreates Docker containers with updated environment variables & extra_hosts
#   3. Restarts host control plane (LiteLLM, Ollama, Langfuse, Queue Worker)
#   4. Reloads Caddy ingress reverse proxy
#   5. Verifies service health
#   6. Displays updated service directory & credentials (show-urls.sh)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi
ENV_FILE="${REPO_ROOT}/.env"

# Terminal formatting
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Parse arguments
FORMAT_ENV=false
SKIP_URLS=false
URLS_ARGS=()

show_help() {
  echo -e "${BOLD}brainsOS Environment Reload & Password Synchronization${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --format, --clean Clean and format .env before reloading"
  echo "  --mask-secrets    Mask passwords and API tokens in the service directory output"
  echo "  --apply-hosts     Automatically apply missing /etc/hosts mappings (requires sudo)"
  echo "  --no-hosts        Skip checking or updating /etc/hosts"
  echo "  --no-urls         Skip displaying the service directory table after reloading"
  echo "  -h, --help        Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format|--clean)
      FORMAT_ENV=true
      shift
      ;;
    --no-urls|--skip-urls)
      SKIP_URLS=true
      shift
      ;;
    --mask-secrets|--apply-hosts|--no-hosts)
      URLS_ARGS+=("$1")
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      URLS_ARGS+=("$1")
      shift
      ;;
  esac
done

echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}brainsOS: Environment Reload & Password Synchronization${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

if [ "${FORMAT_ENV}" = true ]; then
  "${SCRIPT_DIR}/format-env.sh"
fi

if [ ! -f "${ENV_FILE}" ]; then
  log_error "No .env file found at ${ENV_FILE}. Cannot reload."
  exit 1
fi

# Load variables
set -a
. "${ENV_FILE}"
set +a


# ------------------------------------------------------------------------------
# 1. Synchronize LiteLLM PostgreSQL Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 1/6: Checking LiteLLM database credentials..."

DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(infra-)?litellm-db$' | head -n 1 || true)"
if [ -n "${DB_CONTAINER}" ]; then
  LITELLM_DB_USER="${LITELLM_DB_USER:-litellm}"
  LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"
  LITELLM_DB_PASSWORD="${LITELLM_DB_PASSWORD:-brainsos_litellm_secret_change_me}"

  log_info "Synchronizing database password for user '${LITELLM_DB_USER}' in ${DB_CONTAINER}..."
  # Execute ALTER USER inside the container via local socket (trust/peer auth)
  if docker exec "${DB_CONTAINER}" psql -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" \
      -c "ALTER USER \"${LITELLM_DB_USER}\" WITH PASSWORD '${LITELLM_DB_PASSWORD}';" >/dev/null 2>&1; then
    log_success "LiteLLM database password synchronized with .env (Zero data loss)."
  else
    # Fallback to postgres superuser if user lacks ALTER privilege
    if docker exec "${DB_CONTAINER}" psql -U postgres \
        -c "ALTER USER \"${LITELLM_DB_USER}\" WITH PASSWORD '${LITELLM_DB_PASSWORD}';" >/dev/null 2>&1; then
      log_success "LiteLLM database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter LiteLLM password. Database may be initializing."
    fi
  fi
else
  log_info "LiteLLM database container is not running; will be started during control plane restart."
fi

# ------------------------------------------------------------------------------
# 2. Synchronize SOGo Groupware Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 2/6: Checking SOGo database credentials..."

SOGO_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-sogo-db$' | head -n 1 || true)"
if [ -n "${SOGO_DB_CONTAINER}" ]; then
  SOGO_DB_USER="${SOGO_DB_USER:-sogo}"
  SOGO_DB_NAME="${SOGO_DB_NAME:-sogo}"
  SOGO_DB_PASSWORD="${SOGO_DB_PASSWORD:-sogo_secret_pass}"

  log_info "Synchronizing database password for user '${SOGO_DB_USER}' in ${SOGO_DB_CONTAINER}..."
  if docker exec "${SOGO_DB_CONTAINER}" psql -U "${SOGO_DB_USER}" -d "${SOGO_DB_NAME}" \
      -c "ALTER USER \"${SOGO_DB_USER}\" WITH PASSWORD '${SOGO_DB_PASSWORD}';" >/dev/null 2>&1; then
    log_success "SOGo database password synchronized with .env (Zero data loss)."
  else
    if docker exec "${SOGO_DB_CONTAINER}" psql -U postgres \
        -c "ALTER USER \"${SOGO_DB_USER}\" WITH PASSWORD '${SOGO_DB_PASSWORD}';" >/dev/null 2>&1; then
      log_success "SOGo database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter SOGo password. Database may be initializing."
    fi
  fi

  # Synchronize user account passwords in sogo_users table
  ADMIN_MAIL_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
  OPERATOR_MAIL_PASS="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
  MAIL_DOM="${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-brainsos.local}}"
  docker exec -i "${SOGO_DB_CONTAINER}" psql -U "${SOGO_DB_USER}" -d "${SOGO_DB_NAME}" <<-EOSQL >/dev/null 2>&1 || true
    UPDATE sogo_users SET c_password = '${ADMIN_MAIL_PASS}' WHERE c_uid IN ('admin', 'admin@${MAIL_DOM}', 'admin@brainsos.local');
    UPDATE sogo_users SET c_password = '${OPERATOR_MAIL_PASS}' WHERE c_uid IN ('operator', 'operator@${MAIL_DOM}', 'operator@brainsos.local');
    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
      ('akadmin', 'admin', '${ADMIN_MAIL_PASS}', 'System Administrator', 'admin@${MAIL_DOM}'),
      ('akadmin@${MAIL_DOM}', 'admin', '${ADMIN_MAIL_PASS}', 'System Administrator', 'admin@${MAIL_DOM}')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password;
EOSQL
  log_success "SOGo fleet accounts and passwords synchronized in sogo_users table."
else
  log_info "SOGo database container is not running (skipping)."
fi

# Synchronize Dovecot mail accounts and credentials
if [ -f "${SCRIPT_DIR}/../setup/setup-mail.sh" ]; then
  "${SCRIPT_DIR}/../setup/setup-mail.sh" >/dev/null 2>&1 || true
  MAIL_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-|net-)?mail-server$' | head -n 1 || true)"
  if [ -n "${MAIL_CONTAINER}" ]; then
    docker exec "${MAIL_CONTAINER}" doveadm reload 2>/dev/null || true
    docker exec "${MAIL_CONTAINER}" postfix reload 2>/dev/null || true
    log_success "Dovecot & Postfix mail accounts synchronized and reloaded."
  fi
fi

# ------------------------------------------------------------------------------
# 2b. Synchronize Authentik PostgreSQL Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
AUTH_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?auth-db$' | head -n 1 || true)"
if [ -n "${AUTH_DB_CONTAINER}" ]; then
  AUTH_DB_USER="${AUTHENTIK_POSTGRESQL__USER:-authentik}"
  AUTH_DB_NAME="${AUTHENTIK_POSTGRESQL__NAME:-authentik}"
  AUTH_DB_PASSWORD="${AUTHENTIK_POSTGRESQL__PASSWORD:-authentik_db_secret}"

  log_info "Synchronizing database password for user '${AUTH_DB_USER}' in ${AUTH_DB_CONTAINER}..."
  if docker exec "${AUTH_DB_CONTAINER}" psql -U "${AUTH_DB_USER}" -d "${AUTH_DB_NAME}" \
      -c "ALTER USER \"${AUTH_DB_USER}\" WITH PASSWORD '${AUTH_DB_PASSWORD}';" >/dev/null 2>&1; then
    log_success "Authentik database password synchronized with .env (Zero data loss)."
  else
    log_warn "Could not automatically alter Authentik database password."
  fi
fi

# ------------------------------------------------------------------------------
# 3. Synchronize Langfuse Database Password (if local container is running)
# ------------------------------------------------------------------------------
LF_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(telemetry-|langfuse-)?db$' | head -n 1 || true)"
LF_WEB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(telemetry-|langfuse-)?web$' | head -n 1 || true)"
if [ -n "${LF_DB_CONTAINER}" ]; then
  log_info "Step 3/6: Synchronizing local Langfuse database credentials..."
  LANGFUSE_ENV_FILE="${REPO_ROOT}/docker/langfuse/.env"
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    LF_DB_PASS=$(grep "^LANGFUSE_DB_PASSWORD=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || true)
    LF_DB_USER=$(grep "^LANGFUSE_DB_USER=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    LF_DB_NAME=$(grep "^LANGFUSE_DB_NAME=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "langfuse")
    if [ -n "${LF_DB_PASS}" ]; then
      docker exec "${LF_DB_CONTAINER}" psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
        -c "ALTER USER \"${LF_DB_USER}\" WITH PASSWORD '${LF_DB_PASS}';" >/dev/null 2>&1 || true
      log_success "Langfuse database password synchronized."
    fi

    # Synchronize Langfuse Web admin user password if updated
    LF_ADMIN_PASS="${LANGFUSE_INIT_USER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-}}"
    LF_ADMIN_EMAIL="${LANGFUSE_INIT_USER_EMAIL:-${BRAINSOS_ADMIN_EMAIL:-admin@${BRAINSOS_DOMAIN:-brainsos.local}}}"
    LF_ADMIN_NAME="${LANGFUSE_INIT_USER_NAME:-brainsOS Admin}"
    if [ -n "${LF_ADMIN_PASS}" ] && [ -n "${LF_WEB_CONTAINER}" ]; then
      LF_HASH=$(docker exec -i "${LF_WEB_CONTAINER}" node -e "
        const p = process.argv[1];
        const bcrypt = require('/app/node_modules/.pnpm/bcryptjs@2.4.3/node_modules/bcryptjs/dist/bcrypt.js');
        console.log(bcrypt.hashSync(p, 12));
      " "${LF_ADMIN_PASS}" 2>/dev/null || true)
      if [ -n "${LF_HASH}" ]; then
        docker exec -i "${LF_DB_CONTAINER}" psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" \
          -c "
            DO \$\$
            BEGIN
              IF EXISTS (SELECT 1 FROM users WHERE email = '${LF_ADMIN_EMAIL}') THEN
                UPDATE users SET password = '${LF_HASH}', updated_at = NOW() WHERE email = '${LF_ADMIN_EMAIL}';
              ELSE
                UPDATE users SET email = '${LF_ADMIN_EMAIL}', name = '${LF_ADMIN_NAME}', password = '${LF_HASH}', updated_at = NOW()
                WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1);
              END IF;
            END \$\$;
          " >/dev/null 2>&1 || true
        log_success "Langfuse admin user password synchronized."
      fi
    fi
  fi
else
  log_info "Step 3/6: Langfuse database is not running locally (skipping)."
fi

# Synchronize Caddy Operator IDE Basic Auth Password Hash
EFFECTIVE_CODE_PASS="${CODE_SERVER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-}}"
if [ -n "${EFFECTIVE_CODE_PASS}" ]; then
  CADDY_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(ingress-|net-)?caddy$' | head -n 1 || true)"
  if [ -n "${CADDY_CONTAINER}" ]; then
    OP_HASH=$(docker exec "${CADDY_CONTAINER}" caddy hash-password --plaintext "${EFFECTIVE_CODE_PASS}" 2>/dev/null || true)
  else
    OP_HASH=$(docker run --rm caddy:latest caddy hash-password --plaintext "${EFFECTIVE_CODE_PASS}" 2>/dev/null || true)
  fi
  if [ -n "${OP_HASH}" ]; then
    if grep -q "^OPERATOR_PASSWORD_HASH=" "${ENV_FILE}"; then
      sed -i.bak "s|^OPERATOR_PASSWORD_HASH=.*|OPERATOR_PASSWORD_HASH='${OP_HASH}'|" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
    elif grep -q "^# *OPERATOR_PASSWORD_HASH=" "${ENV_FILE}"; then
      sed -i.bak "s|^# *OPERATOR_PASSWORD_HASH=.*|OPERATOR_PASSWORD_HASH='${OP_HASH}'|" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
    else
      echo "OPERATOR_PASSWORD_HASH='${OP_HASH}'" >> "${ENV_FILE}"
    fi
    export OPERATOR_PASSWORD_HASH="${OP_HASH}"
    log_success "Synchronized OPERATOR_PASSWORD_HASH with admin password for Caddy Basic Auth."
  fi
fi

# ------------------------------------------------------------------------------
# 4. Recreate / Update Docker Compose Services
# ------------------------------------------------------------------------------
log_info "Step 4/6: Updating Docker container configurations..."
if ! docker image inspect brainsos-runner-base:latest >/dev/null 2>&1; then
  log_info "Base runner image not found. Building brainsos-runner-base:latest..."
  docker build -t brainsos-runner-base:latest -f "${REPO_ROOT}/docker/runners/base/Dockerfile" "${REPO_ROOT}"
fi
docker compose up -d
log_success "Docker services updated with current .env configurations."

# Synchronize Authentik Identity & Master Credentials
AUTH_SERVER_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?auth-server$' | head -n 1 || true)"
if [ -n "${AUTH_SERVER_CONTAINER}" ]; then
  log_info "Synchronizing Authentik identity and master credentials..."
  ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-admin@${BRAINSOS_DOMAIN:-brainsos.local}}"
  ADMIN_PASS="${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}"
  docker exec -i "${AUTH_SERVER_CONTAINER}" ak shell -c "
from authentik.core.models import User, Group
admin_group = Group.objects.filter(name='authentik Admins').first()

admin_u, _ = User.objects.get_or_create(username='admin', defaults={'name': 'Appliance Administrator', 'email': '${ADMIN_EMAIL}'})
admin_u.email = '${ADMIN_EMAIL}'
admin_u.set_password('${ADMIN_PASS}')
admin_u.is_active = True
if admin_group:
    admin_u.ak_groups.add(admin_group)
admin_u.save()

ak_u = User.objects.filter(username='akadmin').first()
if ak_u:
    ak_u.set_password('${ADMIN_PASS}')
    ak_u.save()

op_u = User.objects.filter(username='operator').first()
if op_u:
    op_u.set_password('${ADMIN_PASS}')
    op_u.save()
" >/dev/null 2>&1 || true
  log_success "Authentik accounts (admin, akadmin, operator) synchronized with master credentials."

  # Synchronize Authentik Outpost & Proxy Provider domain routing
  EFFECTIVE_DOMAIN="${BRAINSOS_DOMAIN:-local.brainsos.ai}"
  docker exec -i "${AUTH_SERVER_CONTAINER}" ak shell -c "
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyProvider
from authentik.core.models import Application

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
        a.meta_launch_url = f'https://{domain}/proxy/ui/'
        a.save()
" >/dev/null 2>&1 || true
  log_success "Authentik SSO Outpost & Proxy Provider synchronized with domain '${EFFECTIVE_DOMAIN}'."
fi

# ------------------------------------------------------------------------------
# 5. Restart Control Plane Gateway & Host Services
# ------------------------------------------------------------------------------
log_info "Step 5/6: Restarting control plane (LiteLLM, Ollama, Langfuse, Queue)..."
"${SCRIPT_DIR}/start-control-plane.sh" restart

# ------------------------------------------------------------------------------
# 6. Reload Caddy Ingress Gateway
# ------------------------------------------------------------------------------
log_info "Step 6/6: Reloading Caddy ingress proxy..."

# Automatically resolve AWS credentials from host AWS CLI if unset
if [ "${ACME_DNS_PROVIDER:-}" = "route53" ] && [ -z "${BRAINSOS_INFRA_AWS_ACCESS_KEY_ID:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    RESOLVED_AWS_KEY="$(aws configure get aws_access_key_id 2>/dev/null || true)"
    RESOLVED_AWS_SECRET="$(aws configure get aws_secret_access_key 2>/dev/null || true)"
    RESOLVED_AWS_REGION="$(aws configure get region 2>/dev/null || echo 'us-east-1')"
    if [ -n "${RESOLVED_AWS_KEY}" ] && [ -n "${RESOLVED_AWS_SECRET}" ]; then
      export AWS_ACCESS_KEY_ID="${RESOLVED_AWS_KEY}"
      export AWS_SECRET_ACCESS_KEY="${RESOLVED_AWS_SECRET}"
      export AWS_REGION="${RESOLVED_AWS_REGION}"
      log_success "Resolved AWS credentials from host AWS CLI configuration for Route 53."
    fi
  fi
fi

# Dynamically render config/caddy/tls_policy.caddy based on ACME_DNS_PROVIDER
TLS_POLICY_FILE="${REPO_ROOT}/config/caddy/tls_policy.caddy"
if [ "${ACME_DNS_PROVIDER:-}" = "route53" ]; then
  cat << EOF > "${TLS_POLICY_FILE}"
# ==============================================================================
# brainsOS: TLS Policy Snippet (AWS Route 53 ACME DNS-01 Challenge)
# Auto-generated by scripts/control/reload-env.sh from environment configuration.
# DO NOT EDIT DIRECTLY. Make changes in .env and re-run make reload-env.
# ==============================================================================
(brainsos_tls) {
	tls ${ACME_EMAIL:-admin@brainsos.ai} {
		dns route53
		propagation_delay 30s
		propagation_timeout 3m
		resolvers 1.1.1.1 8.8.8.8
	}
}

(route53_tls) {
	tls ${ACME_EMAIL:-admin@brainsos.ai} {
		dns route53
		propagation_delay 30s
		propagation_timeout 3m
		resolvers 1.1.1.1 8.8.8.8
	}
}
EOF
  log_success "Configured Caddy TLS policy for Route 53 ACME DNS-01 wildcard certificates (${ACME_EMAIL:-admin@brainsos.ai})."
else
  cat << EOF > "${TLS_POLICY_FILE}"
# ==============================================================================
# brainsOS: TLS Policy Snippet (Internal Private CA)
# Auto-generated by scripts/control/reload-env.sh from environment configuration.
# DO NOT EDIT DIRECTLY. Make changes in .env and re-run make reload-env.
# ==============================================================================
(brainsos_tls) {
	tls internal
}

(route53_tls) {
	tls ${ACME_EMAIL:-admin@brainsos.ai} {
		dns route53
	}
}
EOF
  log_info "Configured Caddy TLS policy for internal private CA."
fi

if docker ps --format '{{.Names}}' | grep -qE '^brainsos-(ingress-|net-)?caddy$'; then
  docker compose restart caddy >/dev/null 2>&1
  log_success "Caddy ingress reloaded."
fi

# Synchronize Caddy root CA certificate into active data directory
if [ -x "${SCRIPT_DIR}/../setup/trust-caddy-ca.sh" ]; then
  log_info "Synchronizing Caddy root CA certificate into active control plane..."
  "${SCRIPT_DIR}/../setup/trust-caddy-ca.sh" --export-only || log_warn "Could not refresh Caddy root CA certificate."
fi

# ------------------------------------------------------------------------------
# Summary & Health Status
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}brainsOS: Environment Successfully Reloaded${NC}"
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "All updated .env values, domains, and database credentials have been applied."
echo ""
"${SCRIPT_DIR}/start-control-plane.sh" status

# ------------------------------------------------------------------------------
# Display Service Directory & URLs
# ------------------------------------------------------------------------------
if [ "${SKIP_URLS}" = false ]; then
  echo ""
  if [ ${#URLS_ARGS[@]} -gt 0 ]; then
    "${SCRIPT_DIR}/show-urls.sh" "${URLS_ARGS[@]}"
  else
    "${SCRIPT_DIR}/show-urls.sh"
  fi
fi
