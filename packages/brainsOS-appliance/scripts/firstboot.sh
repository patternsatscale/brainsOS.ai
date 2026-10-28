#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Appliance First-Boot Provisioner & IMDSv2 Cloud-Init Engine
# Ticket #313 / #322 (Epic #309)
#
# Runs once on initial VM startup (before brainsos.service):
#   1. Queries AWS IMDSv2 for instance-id, hostname, IPs and region
#   2. Delegates secret generation to scripts/control/generate-env.sh (single
#      source of truth) so every secret is unique per instance
#   3. Applies appliance overrides: operator password = instance-id (AWS
#      Marketplace convention), independent service passwords, compose overlay,
#      Bedrock LiteLLM catalog, region, inference mode
#   4. Seeds the data/ tree and validates .venv via scripts/control/bootstrap-env.sh
#   5. Rebuilds the portal bundle for the real hostname (offline)
#   6. Marks the appliance initialized
# ==============================================================================

set -euo pipefail

# Visual styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

DRY_RUN=false
CHECK_MODE=false
SKIP_IMDS="${BRAINSOS_FIRSTBOOT_SKIP_IMDS:-false}"
SKIP_PORTAL="${BRAINSOS_FIRSTBOOT_SKIP_PORTAL:-false}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --check)
      CHECK_MODE=true
      shift
      ;;
    --skip-imds)
      SKIP_IMDS=true
      shift
      ;;
    --skip-portal)
      SKIP_PORTAL=true
      shift
      ;;
    -h|--help)
      cat <<EOF
brainsOS Appliance First-Boot Provisioner (Tickets #313 / #322)

Usage:
  ./packages/brainsOS-appliance/scripts/firstboot.sh [OPTIONS]

Options:
  --dry-run       Simulate first-boot execution without writing .env or disabling service
  --check         Verify if first-boot initialization has been performed
  --skip-imds     Do not query EC2 instance metadata (baremetal / tests)
  --skip-portal   Do not rebuild the portal bundle
  -h, --help      Show this help message

Environment:
  BRAINSOS_REPO_ROOT                 Override repository root (tests)
  BRAINSOS_FIRSTBOOT_SKIP_IMDS       Same as --skip-imds
  BRAINSOS_FIRSTBOOT_SKIP_PORTAL     Same as --skip-portal
  BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP  Skip data/ + .venv seeding (tests only)
EOF
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

INIT_FLAG="${REPO_ROOT}/.brainsos-initialized"
TARGET_ENV="${REPO_ROOT}/.env"
GENERATE_ENV="${REPO_ROOT}/scripts/control/generate-env.sh"

if [ "${CHECK_MODE}" = true ]; then
  if [ -f "${INIT_FLAG}" ]; then
    log_success "Appliance is initialized (${INIT_FLAG} present)."
    exit 0
  else
    log_info "Appliance has not been initialized yet (${INIT_FLAG} not found)."
    exit 1
  fi
fi

if [ -f "${INIT_FLAG}" ] && [ "${DRY_RUN}" = false ]; then
  log_info "Appliance already initialized at $(cat "${INIT_FLAG}"). Exiting."
  exit 0
fi

log_info "Starting brainsOS first-boot cloud-init sequence..."

# ------------------------------------------------------------------------------
# 1. AWS EC2 IMDSv2 Metadata Query
# ------------------------------------------------------------------------------
IMDS_TOKEN=""
INSTANCE_ID=""
PUBLIC_HOSTNAME=""
LOCAL_IPV4=""
PUBLIC_IPV4=""
AWS_REGION_DETECTED=""

imds_get() {
  curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
    "http://169.254.169.254/latest/meta-data/$1" --connect-timeout 2 --max-time 3 2>/dev/null || true
}

if [ "${SKIP_IMDS}" != true ] && command -v curl >/dev/null 2>&1; then
  log_info "Querying instance metadata via token-based IMDSv2..."
  IMDS_TOKEN="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
    --connect-timeout 2 --max-time 3 2>/dev/null || true)"
