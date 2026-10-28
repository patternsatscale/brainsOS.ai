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
else
  log_info "IMDSv2 not available (baremetal, offline, local virtualization or --skip-imds)."
fi

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

log_info "Instance ID:     ${INSTANCE_ID}"
log_info "Public Hostname: ${PUBLIC_HOSTNAME}"
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
  log_info "[DRY-RUN] Would run: ${GENERATE_ENV} --non-interactive --domain ${PUBLIC_HOSTNAME} --data-dir ${REPO_ROOT}/data --force-passwords --no-rebuild"
  log_info "[DRY-RUN] Would write appliance overrides to ${TARGET_ENV}:"
  log_info "[DRY-RUN] BRAINSOS_ADMIN_PASSWORD=${INSTANCE_ID}"
  log_info "[DRY-RUN] BRAINSOS_DOMAIN=${PUBLIC_HOSTNAME}"
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
    --domain "${PUBLIC_HOSTNAME}" \
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
  )

  OVERRIDE_TMP="$(mktemp)"
  printf '%s\n' "${APPLIANCE_OVERRIDES[@]}" > "${OVERRIDE_TMP}"
  python3 - "${TARGET_ENV}" "${OVERRIDE_TMP}" <<'PYEOF'
import sys

env_path, overrides_path = sys.argv[1], sys.argv[2]
overrides = {}
with open(overrides_path, encoding="utf-8") as fh:
    for raw in fh:
        raw = raw.rstrip("\n")
        if raw and not raw.startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            overrides[key] = value

lines = []
seen = set()
with open(env_path, encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        is_comment = line.startswith("#")
        body = line[1:].lstrip() if is_comment else line
        key = body.split("=", 1)[0].strip() if "=" in body else None
        if key and " " not in key and key in overrides:
            if key not in seen:
                # First occurrence (assignment or commented template line) becomes the override
                lines.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
            if not is_comment:
                continue  # drop later duplicate assignments
        lines.append(line)

missing = [k for k in overrides if k not in seen]
if missing:
    lines.append("")
    lines.append("# ==============================================================================")
    lines.append("# Appliance Overrides (written by packages/brainsOS-appliance/scripts/firstboot.sh)")
    lines.append("# ==============================================================================")
    for key in missing:
        lines.append(f"{key}={overrides[key]}")

with open(env_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
PYEOF
  rm -f "${OVERRIDE_TMP}"
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

# Login instructions to console/journal. The initial password is the instance-id,
# which is only visible to principals with ec2:DescribeInstances in the owning account.
cat <<BANNER

================================================================================
 brainsOS Appliance Initialization Complete
--------------------------------------------------------------------------------
 URL:               https://${PUBLIC_HOSTNAME}/   (self-signed until a domain is configured)
 Operator Username: admin
 Initial Password:  your EC2 instance ID

 ACTION REQUIRED: change the initial password at first login.
 Inbound SSH (port 22) is disabled; use AWS Systems Manager Session Manager.
================================================================================

BANNER
