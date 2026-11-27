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


# Ensure current working directory is REPO_ROOT for compose operations
cd "${REPO_ROOT}"

# ------------------------------------------------------------------------------
# 0a. Optional Boot-Time Source Auto-Pull (Appliance Mode)
# ------------------------------------------------------------------------------
if [[ "${BRAINSOS_AUTO_PULL_ON_BOOT:-false}" =~ ^(true|1|yes)$ ]] && [ "${RELOAD_ENV_SKIP_PULL:-false}" != "true" ]; then
  if [ -d "${REPO_ROOT}/.git" ] && command -v git >/dev/null 2>&1; then
    git config --system --add safe.directory "${REPO_ROOT}" 2>/dev/null || true
    ACTIVE_GIT_BRANCH="${BRAINSOS_GIT_BRANCH:-$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")}"
    [ "${ACTIVE_GIT_BRANCH}" = "HEAD" ] && ACTIVE_GIT_BRANCH="main"
    BEFORE_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    log_info "Checking origin/${ACTIVE_GIT_BRANCH} for latest source updates..."
    if timeout 20 git -C "${REPO_ROOT}" fetch --quiet origin "${ACTIVE_GIT_BRANCH}" 2>/dev/null; then
      REMOTE_SHA="$(git -C "${REPO_ROOT}" rev-parse FETCH_HEAD 2>/dev/null || true)"
      if [ -n "${REMOTE_SHA}" ] && [ "${REMOTE_SHA}" != "${BEFORE_SHA}" ]; then
        log_info "Auto-pulling latest source on boot (${BEFORE_SHA:0:12} -> ${REMOTE_SHA:0:12} on ${ACTIVE_GIT_BRANCH})..."
        CHANGED_FILES="$(git -C "${REPO_ROOT}" diff --name-only "${BEFORE_SHA}" "${REMOTE_SHA}" 2>/dev/null || true)"
        git -C "${REPO_ROOT}" checkout --quiet -B "${ACTIVE_GIT_BRANCH}" FETCH_HEAD 2>/dev/null || true
        git -C "${REPO_ROOT}" reset --hard FETCH_HEAD >/dev/null 2>&1 || true
        git -C "${REPO_ROOT}" update-ref "refs/remotes/origin/${ACTIVE_GIT_BRANCH}" "${REMOTE_SHA}" 2>/dev/null || true
        git -C "${REPO_ROOT}" branch --quiet --set-upstream-to="origin/${ACTIVE_GIT_BRANCH}" "${ACTIVE_GIT_BRANCH}" 2>/dev/null || true
        chmod +x "${REPO_ROOT}"/scripts/*/*.sh "${REPO_ROOT}"/packages/brainsOS-appliance/scripts/*.sh "${REPO_ROOT}"/docker/*/*.sh 2>/dev/null || true
        if echo "${CHANGED_FILES}" | grep -q "^packages/brainsOS-portal/" && [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
          log_info "Portal source updated; rebuilding Portal SPA bundle..."
          "${REPO_ROOT}/scripts/setup/setup-portal.sh" || log_warn "Portal rebuild encountered a warning."
        fi
        if echo "${CHANGED_FILES}" | grep -q "^packages/brainsOS-telemetry/" && command -v systemctl >/dev/null 2>&1; then
          systemctl restart brainsos-system-api.service 2>/dev/null || true
        fi
        log_success "Updated source tree to ${ACTIVE_GIT_BRANCH}@${REMOTE_SHA:0:12}; re-executing reload-env.sh..."
        export RELOAD_ENV_SKIP_PULL=true
        exec "${REPO_ROOT}/scripts/control/reload-env.sh" "${URLS_ARGS[@]}" $([ "${SKIP_URLS}" = true ] && echo "--no-urls")
      else
        log_success "Source tree is already at latest ${ACTIVE_GIT_BRANCH}@${BEFORE_SHA:0:12}."
      fi
    else
      log_warn "Could not reach origin/${ACTIVE_GIT_BRANCH} (offline); continuing with local source."
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 0b. AWS EC2 Dynamic Public IP / Public DNS Reconciliation on Boot or Resume
# ------------------------------------------------------------------------------
if command -v curl >/dev/null 2>&1 && [ -f "${REPO_ROOT}/scripts/control/env-upsert.sh" ]; then
  _IMDS_TOK=""
  _IMDS_ATTEMPTS=1
  [ "${BRAINSOS_APPLIANCE:-false}" = "true" ] && _IMDS_ATTEMPTS=5
  for (( _i=1; _i<=_IMDS_ATTEMPTS; _i++ )); do
    _IMDS_TOK="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 60" \
      --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    [ -n "${_IMDS_TOK}" ] && break
    [ "${_i}" -lt "${_IMDS_ATTEMPTS}" ] && sleep 1
  done
  if [ -n "${_IMDS_TOK}" ]; then
    _PUB_IP="$(curl -s -f -H "X-aws-ec2-metadata-token: ${_IMDS_TOK}" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    _LOC_IP="$(curl -s -f -H "X-aws-ec2-metadata-token: ${_IMDS_TOK}" \
      "http://169.254.169.254/latest/meta-data/local-ipv4" --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    _PUB_HOST="$(curl -s -f -H "X-aws-ec2-metadata-token: ${_IMDS_TOK}" \
      "http://169.254.169.254/latest/meta-data/public-hostname" --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    _INST_ID="$(curl -s -f -H "X-aws-ec2-metadata-token: ${_IMDS_TOK}" \
      "http://169.254.169.254/latest/meta-data/instance-id" --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    [ -z "${_INST_ID}" ] && _INST_ID="${BRAINSOS_INSTANCE_ID:-}"

    _EFFECTIVE_NEW_HOST="${_PUB_HOST:-${_PUB_IP}}"
    _CUR_DOMAIN="${BRAINSOS_DOMAIN:-}"
    _NEW_DOMAIN="${_CUR_DOMAIN}"

    if [ -n "${_EFFECTIVE_NEW_HOST}" ]; then
      if [[ "${_CUR_DOMAIN}" == *.amazonaws.com ]] || [[ "${_CUR_DOMAIN}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || [ -z "${_CUR_DOMAIN}" ]; then
        _NEW_DOMAIN="${_EFFECTIVE_NEW_HOST}"
      fi
    fi

    _NEW_IP_SITES=""
    for _ip in "${_PUB_IP}" "${_LOC_IP}"; do
      if [[ "${_ip}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] && [ "${_ip}" != "${_NEW_DOMAIN}" ]; then
        case " ${_NEW_IP_SITES} " in *" ${_ip} "*) ;; *) _NEW_IP_SITES="${_NEW_IP_SITES:+${_NEW_IP_SITES} }${_ip}" ;; esac
      fi
    done
    [ -z "${_NEW_IP_SITES}" ] && _NEW_IP_SITES="127.0.0.1"

    _ENV_UPDATES=()
    if [ -n "${_NEW_DOMAIN}" ] && [ "${_NEW_DOMAIN}" != "${_CUR_DOMAIN}" ]; then
      log_info "Detected EC2 public hostname/IP change on reboot (${_CUR_DOMAIN} -> ${_NEW_DOMAIN}); updating .env..."
      _ENV_UPDATES+=(
        "BRAINSOS_DOMAIN=${_NEW_DOMAIN}"
        "BRAINSOS_URL=${_NEW_DOMAIN}"
        "NEXTAUTH_URL=https://${_NEW_DOMAIN}"
      )
    fi
    if [ "${_NEW_IP_SITES}" != "${BRAINSOS_IP_SITES:-}" ]; then
      _ENV_UPDATES+=("BRAINSOS_IP_SITES=${_NEW_IP_SITES}")
    fi

    # Route 53 Dynamic DNS (DDNS) auto-sync on reboot / stop-start / hibernation resume (#373)
    if [ -n "${BRAINSOS_ROUTE53_ZONE_ID:-}" ] \
      && [[ "${_NEW_DOMAIN}" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]] \
      && [[ "${_NEW_DOMAIN}" != *.amazonaws.com ]] \
      && [[ "${_PUB_IP}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
      && [ "${_PUB_IP}" != "${BRAINSOS_LAST_SYNCED_IP:-}" ] \
      && [ -f "${REPO_ROOT}/scripts/control/sync-route53-ddns.py" ]; then
      _DDNS_PY="${REPO_ROOT}/.venv/bin/python"
      [ ! -x "${_DDNS_PY}" ] && _DDNS_PY="python3"
      _DDNS_ARGS=(
        --domain "${_NEW_DOMAIN}"
        --ip "${_PUB_IP}"
        --zone-id "${BRAINSOS_ROUTE53_ZONE_ID}"
      )
      [ -n "${_INST_ID}" ] && _DDNS_ARGS+=(--instance-id "${_INST_ID}")
      [ "${BRAINSOS_ROUTE53_FORCE:-false}" = "true" ] && _DDNS_ARGS+=(--force)
      log_info "Synchronizing Route 53 DNS A record: ${_NEW_DOMAIN} -> ${_PUB_IP} (zone ${BRAINSOS_ROUTE53_ZONE_ID})..."
      if "${_DDNS_PY}" "${REPO_ROOT}/scripts/control/sync-route53-ddns.py" "${_DDNS_ARGS[@]}"; then
        log_success "Route 53 DDNS updated: ${_NEW_DOMAIN} -> ${_PUB_IP}"
        _ENV_UPDATES+=("BRAINSOS_LAST_SYNCED_IP=${_PUB_IP}")
      else
        log_warn "Route 53 DDNS sync failed on boot/resume (continuing startup without blocking)."
      fi
    fi

    if [ "${#_ENV_UPDATES[@]}" -gt 0 ]; then
      "${REPO_ROOT}/scripts/control/env-upsert.sh" --file "${ENV_FILE}" "${_ENV_UPDATES[@]}" >/dev/null 2>&1 || true
      set -a
      . "${ENV_FILE}"
      set +a
      if [ "${_NEW_DOMAIN}" != "${_CUR_DOMAIN}" ] && [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
        log_info "Rebuilding Portal bundle for new EC2 hostname (${_NEW_DOMAIN})..."
        "${REPO_ROOT}/scripts/setup/setup-portal.sh" >/dev/null 2>&1 || true
      fi
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 0. Ensure Persistence Stores & Databases Are Running
# ------------------------------------------------------------------------------
log_info "Ensuring persistence stores and database engines are running..."
docker compose up -d litellm-db sogo-db authentik-db langfuse-db clickhouse redis authentik-redis minio >/dev/null 2>&1 || true

for db in brainsos-control-litellm-db brainsos-app-sogo-db brainsos-app-auth-db brainsos-telemetry-langfuse-db; do
  if docker ps -q -f name="^${db}$" | grep -q .; then
    for i in $(seq 1 15); do
      if docker exec "${db}" pg_isready >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
  fi
done

# Safe parameterized PostgreSQL password & SOGo helpers (zero SQL interpolation)
alter_pg_password() {
  local container="$1"
  local pg_user="$2"
  local pg_db="$3"
  local target_user="$4"
  local new_pass="$5"
  docker exec -i "${container}" psql -v ON_ERROR_STOP=1 -U "${pg_user}" -d "${pg_db}" \
    -v target_user="${target_user}" -v new_pass="${new_pass}" <<'EOSQL' >/dev/null 2>&1
ALTER USER :"target_user" WITH PASSWORD :'new_pass';
EOSQL
}

sync_sogo_users() {
  local container="$1"
  local sogo_user="$2"
  local sogo_db="$3"
  local admin_mail_pass="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
  local operator_mail_pass="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"
  local terrastella_pass="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
  local bawtford_pass="${BAWTFORD_MAIL_PASSWORD:-brainsos_bawtford_mail_secret_change_me}"
  local marvin_pass="${MARVIN_MAIL_PASSWORD:-brainsos_marvin_mail_secret_change_me}"
  local ping_pass="${PING_MAIL_PASSWORD:-brainsos_ping_mail_secret_change_me}"
  local claude_pass="${CLAUDE_MAIL_PASSWORD:-brainsos_claude_mail_secret_change_me}"
  local gpt_pass="${GPT_MAIL_PASSWORD:-brainsos_gpt_mail_secret_change_me}"
  local mail_dom="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-brainsos.local}}}"
  local admin_user="${BRAINSOS_SUPERUSER_USERNAME:-${BRAINSOS_ADMIN_USERNAME:-admin}}"
  local superuser_cn="${BRAINSOS_SUPERUSER_NAME:-System Administrator}"
  local admin_email="${admin_user}@${mail_dom}"
  local admin_dom_uid="admin@${mail_dom}"
  local akadmin_dom_uid="akadmin@${mail_dom}"
  local su_dom_uid="${admin_user}@${mail_dom}"

  docker exec -i "${container}" psql -U "${sogo_user}" -d "${sogo_db}" \
    -v admin_mail_pass="${admin_mail_pass}" \
    -v operator_mail_pass="${operator_mail_pass}" \
    -v terrastella_pass="${terrastella_pass}" \
    -v bawtford_pass="${bawtford_pass}" \
    -v marvin_pass="${marvin_pass}" \
    -v ping_pass="${ping_pass}" \
    -v claude_pass="${claude_pass}" \
    -v gpt_pass="${gpt_pass}" \
    -v mail_dom="${mail_dom}" \
    -v admin_user="${admin_user}" \
    -v superuser_cn="${superuser_cn}" \
    -v admin_email="${admin_email}" \
    -v admin_dom_uid="${admin_dom_uid}" \
    -v akadmin_dom_uid="${akadmin_dom_uid}" \
    -v su_dom_uid="${su_dom_uid}" \
    -v op_email="operator@${mail_dom}" \
    -v op_dom_uid="operator@${mail_dom}" <<'EOSQL' >/dev/null 2>&1 || true
    CREATE TABLE IF NOT EXISTS sogo_users (
        c_uid VARCHAR(128) PRIMARY KEY,
        c_name VARCHAR(128) NOT NULL,
        c_password VARCHAR(128) NOT NULL,
        c_cn VARCHAR(128) NOT NULL,
        mail VARCHAR(128) NOT NULL
    );
    UPDATE sogo_users SET c_password = :'admin_mail_pass', mail = :'admin_email'
      WHERE c_name = 'admin' OR c_uid IN ('admin', :'admin_dom_uid', 'admin@brainsos.local', 'akadmin', :'akadmin_dom_uid', 'akadmin@brainsos.local');
    UPDATE sogo_users SET c_password = :'operator_mail_pass', mail = :'op_email'
      WHERE c_name = 'operator' OR c_uid IN ('operator', :'op_dom_uid', 'operator@brainsos.local');
    UPDATE sogo_users SET mail = c_name || '@' || :'mail_dom'
      WHERE c_name IN ('terrastella', 'bawtford', 'marvin', 'ping', 'claude', 'gpt');
    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail) VALUES
      ('admin', 'admin', :'admin_mail_pass', 'System Administrator', :'admin_email'),
      (:'admin_dom_uid', 'admin', :'admin_mail_pass', 'System Administrator', :'admin_email'),
      ('akadmin', 'admin', :'admin_mail_pass', 'System Administrator', :'admin_email'),
      (:'akadmin_dom_uid', 'admin', :'admin_mail_pass', 'System Administrator', :'admin_email'),
      ('operator', 'operator', :'operator_mail_pass', 'Human Operator', :'op_email'),
      ('terrastella', 'terrastella', :'terrastella_pass', 'Terrastella Agent', 'terrastella@' || :'mail_dom'),
      ('bawtford', 'bawtford', :'bawtford_pass', 'Bawtford Agent', 'bawtford@' || :'mail_dom'),
      ('marvin', 'marvin', :'marvin_pass', 'Marvin Agent', 'marvin@' || :'mail_dom'),
      ('ping', 'ping', :'ping_pass', 'Ping Autoresponder Agent', 'ping@' || :'mail_dom'),
      ('claude', 'claude', :'claude_pass', 'Claude Demo Agent', 'claude@' || :'mail_dom'),
      ('gpt', 'gpt', :'gpt_pass', 'GPT Demo Agent', 'gpt@' || :'mail_dom')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, mail = EXCLUDED.mail;
    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail)
      SELECT :'admin_user', 'admin', :'admin_mail_pass', :'superuser_cn', :'admin_email'
      WHERE :'admin_user' <> '' AND :'admin_user' NOT IN ('admin', 'akadmin')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, c_cn = EXCLUDED.c_cn, mail = EXCLUDED.mail;
    INSERT INTO sogo_users (c_uid, c_name, c_password, c_cn, mail)
      SELECT :'su_dom_uid', 'admin', :'admin_mail_pass', :'superuser_cn', :'admin_email'
      WHERE :'admin_user' <> '' AND :'admin_user' NOT IN ('admin', 'akadmin')
    ON CONFLICT (c_uid) DO UPDATE SET c_password = EXCLUDED.c_password, c_cn = EXCLUDED.c_cn, mail = EXCLUDED.mail;
    CREATE OR REPLACE VIEW sogo_addressbook AS
    SELECT c_uid, c_name, c_password, c_cn, mail
    FROM sogo_users
    WHERE c_uid IN (:'admin_user', 'operator', 'terrastella', 'bawtford', 'marvin', 'ping', 'claude', 'gpt');
EOSQL
}

# ------------------------------------------------------------------------------
# 1. Synchronize LiteLLM PostgreSQL Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 1/6: Checking LiteLLM database credentials..."

DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(control-|infra-)?litellm-db$' | head -n 1 || true)"
if [ -n "${DB_CONTAINER}" ]; then
  LITELLM_DB_USER="${LITELLM_DB_USER:-litellm}"
  LITELLM_DB_NAME="${LITELLM_DB_NAME:-litellm}"
  LITELLM_DB_PASSWORD="${LITELLM_DB_PASSWORD:-brainsos_litellm_secret_change_me}"

  log_info "Synchronizing database password for user '${LITELLM_DB_USER}' in ${DB_CONTAINER}..."
  if alter_pg_password "${DB_CONTAINER}" "${LITELLM_DB_USER}" "${LITELLM_DB_NAME}" "${LITELLM_DB_USER}" "${LITELLM_DB_PASSWORD}"; then
    log_success "LiteLLM database password synchronized with .env (Zero data loss)."
  else
    if alter_pg_password "${DB_CONTAINER}" postgres "${LITELLM_DB_NAME}" "${LITELLM_DB_USER}" "${LITELLM_DB_PASSWORD}"; then
      log_success "LiteLLM database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter LiteLLM password. Database may be initializing."
    fi
  fi
  docker exec "${DB_CONTAINER}" psql -U "${LITELLM_DB_USER}" -d "${LITELLM_DB_NAME}" \
    -c "UPDATE \"LiteLLM_VerificationToken\" SET key_alias = 'brainsOs.console' WHERE key_alias LIKE '%/editor/%' OR key_alias = 'brainsos-operator';" >/dev/null 2>&1 || true
else
  log_info "LiteLLM database container is not running; will be started during control plane restart."
fi

# ------------------------------------------------------------------------------
# 2. Synchronize SOGo Groupware Database Password (Zero Data Loss)
# ------------------------------------------------------------------------------
log_info "Step 2/6: Checking SOGo database credentials..."

SOGO_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?sogo-db$' | head -n 1 || true)"
if [ -n "${SOGO_DB_CONTAINER}" ]; then
  SOGO_DB_USER="${SOGO_DB_USER:-sogo}"
  SOGO_DB_NAME="${SOGO_DB_NAME:-sogo}"
  SOGO_DB_PASSWORD="${SOGO_DB_PASSWORD:-sogo_secret_pass}"

  log_info "Synchronizing database password for user '${SOGO_DB_USER}' in ${SOGO_DB_CONTAINER}..."
  if alter_pg_password "${SOGO_DB_CONTAINER}" "${SOGO_DB_USER}" "${SOGO_DB_NAME}" "${SOGO_DB_USER}" "${SOGO_DB_PASSWORD}"; then
    log_success "SOGo database password synchronized with .env (Zero data loss)."
  else
    if alter_pg_password "${SOGO_DB_CONTAINER}" postgres "${SOGO_DB_NAME}" "${SOGO_DB_USER}" "${SOGO_DB_PASSWORD}"; then
      log_success "SOGo database password synchronized via postgres role."
    else
      log_warn "Could not automatically alter SOGo password. Database may be initializing."
    fi
  fi

  sync_sogo_users "${SOGO_DB_CONTAINER}" "${SOGO_DB_USER}" "${SOGO_DB_NAME}"
  log_success "SOGo fleet accounts and passwords synchronized in sogo_users table."
else
  log_info "SOGo database container is not running (skipping pre-up check)."
fi

# Synchronize Dovecot mail accounts and credentials
if [ -f "${SCRIPT_DIR}/../setup/setup-mail.sh" ]; then
  "${SCRIPT_DIR}/../setup/setup-mail.sh" --accounts-only >/dev/null 2>&1 || true
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
  if alter_pg_password "${AUTH_DB_CONTAINER}" "${AUTH_DB_USER}" "${AUTH_DB_NAME}" "${AUTH_DB_USER}" "${AUTH_DB_PASSWORD}"; then
    log_success "Authentik database password synchronized with .env (Zero data loss)."
  else
    log_warn "Could not automatically alter Authentik database password."
  fi
fi


# ------------------------------------------------------------------------------
# 3. Synchronize Langfuse Database Password (if local container is running)
# ------------------------------------------------------------------------------
LF_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(telemetry-langfuse-|telemetry-|langfuse-)?db$' | head -n 1 || true)"
LF_WEB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(telemetry-langfuse-|telemetry-|langfuse-)?web$' | head -n 1 || true)"
if [ -n "${LF_DB_CONTAINER}" ]; then
  log_info "Step 3/6: Synchronizing local Langfuse database credentials..."
  LANGFUSE_ENV_FILE="${REPO_ROOT}/docker/langfuse/.env"
  LF_DB_PASS="${LANGFUSE_DB_PASSWORD:-}"
  LF_DB_USER="${LANGFUSE_DB_USER:-langfuse}"
  LF_DB_NAME="${LANGFUSE_DB_NAME:-langfuse}"
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    LF_DB_PASS=$(grep "^LANGFUSE_DB_PASSWORD=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "${LF_DB_PASS}")
    LF_DB_USER=$(grep "^LANGFUSE_DB_USER=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "${LF_DB_USER}")
    LF_DB_NAME=$(grep "^LANGFUSE_DB_NAME=" "${LANGFUSE_ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "${LF_DB_NAME}")
  fi
  if [ -n "${LF_DB_PASS}" ]; then
    alter_pg_password "${LF_DB_CONTAINER}" "${LF_DB_USER}" "${LF_DB_NAME}" "${LF_DB_USER}" "${LF_DB_PASS}" || true
    log_success "Langfuse database password synchronized."
  fi

  # Check if any existing Langfuse user is missing membership in project 'brainsos'.
  # If so, rotate NEXTAUTH_SECRET before 'docker compose up -d' so any stale browser
  # NextAuth JWT cookie (cached with organizations=[]) is invalidated and refreshed via OIDC.
  UNLINKED_LF_USERS=$(docker exec -i "${LF_DB_CONTAINER}" psql -U "${LF_DB_USER}" -d "${LF_DB_NAME}" -tc "
    SELECT COUNT(*) FROM users u
    WHERE NOT EXISTS (
      SELECT 1 FROM project_memberships pm WHERE pm.user_id = u.id AND pm.project_id = 'brainsos'
    );
  " 2>/dev/null | tr -d '[:space:]' || echo "0")
  if [ -n "${UNLINKED_LF_USERS}" ] && [ "${UNLINKED_LF_USERS}" != "0" ]; then
    log_info "Detected ${UNLINKED_LF_USERS} Langfuse user(s) missing 'brainsos' project membership; rotating NEXTAUTH_SECRET to refresh SSO sessions..."
    NEW_NEXTAUTH_SECRET="$(python3 -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())' 2>/dev/null || openssl rand -base64 32)"
    "${REPO_ROOT}/scripts/control/env-upsert.sh" --file "${ENV_FILE}" "NEXTAUTH_SECRET=${NEW_NEXTAUTH_SECRET}" >/dev/null 2>&1 || true
    export NEXTAUTH_SECRET="${NEW_NEXTAUTH_SECRET}"
  fi
else
  log_info "Step 3/6: Langfuse database is not running locally (skipping pre-up check)."
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

# Ensure SYSTEM_API_TOKEN and BRAINSOS_UNIT_NAME exist in .env before docker compose up -d
if [ -z "${SYSTEM_API_TOKEN:-}" ]; then
  SYSTEM_API_TOKEN="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')"
  "${REPO_ROOT}/scripts/control/env-upsert.sh" --file "${ENV_FILE}" "SYSTEM_API_TOKEN=${SYSTEM_API_TOKEN}" >/dev/null 2>&1 || true
  export SYSTEM_API_TOKEN
fi
if [ -z "${BRAINSOS_UNIT_NAME:-}" ]; then
  BRAINSOS_UNIT_NAME="Enterprise Agent Box"
  "${REPO_ROOT}/scripts/control/env-upsert.sh" --file "${ENV_FILE}" "BRAINSOS_UNIT_NAME=${BRAINSOS_UNIT_NAME}" >/dev/null 2>&1 || true
  export BRAINSOS_UNIT_NAME
fi

# Provision LiteLLM Lens secrets & shared ClickHouse KeeperMap / isolated `lens` DB before compose up (#375)
if [ -x "${REPO_ROOT}/scripts/setup/setup-lens.sh" ]; then
  "${REPO_ROOT}/scripts/setup/setup-lens.sh" --pre-up || log_warn "Lens pre-up ClickHouse check encountered a warning."
  set -a
  . "${ENV_FILE}"
  set +a
fi

# ------------------------------------------------------------------------------
# 4. Recreate / Update Docker Compose Services
# ------------------------------------------------------------------------------
log_info "Step 4/6: Updating Docker container configurations..."
if ! docker image inspect brainsos-runner-base:latest >/dev/null 2>&1; then
  log_info "Base runner image not found. Building brainsos-runner-base:latest..."
  docker build -t brainsos-runner-base:latest -f "${REPO_ROOT}/docker/runners/base/Dockerfile" "${REPO_ROOT}"
fi

# Ensure caddy_root.crt and runner/settings bind-mounted files exist as regular files before docker compose bind-mounts them
EFFECTIVE_DATA_DIR="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/../data}"
if [[ "${EFFECTIVE_DATA_DIR}" != /* ]]; then
  EFFECTIVE_DATA_DIR="${REPO_ROOT}/${EFFECTIVE_DATA_DIR#./}"
fi
mkdir -p \
  "${EFFECTIVE_DATA_DIR}/control_plane" \
  "${EFFECTIVE_DATA_DIR}/control_plane/caddy_data" \
  "${EFFECTIVE_DATA_DIR}/runners/hermes" \
  "${EFFECTIVE_DATA_DIR}/runners/hermes/state" \
  "${EFFECTIVE_DATA_DIR}/settings"

# One-time seamless migration of legacy Docker named volumes into ${EFFECTIVE_DATA_DIR} bind mounts (#382)
if [ -z "$(ls -A "${EFFECTIVE_DATA_DIR}/runners/hermes/state" 2>/dev/null)" ] && docker volume inspect brainsos_hermes_runner_data >/dev/null 2>&1; then
  log_info "Migrating legacy brainsos_hermes_runner_data volume into ${EFFECTIVE_DATA_DIR}/runners/hermes/state..."
  docker run --rm -v brainsos_hermes_runner_data:/src:ro -v "${EFFECTIVE_DATA_DIR}/runners/hermes/state:/dst" \
    --entrypoint sh brainsos-runner-base:latest -c 'cp -a /src/. /dst/ 2>/dev/null || true' || true
fi
if [ -z "$(ls -A "${EFFECTIVE_DATA_DIR}/control_plane/caddy_data" 2>/dev/null)" ] && docker volume inspect brainsos_caddy_data >/dev/null 2>&1; then
  log_info "Migrating legacy brainsos_caddy_data volume into ${EFFECTIVE_DATA_DIR}/control_plane/caddy_data..."
  docker run --rm -v brainsos_caddy_data:/src:ro -v "${EFFECTIVE_DATA_DIR}/control_plane/caddy_data:/dst" \
    --entrypoint sh brainsos-runner-base:latest -c 'cp -a /src/. /dst/ 2>/dev/null || true' || true
fi
if [ "$(id -u)" -eq 0 ]; then
  chown 1000:1000 "${EFFECTIVE_DATA_DIR}/runners/hermes/state" 2>/dev/null || true
fi
if [ -d "${EFFECTIVE_DATA_DIR}/control_plane/caddy_root.crt" ]; then
  rm -rf "${EFFECTIVE_DATA_DIR}/control_plane/caddy_root.crt"
fi
if [ ! -f "${EFFECTIVE_DATA_DIR}/control_plane/caddy_root.crt" ]; then
  touch "${EFFECTIVE_DATA_DIR}/control_plane/caddy_root.crt" 2>/dev/null || true
fi
for hfile in config.yaml config.json model_pool.json mcp.json; do
  if [ -d "${EFFECTIVE_DATA_DIR}/runners/hermes/${hfile}" ]; then
    rm -rf "${EFFECTIVE_DATA_DIR}/runners/hermes/${hfile}"
  fi
  if [ ! -f "${EFFECTIVE_DATA_DIR}/runners/hermes/${hfile}" ] && [ -f "${REPO_ROOT}/config/default_runners/hermes/${hfile}" ]; then
    cp "${REPO_ROOT}/config/default_runners/hermes/${hfile}" "${EFFECTIVE_DATA_DIR}/runners/hermes/${hfile}"
  fi
done
for sfile in agents.yaml runners.yaml; do
  if [ ! -f "${EFFECTIVE_DATA_DIR}/settings/${sfile}" ] && [ -f "${REPO_ROOT}/config/default_settings/${sfile}" ]; then
    cp "${REPO_ROOT}/config/default_settings/${sfile}" "${EFFECTIVE_DATA_DIR}/settings/${sfile}"
  fi
done

docker compose up -d
log_success "Docker services updated with current .env configurations."
if [ -x "${REPO_ROOT}/scripts/setup/imds-guard.sh" ]; then
  "${REPO_ROOT}/scripts/setup/imds-guard.sh" --apply || log_warn "IMDS guard could not be applied."
fi

# ------------------------------------------------------------------------------
# 4b. Post-Up SOGo & Mail Synchronization (ensures live containers match .env)
# ------------------------------------------------------------------------------
SOGO_DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?sogo-db$' | head -n 1 || true)"
if [ -n "${SOGO_DB_CONTAINER}" ]; then
  SOGO_DB_USER="${SOGO_DB_USER:-sogo}"
  SOGO_DB_NAME="${SOGO_DB_NAME:-sogo}"
  sync_sogo_users "${SOGO_DB_CONTAINER}" "${SOGO_DB_USER}" "${SOGO_DB_NAME}"
  docker exec -i "${SOGO_DB_CONTAINER}" psql -U "${SOGO_DB_USER}" -d "${SOGO_DB_NAME}" \
    -c "DELETE FROM sogo_user_profile WHERE c_defaults LIKE '%@brainsos.local%' OR c_defaults LIKE '%@local.brainsos.ai%';" >/dev/null 2>&1 || true
fi

if [ -f "${SCRIPT_DIR}/../setup/setup-mail.sh" ]; then
  "${SCRIPT_DIR}/../setup/setup-mail.sh" --accounts-only >/dev/null 2>&1 || true
  MAIL_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-|net-)?mail-server$' | head -n 1 || true)"
  if [ -n "${MAIL_CONTAINER}" ]; then
    docker exec "${MAIL_CONTAINER}" postmap lmdb:/etc/mail-brainsos/vmailbox 2>/dev/null || true
    docker exec "${MAIL_CONTAINER}" postmap lmdb:/etc/mail-brainsos/virtual 2>/dev/null || true
    docker exec "${MAIL_CONTAINER}" doveadm reload 2>/dev/null || true
    docker exec "${MAIL_CONTAINER}" postfix reload 2>/dev/null || true
  fi
fi

# Restart SOGo container so sogod and memcached reload sogo.conf (SOGoMailDomain) and flush addressbook cache
SOGO_CONTAINER="$(docker ps -a --format '{{.Names}}' | grep -E '^brainsos-(app-|net-)?sogo$' | head -n 1 || true)"
if [ -n "${SOGO_CONTAINER}" ]; then
  log_info "Restarting SOGo container (${SOGO_CONTAINER}) to refresh domain & addressbook cache..."
  docker compose restart sogo >/dev/null 2>&1 || docker restart "${SOGO_CONTAINER}" >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# 4c. Post-Up Langfuse Organization, Project, Membership & Trigger Sync
# ------------------------------------------------------------------------------
if [ -x "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" ]; then
  "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" sync || log_warn "Langfuse post-up sync encountered a warning."
fi

# Synchronize Local Git Server (Gitea) & /data Repository (#332)
if [ -x "${REPO_ROOT}/scripts/setup/setup-git.sh" ]; then
  "${REPO_ROOT}/scripts/setup/setup-git.sh" || log_warn "Gitea seed sync encountered a warning."
fi

# Synchronize Authentik Identity & Master Credentials
AUTH_SERVER_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E '^brainsos-(app-)?auth-server$' | head -n 1 || true)"
if [ -n "${AUTH_SERVER_CONTAINER}" ]; then
  RAW_URL="${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}"
  EFFECTIVE_DOMAIN="$(printf '%s' "${RAW_URL}" | sed -E 's|^https?://||; s|/.*$||; s|:[0-9]+$||')"
  log_info "Waiting for Authentik blueprint & Embedded Outpost readiness..."
  for i in $(seq 1 60); do
    if docker exec -i -e EFFECTIVE_DOMAIN="${EFFECTIVE_DOMAIN}" "${AUTH_SERVER_CONTAINER}" ak shell -c '
import os, sys
from authentik.outposts.models import Outpost
dom = os.environ.get("EFFECTIVE_DOMAIN", "local.brainsos.ai")
expected = f"https://{dom}"
for o in Outpost.objects.all():
    if o._config.get("authentik_host") != expected:
        o._config["authentik_host"] = expected
        o._config["authentik_host_browser"] = expected
        o.save()
sys.exit(0 if Outpost.objects.filter(providers__isnull=False).exists() else 1)
' >/dev/null 2>&1; then
      break
    fi
    # On a fresh database, default blueprints (flows/certs) may still be applying when
    # authentik-worker first discovers brainsos-portal.yaml; explicitly apply it once ready.
    if [ $((i % 4)) -eq 0 ]; then
      docker exec -i "${AUTH_SERVER_CONTAINER}" ak apply_blueprint /blueprints/zzz-brainsos/brainsos-portal.yaml >/dev/null 2>&1 || \
      docker exec -i "${AUTH_SERVER_CONTAINER}" ak apply_blueprint /blueprints/brainsos/brainsos-portal.yaml >/dev/null 2>&1 || true
    fi
    sleep 2
  done

  log_info "Synchronizing Authentik identity and master credentials..."
  SUPERUSER_USER="${BRAINSOS_SUPERUSER_USERNAME:-${BRAINSOS_ADMIN_USERNAME:-admin}}"
  ADMIN_USER="${SUPERUSER_USER}"
  SUPERUSER_DISPLAY_NAME="${BRAINSOS_SUPERUSER_NAME:-${SUPERUSER_USER}}"
  LOCAL_DOM="${BRAINSOS_LOCAL_DOMAIN:-${EFFECTIVE_DOMAIN:-brainsos.ai}}"
  BREAKGLASS_ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-admin@${EFFECTIVE_DOMAIN:-${LOCAL_DOM}}}"
  if [[ "${BREAKGLASS_ADMIN_EMAIL}" == *.local ]]; then
    BREAKGLASS_ADMIN_EMAIL="admin@brainsos.ai"
  fi
  ADMIN_EMAIL="${BRAINSOS_SUPERUSER_EMAIL:-${BRAINSOS_ADMIN_EMAIL:-${SUPERUSER_USER}@${LOCAL_DOM}}}"
  if [[ "${ADMIN_EMAIL}" == *.local ]]; then
    ADMIN_EMAIL="${SUPERUSER_USER}@brainsos.ai"
  fi
  SUPERUSER_PASS="${BRAINSOS_SUPERUSER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-}}"

  # Resolve EC2 Instance ID so 'admin' / 'akadmin' stay bound to the Instance ID (#332)
  INSTANCE_ADMIN_PASS=""
  if command -v curl >/dev/null 2>&1; then
    _IMDS_TOK="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" --connect-timeout 1 --max-time 1 2>/dev/null || true)"
    if [ -n "${_IMDS_TOK}" ]; then
      INSTANCE_ADMIN_PASS="$(curl -s -f -H "X-aws-ec2-metadata-token: ${_IMDS_TOK}" "http://169.254.169.254/latest/meta-data/instance-id" --connect-timeout 1 --max-time 1 2>/dev/null || true)"
    fi
  fi
  if [ -z "${INSTANCE_ADMIN_PASS}" ]; then
    INSTANCE_ADMIN_PASS="${BRAINSOS_INSTANCE_ID:-${BRAINSOS_INSTANCE_ADMIN_PASSWORD:-${AUTHENTIK_BOOTSTRAP_PASSWORD:-${SUPERUSER_PASS}}}}"
  fi

  BREAKGLASS_ENABLED="${BRAINSOS_BREAKGLASS_ENABLED:-true}"
  USER_SUB="${BRAINSOS_USER_SUB:-}"
  OWNER_ONLY="${BRAINSOS_OWNER_ONLY:-true}"
  COGNITO_ENABLED="${AUTH_COGNITO_ENABLED:-false}"
  COGNITO_REGION="${AUTH_COGNITO_REGION:-}"
  COGNITO_POOL_ID="${AUTH_COGNITO_USER_POOL_ID:-}"
  COGNITO_DOMAIN="${AUTH_COGNITO_DOMAIN:-}"
  COGNITO_CLIENT_ID="${AUTH_COGNITO_CLIENT_ID:-}"
  COGNITO_CLIENT_SECRET="${AUTH_COGNITO_CLIENT_SECRET:-}"
  COGNITO_ADMIN_GROUP="${AUTH_COGNITO_ADMIN_GROUP:-brainsos-admins}"
  ALB_OIDC_ENABLED="${AUTH_ALB_OIDC_ENABLED:-false}"

  docker exec -i \
    -e AK_BREAKGLASS_ENABLED="${BREAKGLASS_ENABLED}" \
    -e AK_BREAKGLASS_EMAIL="${BREAKGLASS_ADMIN_EMAIL}" \
    -e AK_INSTANCE_PASS="${INSTANCE_ADMIN_PASS}" \
    -e AK_SUPERUSER_USER="${SUPERUSER_USER}" \
    -e AK_SUPERUSER_NAME="${SUPERUSER_DISPLAY_NAME}" \
    -e AK_ADMIN_EMAIL="${ADMIN_EMAIL}" \
    -e AK_SUPERUSER_PASS="${SUPERUSER_PASS}" \
    -e AK_EFFECTIVE_DOMAIN="${EFFECTIVE_DOMAIN:-brainsos.ai}" \
    -e AK_USER_SUB="${USER_SUB}" \
    -e AK_COGNITO_ENABLED="${COGNITO_ENABLED}" \
    -e AK_ALB_OIDC_ENABLED="${ALB_OIDC_ENABLED}" \
    "${AUTH_SERVER_CONTAINER}" ak shell -c '
import os
from authentik.core.models import User, Group

admin_group = Group.objects.filter(name="authentik Admins").first()
breakglass_enabled = os.environ.get("AK_BREAKGLASS_ENABLED", "true").strip().lower() not in ("false", "0", "no")
su_user = os.environ.get("AK_SUPERUSER_USER", "").strip()
su_name = os.environ.get("AK_SUPERUSER_NAME", "").strip() or su_user
admin_email = os.environ.get("AK_ADMIN_EMAIL", "").strip()
su_pass = os.environ.get("AK_SUPERUSER_PASS", "")
bg_email = os.environ.get("AK_BREAKGLASS_EMAIL", "admin@brainsos.ai").strip()
inst_pass = os.environ.get("AK_INSTANCE_PASS", "")
dom = os.environ.get("AK_EFFECTIVE_DOMAIN", "brainsos.ai").strip() or "brainsos.ai"
user_sub = os.environ.get("AK_USER_SUB", "").strip()
cognito_on = os.environ.get("AK_COGNITO_ENABLED", "false").strip().lower() == "true"
alb_on = os.environ.get("AK_ALB_OIDC_ENABLED", "false").strip().lower() == "true"

has_named_su = bool(su_user and su_user not in ("admin", "akadmin"))
has_owner_sso = bool(user_sub and (cognito_on or alb_on))
lock_breakglass = (not breakglass_enabled) and (has_named_su or has_owner_sso)

admin_u, _ = User.objects.get_or_create(
    username="admin",
    defaults={"name": "Appliance Administrator", "email": bg_email},
)
admin_u.email = bg_email
if lock_breakglass:
    admin_u.set_unusable_password()
    admin_u.is_active = False
else:
    if inst_pass:
        admin_u.set_password(inst_pass)
    admin_u.is_active = True
    if admin_group:
        admin_u.ak_groups.add(admin_group)
admin_u.save()

if has_named_su:
    custom_u, _ = User.objects.get_or_create(
        username=su_user,
        defaults={"name": su_name, "email": admin_email},
    )
    custom_u.name = su_name
    custom_u.email = admin_email
    if su_pass:
        custom_u.set_password(su_pass)
    custom_u.is_active = True
    try:
        custom_u.attributes["is_superuser"] = True
    except Exception:
        pass
    if admin_group:
        custom_u.ak_groups.add(admin_group)
    custom_u.save()

ak_u = User.objects.filter(username="akadmin").first()
if ak_u:
    ak_u.email = f"akadmin@{dom}"
    if lock_breakglass:
        ak_u.set_unusable_password()
        ak_u.is_active = False
    else:
        if inst_pass:
            ak_u.set_password(inst_pass)
        ak_u.is_active = True
    ak_u.save()

op_u, _ = User.objects.get_or_create(
    username="operator",
    defaults={"name": "Appliance Operator", "email": "operator@brainsos.ai"},
)
if op_u.email.endswith(".local"):
    op_u.email = "operator@brainsos.ai"
if su_pass:
    op_u.set_password(su_pass)
op_u.is_active = True
if admin_group:
    op_u.ak_groups.add(admin_group)
op_u.save()
' >/dev/null 2>&1 || true
  log_success "Authentik accounts (${SUPERUSER_USER}, admin [breakglass=${BREAKGLASS_ENABLED}], akadmin, operator) synchronized."

  # Synchronize Authentik Outpost, Proxy Provider, OAuth2 OIDC secrets/domains, and Cognito OAuthSource
  RAW_URL="${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}"
  EFFECTIVE_DOMAIN="$(printf '%s' "${RAW_URL}" | sed -E 's|^https?://||; s|/.*$||; s|:[0-9]+$||')"
  LITELLM_CLIENT_SECRET="${AUTH_LITELLM_CLIENT_SECRET:-}"
  LANGFUSE_CLIENT_SECRET="${AUTH_LANGFUSE_CLIENT_SECRET:-}"
  OPENBAO_CLIENT_SECRET="${AUTH_OPENBAO_CLIENT_SECRET:-}"
  docker exec -i \
    -e AK_EFFECTIVE_DOMAIN="${EFFECTIVE_DOMAIN}" \
    -e AK_LITELLM_CLIENT_SECRET="${LITELLM_CLIENT_SECRET}" \
    -e AK_LANGFUSE_CLIENT_SECRET="${LANGFUSE_CLIENT_SECRET}" \
    -e AK_OPENBAO_CLIENT_SECRET="${OPENBAO_CLIENT_SECRET}" \
    -e AK_COGNITO_ENABLED="${COGNITO_ENABLED}" \
    -e AK_COGNITO_REGION="${COGNITO_REGION}" \
    -e AK_COGNITO_POOL_ID="${COGNITO_POOL_ID}" \
    -e AK_COGNITO_DOMAIN="${COGNITO_DOMAIN}" \
    -e AK_COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID}" \
    -e AK_COGNITO_CLIENT_SECRET="${COGNITO_CLIENT_SECRET}" \
    -e AK_COGNITO_ADMIN_GROUP="${COGNITO_ADMIN_GROUP}" \
    -e AK_USER_SUB="${USER_SUB}" \
    -e AK_OWNER_ONLY="${OWNER_ONLY}" \
    "${AUTH_SERVER_CONTAINER}" ak shell -c '
import json, os
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyProvider
from authentik.providers.oauth2.models import OAuth2Provider
from authentik.core.models import Application, Group
from authentik.flows.models import Flow
from authentik.sources.oauth.models import OAuthSource, OAuthSourcePropertyMapping
from authentik.stages.identification.models import IdentificationStage

domain = os.environ.get("AK_EFFECTIVE_DOMAIN", "local.brainsos.ai").strip() or "local.brainsos.ai"
cookie_dom = "local.brainsos.ai" if domain.endswith("local.brainsos.ai") else ""
litellm_secret = os.environ.get("AK_LITELLM_CLIENT_SECRET", "")
langfuse_secret = os.environ.get("AK_LANGFUSE_CLIENT_SECRET", "")
openbao_secret = os.environ.get("AK_OPENBAO_CLIENT_SECRET", "")

for o in Outpost.objects.all():
    o._config["authentik_host"] = f"https://{domain}"
    o._config["authentik_host_browser"] = f"https://{domain}"
    o.save()

proxy_redirects = "\n".join([
    f"https://{domain}/outpost.goauthentik.io/callback?X-authentik-auth-callback=true",
    f"https://{domain}?X-authentik-auth-callback=true",
    "https://local.brainsos.ai/outpost.goauthentik.io/callback?X-authentik-auth-callback=true",
    "https://local.brainsos.ai?X-authentik-auth-callback=true",
])
for p in ProxyProvider.objects.all():
    p.external_host = f"https://{domain}"
    p.cookie_domain = cookie_dom
    p.access_token_validity = "days=7"
    p.refresh_token_validity = "days=30"
    p.redirect_uris = proxy_redirects
    p.save()

litellm_redirects = "\n".join([
    f"https://{domain}/sso/callback",
    f"https://{domain}/proxy/ui/sso/callback",
    f"https://proxy.{domain}/sso/callback",
    "https://local.brainsos.ai/sso/callback",
    "https://local.brainsos.ai/proxy/ui/sso/callback",
    "http://localhost:4000/sso/callback",
])
langfuse_redirects = "\n".join([
    f"https://{domain}/api/auth/callback/custom",
    f"https://langfuse.{domain}/api/auth/callback/custom",
    "https://local.brainsos.ai/api/auth/callback/custom",
    "http://localhost:3001/api/auth/callback/custom",
])
for oa in OAuth2Provider.objects.all():
    if oa.client_id == "litellm-proxy":
        if litellm_secret:
            oa.client_secret = litellm_secret
        oa.redirect_uris = litellm_redirects
        oa.save()
    elif oa.client_id == "langfuse-trace":
        if langfuse_secret:
            oa.client_secret = langfuse_secret
        oa.redirect_uris = langfuse_redirects
        oa.save()
    elif oa.client_id == "openbao-vault":
        if openbao_secret:
            oa.client_secret = openbao_secret
        oa.redirect_uris = "\n".join([
            f"https://{domain}/ui/vault/auth/oidc/oidc/callback",
            f"https://secrets.{domain}/ui/vault/auth/oidc/oidc/callback",
            "https://local.brainsos.ai/ui/vault/auth/oidc/oidc/callback",
            "http://localhost:8200/ui/vault/auth/oidc/oidc/callback",
            "http://localhost:8250/oidc/callback",
        ])
        oa.save()

for a in Application.objects.all():
    if a.slug == "brainsos-portal":
        a.meta_launch_url = f"https://{domain}/"
        a.save()
    elif a.slug == "litellm":
        a.meta_launch_url = f"https://{domain}/proxy/ui/"
        a.save()
    elif a.slug == "langfuse":
        a.meta_launch_url = f"https://{domain}/project/brainsos/sessions"
        a.save()
    elif a.slug == "openbao-vault":
        a.meta_launch_url = f"https://{domain}/ui/vault/"
        a.save()

# AWS Cognito Direct OIDC Federation (opt-in) & EBS Owner Mapping (#385)
cognito_enabled = os.environ.get("AK_COGNITO_ENABLED", "false").strip().lower() == "true"
cog_region = os.environ.get("AK_COGNITO_REGION", "").strip()
cog_pool = os.environ.get("AK_COGNITO_POOL_ID", "").strip()
cog_domain = os.environ.get("AK_COGNITO_DOMAIN", "").strip()
cog_client_id = os.environ.get("AK_COGNITO_CLIENT_ID", "").strip()
cog_client_secret = os.environ.get("AK_COGNITO_CLIENT_SECRET", "").strip()
cog_admin_group = os.environ.get("AK_COGNITO_ADMIN_GROUP", "brainsos-admins").strip() or "brainsos-admins"
owner_sub = os.environ.get("AK_USER_SUB", "").strip()
owner_only = os.environ.get("AK_OWNER_ONLY", "true").strip().lower() not in ("false", "0", "no")

ident_stage = IdentificationStage.objects.filter(name="default-authentication-identification").first()
if cognito_enabled and cog_region and cog_pool and cog_client_id:
    Group.objects.get_or_create(name="brainsos-viewers")
    well_known = f"https://cognito-idp.{cog_region}.amazonaws.com/{cog_pool}/.well-known/openid-configuration"
    auth_flow = Flow.objects.filter(slug="default-source-authentication").first()
    enroll_flow = Flow.objects.filter(slug="default-source-enrollment").first()

    pm_expr = "\n".join([
        f"owner_sub = {json.dumps(owner_sub)}",
        f"admin_group = {json.dumps(cog_admin_group)}",
        f"owner_only = {bool(owner_only)!r}",
        "sub = str(info.get(\"sub\") or \"\").strip()",
        "raw_groups = info.get(\"cognito:groups\") or info.get(\"groups\") or []",
        "if isinstance(raw_groups, str):",
        "    raw_groups = [g.strip() for g in raw_groups.split(\",\") if g.strip()]",
        "groups = [str(g).strip() for g in raw_groups if str(g).strip()]",
        "is_owner = bool(owner_sub and sub == owner_sub)",
        "is_group_admin = bool(admin_group and any(g.lower() == admin_group.lower() for g in groups))",
        "is_admin = is_owner or is_group_admin",
        "if is_admin and \"authentik Admins\" not in groups:",
        "    groups.append(\"authentik Admins\")",
        "elif not is_admin and \"brainsos-viewers\" not in groups:",
        "    groups.append(\"brainsos-viewers\")",
        "username = info.get(\"preferred_username\") or info.get(\"cognito:username\") or info.get(\"username\") or info.get(\"email\") or sub",
        "return {",
        "    \"username\": username,",
        "    \"email\": info.get(\"email\") or f\"{username}@cognito.local\",",
        "    \"name\": info.get(\"name\") or username,",
        "    \"groups\": groups,",
        "    \"is_active\": False if (owner_only and not is_admin) else True,",
        "}",
    ])
    pm, _ = OAuthSourcePropertyMapping.objects.get_or_create(
        name="brainsos-cognito-user-mapping",
        defaults={"expression": pm_expr},
    )
    pm.expression = pm_expr
    pm.save()

    src, _ = OAuthSource.objects.get_or_create(
        slug="cognito",
        defaults={
            "name": "AWS Cognito",
            "provider_type": "openidconnect",
            "consumer_key": cog_client_id,
            "consumer_secret": cog_client_secret,
            "oidc_well_known_url": well_known,
            "additional_scopes": "openid email profile",
            "user_matching_mode": "email_link",
            "group_matching_mode": "name_link",
            "enabled": True,
        },
    )
    src.name = "AWS Cognito"
    src.provider_type = "openidconnect"
    src.consumer_key = cog_client_id
    if cog_client_secret:
        src.consumer_secret = cog_client_secret
    src.oidc_well_known_url = well_known
    if cog_domain:
        cog_host = cog_domain if "://" in cog_domain else (
            cog_domain if "." in cog_domain else f"{cog_domain}.auth.{cog_region}.amazoncognito.com"
        )
        cog_host = cog_host.removeprefix("https://").removeprefix("http://").rstrip("/")
        src.authorization_url = f"https://{cog_host}/oauth2/authorize"
        src.access_token_url = f"https://{cog_host}/oauth2/token"
        src.profile_url = f"https://{cog_host}/oauth2/userInfo"
    src.oidc_jwks_url = f"https://cognito-idp.{cog_region}.amazonaws.com/{cog_pool}/.well-known/jwks.json"
    src.additional_scopes = "openid email profile"
    src.user_matching_mode = "email_link"
    src.group_matching_mode = "name_link"
    if auth_flow:
        src.authentication_flow = auth_flow
    if enroll_flow:
        src.enrollment_flow = enroll_flow
    src.enabled = True
    src.save()
    src.user_property_mappings.set([pm])
    if ident_stage:
        ident_stage.sources.add(src)
else:
    existing_src = OAuthSource.objects.filter(slug="cognito").first()
    if existing_src:
        existing_src.enabled = False
        existing_src.save()
        if ident_stage:
            ident_stage.sources.remove(existing_src)
' >/dev/null 2>&1 || true
  log_success "Authentik SSO Outpost, Proxy/OAuth2 Providers & Cognito federation synchronized with domain '${EFFECTIVE_DOMAIN}'."
fi

# ------------------------------------------------------------------------------
# 5. Restart Control Plane Gateway & Host Services
# ------------------------------------------------------------------------------
log_info "Step 5/6: Restarting control plane (LiteLLM, Ollama, Langfuse, Queue)..."
"${SCRIPT_DIR}/start-control-plane.sh" restart

if [ -x "${REPO_ROOT}/scripts/setup/setup-litellm-sso.sh" ]; then
  "${REPO_ROOT}/scripts/setup/setup-litellm-sso.sh" || true
fi

if [ -x "${REPO_ROOT}/scripts/setup/setup-secrets.sh" ]; then
  "${REPO_ROOT}/scripts/setup/setup-secrets.sh" --sync-oidc || true
fi

# Synchronize LiteLLM Lens tenant-matched tracing key after LiteLLM SSO owner resolution (#375)
if [ -x "${REPO_ROOT}/scripts/setup/setup-lens.sh" ]; then
  _PREV_LENS_TRACE_KEY="${LITELLM_TRACING_KEY:-}"
  "${REPO_ROOT}/scripts/setup/setup-lens.sh" sync || log_warn "LiteLLM Lens tracing key sync encountered a warning."
  set -a
  . "${ENV_FILE}"
  set +a
  if [ "${_PREV_LENS_TRACE_KEY}" != "${LITELLM_TRACING_KEY:-}" ]; then
    "${SCRIPT_DIR}/start-control-plane.sh" restart >/dev/null 2>&1 || true
  fi
fi

# Synchronize Operator IDE (code-server) with active LiteLLM virtual key
if docker ps --format '{{.Names}}' | grep -qE '^brainsos-(app-)?code-server$'; then
  docker compose up -d code-server >/dev/null 2>&1 || true
  log_success "Operator IDE (code-server) synchronized with LiteLLM virtual key."
fi

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

# Dynamically render config/caddy/tls_policy.caddy based on ACME_DNS_PROVIDER and BRAINSOS_TLS_MODE
TLS_POLICY_FILE="${REPO_ROOT}/config/caddy/tls_policy.caddy"
if [ "${ACME_DNS_PROVIDER:-}" = "route53" ] || [ "${BRAINSOS_TLS_MODE:-}" = "route53" ]; then
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
elif [ "${BRAINSOS_TLS_MODE:-}" = "acme" ] || [ "${BRAINSOS_TLS_MODE:-}" = "public_acme" ]; then
  cat << EOF > "${TLS_POLICY_FILE}"
# ==============================================================================
# brainsOS: TLS Policy Snippet (Public ACME HTTP-01 / TLS-ALPN-01)
# Auto-generated by scripts/control/reload-env.sh from environment configuration.
# DO NOT EDIT DIRECTLY. Make changes in .env and re-run make reload-env.
# ==============================================================================
(brainsos_tls) {
	tls ${ACME_EMAIL:-admin@brainsos.ai}
}

(route53_tls) {
	tls ${ACME_EMAIL:-admin@brainsos.ai} {
		dns route53
	}
}
EOF
  log_success "Configured Caddy TLS policy for Public ACME (Let's Encrypt / ZeroSSL) certificates (${ACME_EMAIL:-admin@brainsos.ai})."
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
git -C "${REPO_ROOT}" update-index --assume-unchanged config/caddy/tls_policy.caddy 2>/dev/null || true


if docker ps --format '{{.Names}}' | grep -qE '^brainsos-(ingress-|net-)?caddy$'; then
  docker compose up -d caddy >/dev/null 2>&1 || true
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