fi

if [ -n "${IMDS_TOKEN}" ]; then
  log_success "Acquired IMDSv2 session token from AWS EC2 metadata service."
  INSTANCE_ID="$(imds_get instance-id)"
  PUBLIC_HOSTNAME="$(imds_get public-hostname)"
  LOCAL_IPV4="$(imds_get local-ipv4)"
  PUBLIC_IPV4="$(imds_get public-ipv4)"
  AWS_REGION_DETECTED="$(imds_get placement/region)"
  USER_DATA="$(curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
    "http://169.254.169.254/latest/user-data" --connect-timeout 2 --max-time 3 2>/dev/null || true)"
else
  log_info "IMDSv2 not available (baremetal, offline, local virtualization or --skip-imds)."
  USER_DATA=""
fi

# Test hook / non-EC2 hosts: user-data supplied from a local file
if [ -n "${BRAINSOS_FIRSTBOOT_USER_DATA_FILE:-}" ] && [ -f "${BRAINSOS_FIRSTBOOT_USER_DATA_FILE}" ]; then
  USER_DATA="$(cat "${BRAINSOS_FIRSTBOOT_USER_DATA_FILE}")"
fi

# ------------------------------------------------------------------------------
# 1b. Optional bring-your-own-domain settings from EC2 user-data (#323)
#     Only these KEY=VALUE lines are honoured; everything else (cloud-config,
#     scripts) is ignored. Example user-data:
#       BRAINSOS_DOMAIN=brainsos.example.com
#       ACME_EMAIL=ops@example.com
#       BRAINSOS_TLS_MODE=acme        # or route53
# ------------------------------------------------------------------------------
strip_value() { local v="${1%%#*}"; printf '%s' "${v}" | tr -d "\"' \r"; }
UD_DOMAIN=""
UD_ACME_EMAIL=""
UD_TLS_MODE=""
if [ -n "${USER_DATA}" ]; then
  while IFS= read -r ud_line; do
    ud_trimmed="${ud_line#"${ud_line%%[![:space:]]*}"}"
    case "${ud_trimmed}" in
      BRAINSOS_DOMAIN=*|BRAINSOS_DOMAIN:*)
        val="${ud_trimmed#BRAINSOS_DOMAIN[=:]}"
        UD_DOMAIN="$(strip_value "${val}" | tr '[:upper:]' '[:lower:]')"
        ;;
      domain:*)
        val="${ud_trimmed#domain:}"
        UD_DOMAIN="$(strip_value "${val}" | tr '[:upper:]' '[:lower:]')"
        ;;
      ACME_EMAIL=*|ACME_EMAIL:*)
        val="${ud_trimmed#ACME_EMAIL[=:]}"
        UD_ACME_EMAIL="$(strip_value "${val}")"
        ;;
      email:*)
        val="${ud_trimmed#email:}"
        UD_ACME_EMAIL="$(strip_value "${val}")"
        ;;
      BRAINSOS_TLS_MODE=*|BRAINSOS_TLS_MODE:*)
        val="${ud_trimmed#BRAINSOS_TLS_MODE[=:]}"
        UD_TLS_MODE="$(strip_value "${val}" | tr '[:upper:]' '[:lower:]')"
        ;;
      tls_mode:*)
        val="${ud_trimmed#tls_mode:}"
        UD_TLS_MODE="$(strip_value "${val}" | tr '[:upper:]' '[:lower:]')"
        ;;
    esac
  done <<< "${USER_DATA}"
fi

is_fqdn() { [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]]; }
is_ipv4() { [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; }

# Fallback values if not on AWS EC2
if [ -z "${INSTANCE_ID}" ]; then
  HOST_HASH="$(hostname 2>/dev/null | tr -cd 'a-zA-Z0-9' | cut -c1-12 || echo "local")"
  INSTANCE_ID="i-appliance-${HOST_HASH:-local}"
fi

if [ -z "${PUBLIC_HOSTNAME}" ]; then
  if [ -n "${PUBLIC_IPV4}" ]; then
    PUBLIC_HOSTNAME="${PUBLIC_IPV4}"
  else
    PUBLIC_HOSTNAME="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo "appliance.local")"
  fi
fi

APPLIANCE_REGION="${AWS_REGION_DETECTED:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"

# Primary hostname: operator domain from user-data, else EC2 public DNS / IP
APPLIANCE_DOMAIN="${PUBLIC_HOSTNAME}"
if [ -n "${UD_DOMAIN}" ]; then
  if is_fqdn "${UD_DOMAIN}"; then
    APPLIANCE_DOMAIN="${UD_DOMAIN}"
  else
    log_warn "Ignoring invalid BRAINSOS_DOMAIN in user-data: '${UD_DOMAIN}'"
  fi
fi

# TLS mode: internal CA unless a complete BYOD request was supplied
TLS_MODE="internal"
ACME_EMAIL_VALUE=""
case "${UD_TLS_MODE}" in
  ""|internal) ;;
  acme|route53)
    if [ "${APPLIANCE_DOMAIN}" != "${UD_DOMAIN}" ] || [ -z "${UD_DOMAIN}" ]; then
      log_warn "BRAINSOS_TLS_MODE=${UD_TLS_MODE} requires a valid BRAINSOS_DOMAIN in user-data; using internal CA."
    elif [[ ! "${UD_ACME_EMAIL}" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
      log_warn "BRAINSOS_TLS_MODE=${UD_TLS_MODE} requires a valid ACME_EMAIL in user-data; using internal CA."
    else
      TLS_MODE="${UD_TLS_MODE}"
      ACME_EMAIL_VALUE="${UD_ACME_EMAIL}"
    fi
    ;;
  *)
    log_warn "Unknown BRAINSOS_TLS_MODE '${UD_TLS_MODE}' in user-data; using internal CA."
    ;;
esac

# Bare-IP site addresses (internal CA), excluding the primary hostname itself
IP_SITES=""
for ip in "${PUBLIC_IPV4}" "${LOCAL_IPV4}"; do
  if [ -n "${ip}" ] && is_ipv4 "${ip}" && [ "${ip}" != "${APPLIANCE_DOMAIN}" ]; then
    case " ${IP_SITES} " in *" ${ip} "*) ;; *) IP_SITES="${IP_SITES:+${IP_SITES} }${ip}" ;; esac
  fi
done
[ -z "${IP_SITES}" ] && IP_SITES="127.0.0.1"

log_info "Instance ID:     ${INSTANCE_ID}"
log_info "Public Hostname: ${PUBLIC_HOSTNAME}"
log_info "Primary Domain:  ${APPLIANCE_DOMAIN}"
log_info "TLS Mode:        ${TLS_MODE}"
log_info "IP Sites:        ${IP_SITES}"
log_info "Local IPv4:      ${LOCAL_IPV4:-unknown}"
log_info "AWS Region:      ${APPLIANCE_REGION}"

case "${APPLIANCE_REGION}" in
  us-*) ;;
  *)
    log_warn "Region ${APPLIANCE_REGION} is outside the US: config/litellm/config.bedrock.yaml uses 'us.' cross-region"
    log_warn "inference profiles. Adjust model IDs (eu./apac./global.) per 'aws bedrock list-inference-profiles'."
    ;;
esac

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would run: ${GENERATE_ENV} --non-interactive --domain ${APPLIANCE_DOMAIN} --data-dir ${REPO_ROOT}/data --force-passwords --no-rebuild"
  log_info "[DRY-RUN] Would write appliance overrides to ${TARGET_ENV}:"
  log_info "[DRY-RUN] BRAINSOS_ADMIN_PASSWORD=${INSTANCE_ID}"
  log_info "[DRY-RUN] BRAINSOS_DOMAIN=${APPLIANCE_DOMAIN}"
  log_info "[DRY-RUN] CADDYFILE=Caddyfile.appliance BRAINSOS_TLS_MODE=${TLS_MODE} BRAINSOS_IP_SITES=${IP_SITES}"
  if [ -n "${ACME_EMAIL_VALUE}" ]; then
    log_info "[DRY-RUN] ACME_EMAIL=${ACME_EMAIL_VALUE}"
  fi
  log_info "[DRY-RUN] COMPOSE_FILE=${REPO_ROOT}/docker-compose.yml:${REPO_ROOT}/docker/compose/compose.appliance.yml"
  log_info "[DRY-RUN] LITELLM_CONFIG=${REPO_ROOT}/config/litellm/config.bedrock.yaml"
  log_info "[DRY-RUN] Would run: ${REPO_ROOT}/scripts/control/bootstrap-env.sh --skip-images --skip-portal --skip-models"
  log_info "[DRY-RUN] Would touch ${INIT_FLAG}"
  exit 0
fi

# ------------------------------------------------------------------------------
# 2. Canonical Secret Generation (generate-env.sh is the single source of truth)
# ------------------------------------------------------------------------------
if [ -f "${TARGET_ENV}" ]; then
  log_info "Existing .env detected; preserving configuration (no secret regeneration)."
else
  if [ ! -x "${GENERATE_ENV}" ]; then
    log_error "Canonical environment generator not found or not executable: ${GENERATE_ENV}"
    exit 1
  fi
  log_info "Generating unique per-instance secrets via scripts/control/generate-env.sh..."
  "${GENERATE_ENV}" --non-interactive \
    --domain "${APPLIANCE_DOMAIN}" \
    --data-dir "${REPO_ROOT}/data" \
    --force-passwords \
    --no-rebuild </dev/null

  # --------------------------------------------------------------------------
  # 3. Appliance Overrides
  # --------------------------------------------------------------------------
  gen_secret() { python3 -c "import secrets; print(secrets.token_hex(${1:-20}))"; }

  APPLIANCE_OVERRIDES=(
    "BRAINSOS_APPLIANCE=true"
    "BRAINSOS_STAGE=aws"
    # Operator login (Authentik admin/akadmin/operator) - AWS Marketplace convention, rotate at first login
    "BRAINSOS_ADMIN_PASSWORD=${INSTANCE_ID}"
    "AUTHENTIK_BOOTSTRAP_PASSWORD=${INSTANCE_ID}"
    # Independent service credentials (never derived from the instance-id)
    "CODE_SERVER_PASSWORD=$(gen_secret 16)"
    "TOOL_EGRESS_WEB_PASSWORD=$(gen_secret 16)"
    "ADMIN_MAIL_PASSWORD=$(gen_secret 16)"
    "OPERATOR_MAIL_PASSWORD=$(gen_secret 16)"
    "LANGFUSE_INIT_USER_PASSWORD=$(gen_secret 16)"
    # Secrets with hardcoded compose fallbacks that are not in .env.example
    "CLICKHOUSE_PASSWORD=$(gen_secret 20)"
    "AUTH_LITELLM_CLIENT_SECRET=$(gen_secret 32)"
    "AUTH_LANGFUSE_CLIENT_SECRET=$(gen_secret 32)"
    # Appliance topology: every 'docker compose' call inherits the lockdown overlay
    "COMPOSE_FILE=${REPO_ROOT}/docker-compose.yml:${REPO_ROOT}/docker/compose/compose.appliance.yml"
    # Ambient-IAM Bedrock catalog; no host Ollama on the appliance
    "LITELLM_CONFIG=${REPO_ROOT}/config/litellm/config.bedrock.yaml"
    "BRAINSOS_CORE_MODEL=brainsos-core"
    "OLLAMA_ENABLED=false"
    "AWS_REGION=${APPLIANCE_REGION}"
    "AWS_DEFAULT_REGION=${APPLIANCE_REGION}"
    # Ingress (#323): appliance Caddyfile, self-signed by default, BYOD via user-data or set-domain.sh
    "BRAINSOS_DOMAIN=${APPLIANCE_DOMAIN}"
    "CADDYFILE=Caddyfile.appliance"
    "BRAINSOS_TLS_MODE=${TLS_MODE}"
    "BRAINSOS_IP_SITES=${IP_SITES}"
    "NEXTAUTH_URL=https://langfuse.${APPLIANCE_DOMAIN}"
  )
  if [ -n "${ACME_EMAIL_VALUE}" ]; then
    APPLIANCE_OVERRIDES+=("ACME_EMAIL=${ACME_EMAIL_VALUE}")
  fi

  "${REPO_ROOT}/scripts/control/env-upsert.sh" --file "${TARGET_ENV}" \
    --section "Appliance Overrides (written by packages/brainsOS-appliance/scripts/firstboot.sh)" \
    "${APPLIANCE_OVERRIDES[@]}"
  chmod 600 "${TARGET_ENV}"
  log_success "Wrote appliance .env with unique secrets and strict 0600 permissions."
fi

# ------------------------------------------------------------------------------
# 4. Per-Instance Data Tree & Python Environment
#    bootstrap-env.sh preserves the .env written above, scaffolds data/ and
#    seeds default settings/agents/runners/skills. Failure is fatal so that
#    brainsos.service (Requires=brainsos-firstboot.service) never starts on a
#    half-provisioned host.
# ------------------------------------------------------------------------------
BOOTSTRAP_ENV="${REPO_ROOT}/scripts/control/bootstrap-env.sh"
if [ "${BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP:-false}" != true ]; then
  if [ ! -x "${BOOTSTRAP_ENV}" ]; then
    log_error "Bootstrap script not found or not executable: ${BOOTSTRAP_ENV}"
    exit 1
  fi
  log_info "Seeding per-instance data tree via scripts/control/bootstrap-env.sh..."
  "${BOOTSTRAP_ENV}" --skip-images --skip-portal --skip-models </dev/null
fi

# ------------------------------------------------------------------------------
# 5. Portal Bundle for the Real Hostname (node_modules cached in the AMI)
# ------------------------------------------------------------------------------
if [ "${SKIP_PORTAL}" != true ] && [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
  log_info "Rebuilding portal bundle for ${PUBLIC_HOSTNAME}..."
  if ! "${REPO_ROOT}/scripts/setup/setup-portal.sh"; then
    log_warn "Portal rebuild failed; the pre-built bundle from the AMI remains in place."
  fi
fi

# ------------------------------------------------------------------------------
# 6. Mark Initialized & Finalize
# ------------------------------------------------------------------------------
date -u +"%Y-%m-%dT%H:%M:%SZ" > "${INIT_FLAG}"
chmod 644 "${INIT_FLAG}"
log_success "Appliance initialized successfully."

# Disable firstboot service so it never runs again (ConditionPathExists also guards it)
if [ "${SKIP_IMDS}" != true ] && command -v systemctl >/dev/null 2>&1; then
  systemctl disable brainsos-firstboot.service 2>/dev/null || true
fi

if [ "${TLS_MODE}" = "internal" ]; then
  TLS_NOTE="self-signed (Caddy internal CA)"
else
  TLS_NOTE="public ACME (${TLS_MODE}); falls back to self-signed until issued"
fi

# Login instructions to console/journal. The initial password is the instance-id,
# which is only visible to principals with ec2:DescribeInstances in the owning account.
cat <<BANNER

================================================================================
 brainsOS Appliance Initialization Complete
--------------------------------------------------------------------------------
 URL:               https://${APPLIANCE_DOMAIN}/
 Certificate:       ${TLS_NOTE}
 Root CA download:  https://${APPLIANCE_DOMAIN}/system/ca.crt  (after sign-in)
 Operator Username: admin
 Initial Password:  your EC2 instance ID

 ACTION REQUIRED: change the initial password at first login.
 Use your own domain (public certificate):
   sudo /opt/brainsos/scripts/control/set-domain.sh --domain <fqdn> --email <addr>
 Inbound SSH (port 22) is disabled; use AWS Systems Manager Session Manager.
================================================================================

BANNER
