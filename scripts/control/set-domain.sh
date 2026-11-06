#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Bring-Your-Own-Domain (BYOD) & TLS Mode Configuration
# Ticket #323 (Epic #309 / #321)
#
# Configures the appliance primary domain and switches TLS modes:
#   - Public ACME (TLS-ALPN-01 on 443 / HTTP-01 on 80)
#   - AWS Route 53 DNS-01 ACME (ambient EC2 instance profile, zero static keys)
#   - Internal Private CA (self-signed, default offline / private mode)
#
# Usage:
#   ./scripts/control/set-domain.sh --domain <fqdn> --email <addr> [--dns route53]
#   ./scripts/control/set-domain.sh --domain <fqdn> --internal
#   ./scripts/control/set-domain.sh --dry-run [OPTIONS]
# ==============================================================================

set -euo pipefail

# Visual styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
ENV_UPSERT="${REPO_ROOT}/scripts/control/env-upsert.sh"

DOMAIN=""
URL_INPUT=""
LOCAL_DOMAIN=""
ADMIN_USERNAME=""
ADMIN_PASSWORD=""
EMAIL=""
DNS_PROVIDER=""
INTERNAL_MODE=false
SKIP_DNS_CHECK=false
MARK_WIZARD_COMPLETED=false
FORCE=false
DRY_RUN=false

normalize_url_host() {
  local raw="$1"
  raw="${raw#http://}"
  raw="${raw#https://}"
  raw="${raw%%/*}"
  raw="${raw%%:*}"
  printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | tr -d ' '
}

usage() {
  cat <<EOF
${BOLD}brainsOS Bring-Your-Own-Domain (BYOD), Local Identity & TLS Configuration${NC}

Usage:
  ./scripts/control/set-domain.sh [OPTIONS]

Options:
  --domain FQDN           External web URL / domain (alias for --url)
  --url URL               External web access URL or hostname (BRAINSOS_URL, e.g. https://ec2-...amazonaws.com)
  --local-domain FQDN     Coherent appliance unit FQDN & local mail domain (BRAINSOS_LOCAL_DOMAIN, e.g. jsm.cloud.aws.brainsos.ai)
  --admin-username USER   Administrator username (BRAINSOS_ADMIN_USERNAME, default: admin)
  --admin-password PASS   Administrator password (or pass via BRAINSOS_NEW_ADMIN_PASSWORD env var)
  --email EMAIL           ACME contact email address for Let's Encrypt / ZeroSSL
  --dns PROVIDER          DNS-01 ACME challenge provider (e.g. 'route53')
  --internal              Use Caddy's internal private CA (self-signed)
  --mark-wizard-completed Record completion of the First-Boot Setup Wizard (.brainsos-wizard-completed)
  --skip-dns-check        Skip DNS resolution pre-flight check
  --force                 Proceed even if DNS does not resolve to this instance
  --dry-run               Simulate configuration changes without writing .env
  -h, --help              Show this help message

Examples:
  # First-Boot Setup (keep AWS URL with internal CA, set local domain & admin credentials):
  ./scripts/control/set-domain.sh --local-domain jsm.cloud.aws.brainsos.ai --admin-username jsm --internal --mark-wizard-completed

  # Public ACME (TLS-ALPN-01 / HTTP-01):
  ./scripts/control/set-domain.sh --domain brainsos.myorg.com --local-domain jsm.myorg.com --email ops@myorg.com

  # Route 53 DNS-01 (wildcard certs via ambient EC2 IAM role):
  ./scripts/control/set-domain.sh --domain brainsos.myorg.com --email ops@myorg.com --dns route53

  # Revert to Caddy internal self-signed CA:
  ./scripts/control/set-domain.sh --domain brainsos.local --internal
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain)
      DOMAIN="${2:-}"
      shift 2
      ;;
    --url)
      URL_INPUT="${2:-}"
      shift 2
      ;;
    --local-domain)
      LOCAL_DOMAIN="${2:-}"
      shift 2
      ;;
    --admin-username)
      ADMIN_USERNAME="${2:-}"
      shift 2
      ;;
    --admin-password)
      ADMIN_PASSWORD="${2:-}"
      shift 2
      ;;
    --email)
      EMAIL="${2:-}"
      shift 2
      ;;
    --dns)
      DNS_PROVIDER="${2:-}"
      shift 2
      ;;
    --internal)
      INTERNAL_MODE=true
      shift
      ;;
    --mark-wizard-completed)
      MARK_WIZARD_COMPLETED=true
      shift
      ;;
    --skip-dns-check)
      SKIP_DNS_CHECK=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [ -z "${ADMIN_PASSWORD}" ] && [ -n "${BRAINSOS_NEW_ADMIN_PASSWORD:-}" ]; then
  ADMIN_PASSWORD="${BRAINSOS_NEW_ADMIN_PASSWORD}"
fi

if [ -n "${URL_INPUT}" ] && [ -z "${DOMAIN}" ]; then
  DOMAIN="${URL_INPUT}"
fi

if [ -z "${DOMAIN}" ]; then
  if [ "${INTERNAL_MODE}" = true ] || [ -n "${LOCAL_DOMAIN}" ] || [ -n "${ADMIN_USERNAME}" ] || [ -n "${ADMIN_PASSWORD}" ]; then
    if [ -f "${ENV_FILE}" ]; then
      CURRENT_URL="$(grep -E '^BRAINSOS_URL=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
      CURRENT_DOMAIN="$(grep -E '^BRAINSOS_DOMAIN=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
      DOMAIN="${CURRENT_URL:-${CURRENT_DOMAIN:-localhost}}"
    else
      DOMAIN="localhost"
    fi
    if [ -z "${DNS_PROVIDER}" ] && [ -z "${EMAIL}" ]; then
      INTERNAL_MODE=true
    fi
  else
    log_error "Missing required option: --domain <fqdn> (or --url / --local-domain)"
    usage
    exit 1
  fi
fi

DOMAIN="$(normalize_url_host "${DOMAIN}")"

if [ -n "${LOCAL_DOMAIN}" ]; then
  LOCAL_DOMAIN="$(normalize_url_host "${LOCAL_DOMAIN}")"
  if ! python3 -c "import re, sys; sys.exit(0 if re.match(r'^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$', sys.argv[1]) else 1)" "${LOCAL_DOMAIN}"; then
    log_error "Invalid local domain FQDN: '${LOCAL_DOMAIN}'"
    exit 1
  fi
fi

if [ -n "${ADMIN_USERNAME}" ]; then
  ADMIN_USERNAME="$(printf '%s' "${ADMIN_USERNAME}" | tr -d ' ')"
  if ! python3 -c "import re, sys; sys.exit(0 if re.match(r'^[a-zA-Z0-9._-]{2,64}$', sys.argv[1]) else 1)" "${ADMIN_USERNAME}"; then
    log_error "Invalid admin username: '${ADMIN_USERNAME}'"
    exit 1
  fi
fi

# Validate domain syntax
if ! python3 -c "import re, sys; sys.exit(0 if re.match(r'^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$', sys.argv[1]) else 1)" "${DOMAIN}"; then
  if [ "${DOMAIN}" != "localhost" ] && [ "${INTERNAL_MODE}" != true ]; then
    log_error "Invalid fully qualified domain name: '${DOMAIN}'"
    exit 1
  fi
fi

# Determine target TLS mode
if [ "${INTERNAL_MODE}" = true ]; then
  TLS_MODE="internal"
elif [ "${DNS_PROVIDER}" = "route53" ]; then
  TLS_MODE="route53"
else
  TLS_MODE="acme"
fi

if [ "${TLS_MODE}" != "internal" ]; then
  if [ -z "${EMAIL}" ]; then
    log_error "ACME modes (--email) require a valid operator email address for certificate recovery."
    exit 1
  fi
  if ! python3 -c "import re, sys; sys.exit(0 if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', sys.argv[1]) else 1)" "${EMAIL}"; then
    log_error "Invalid ACME email address: '${EMAIL}'"
    exit 1
  fi
fi

# AWS Route 53 validation
if [ "${TLS_MODE}" = "route53" ]; then
  log_info "Validating AWS Route 53 IAM context..."
  if command -v aws >/dev/null 2>&1; then
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
      log_warn "AWS STS caller identity check failed. Route 53 DNS-01 requires valid AWS credentials or EC2 instance profile."
      if [ "${FORCE}" != true ]; then
        log_error "Aborting. Ensure an instance role with route53 permissions is attached or pass --force."
        exit 1
      fi
    else
      log_success "AWS IAM identity verified for Route 53 DNS-01."
    fi
  else
    log_warn "AWS CLI not found on host; Route 53 validation skipped."
  fi
fi

# DNS pre-flight verification
if [ "${TLS_MODE}" = "acme" ] && [ "${SKIP_DNS_CHECK}" != true ]; then
  log_info "Performing DNS pre-flight resolution check for ${DOMAIN}..."
  RESOLVED_IP="$(python3 -c "import socket, sys
try:
    print(socket.gethostbyname(sys.argv[1]))
except Exception:
    sys.exit(1)" "${DOMAIN}" 2>/dev/null || true)"

  if [ -z "${RESOLVED_IP}" ]; then
    log_warn "Domain '${DOMAIN}' does not resolve to any IPv4 address."
    log_warn "Let's Encrypt / ZeroSSL public issuance requires DNS pointing to this instance."
    if [ "${FORCE}" != true ] && [ "${DRY_RUN}" != true ]; then
      log_error "Please configure DNS A record before requesting ACME certificates, or pass --force."
      exit 1
    fi
  else
    log_info "Domain '${DOMAIN}' resolves to: ${RESOLVED_IP}"

    # Query local/public IP from IMDSv2 or network
    DETECTED_PUBLIC_IP=""
    IMDS_TOKEN="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 60" \
      --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    if [ -n "${IMDS_TOKEN}" ]; then
      DETECTED_PUBLIC_IP="$(curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
        "http://169.254.169.254/latest/meta-data/public-ipv4" --connect-timeout 1 --max-time 2 2>/dev/null || true)"
    fi

    if [ -n "${DETECTED_PUBLIC_IP}" ]; then
      if [ "${RESOLVED_IP}" = "${DETECTED_PUBLIC_IP}" ]; then
        log_success "DNS verified: ${DOMAIN} points directly to this EC2 instance (${DETECTED_PUBLIC_IP})."
      else
        log_warn "Domain ${DOMAIN} resolves to ${RESOLVED_IP}, but EC2 public IP is ${DETECTED_PUBLIC_IP}."
        log_warn "If this instance is behind a load balancer or proxy, this may be expected."
        if [ "${FORCE}" != true ] && [ "${DRY_RUN}" != true ]; then
          log_warn "Continuing with internal CA fallback enabled (Caddy will not break on issuance failure)."
        fi
      fi
    fi
  fi
fi

log_info "Configuring brainsOS Domain, Identity & Ingress:"
log_info "  External URL: ${DOMAIN}"
[ -n "${LOCAL_DOMAIN}" ] && log_info "  Local Domain: ${LOCAL_DOMAIN}"
[ -n "${ADMIN_USERNAME}" ] && log_info "  Admin User:   ${ADMIN_USERNAME}"
[ -n "${ADMIN_PASSWORD}" ] && log_info "  Admin Pass:   [REDACTED - will rotate]"
log_info "  TLS Mode:     ${TLS_MODE}"
[ -n "${EMAIL}" ] && log_info "  ACME Email:   ${EMAIL}"
[ -n "${DNS_PROVIDER}" ] && log_info "  DNS Provider: ${DNS_PROVIDER}"

ENV_CHANGES=(
  "BRAINSOS_URL=${DOMAIN}"
  "BRAINSOS_DOMAIN=${DOMAIN}"
  "AUTHENTIK_COOKIE_DOMAIN="
  "BRAINSOS_TLS_MODE=${TLS_MODE}"
  "NEXTAUTH_URL=https://${DOMAIN}"
)

EFFECTIVE_LOCAL_DOM=""
if [ -f "${ENV_FILE}" ]; then
  EFFECTIVE_LOCAL_DOM="$(grep -E '^BRAINSOS_LOCAL_DOMAIN=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
  if [ -z "${EFFECTIVE_LOCAL_DOM}" ]; then
    EFFECTIVE_LOCAL_DOM="$(grep -E '^BRAINSOS_MAIL_DOMAIN=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
  fi
fi

if [ -n "${LOCAL_DOMAIN}" ]; then
  EFFECTIVE_LOCAL_DOM="${LOCAL_DOMAIN}"
  ENV_CHANGES+=(
    "BRAINSOS_LOCAL_DOMAIN=${LOCAL_DOMAIN}"
    "BRAINSOS_MAIL_DOMAIN=${LOCAL_DOMAIN}"
  )
fi
[ -z "${EFFECTIVE_LOCAL_DOM}" ] && EFFECTIVE_LOCAL_DOM="local.brainsos.ai"

EFFECTIVE_ADMIN_USER=""
if [ -f "${ENV_FILE}" ]; then
  EFFECTIVE_ADMIN_USER="$(grep -E '^BRAINSOS_ADMIN_USERNAME=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
fi
if [ -n "${ADMIN_USERNAME}" ]; then
  EFFECTIVE_ADMIN_USER="${ADMIN_USERNAME}"
  ENV_CHANGES+=("BRAINSOS_ADMIN_USERNAME=${ADMIN_USERNAME}")
fi
[ -z "${EFFECTIVE_ADMIN_USER}" ] && EFFECTIVE_ADMIN_USER="admin"

if [ -n "${LOCAL_DOMAIN}" ] || [ -n "${ADMIN_USERNAME}" ]; then
  TARGET_ADMIN_EMAIL="${EFFECTIVE_ADMIN_USER}@${EFFECTIVE_LOCAL_DOM}"
  if [[ "${TARGET_ADMIN_EMAIL}" == *.local ]]; then
    TARGET_ADMIN_EMAIL="${EFFECTIVE_ADMIN_USER}@brainsos.ai"
  fi
  ENV_CHANGES+=(
    "BRAINSOS_ADMIN_EMAIL=${TARGET_ADMIN_EMAIL}"
    "AUTHENTIK_BOOTSTRAP_EMAIL=${TARGET_ADMIN_EMAIL}"
    "LANGFUSE_INIT_USER_EMAIL=${TARGET_ADMIN_EMAIL}"
  )
fi

if [ -n "${ADMIN_PASSWORD}" ]; then
  ENV_CHANGES+=(
    "BRAINSOS_ADMIN_PASSWORD=${ADMIN_PASSWORD}"
    "AUTHENTIK_BOOTSTRAP_PASSWORD=${ADMIN_PASSWORD}"
    "ADMIN_MAIL_PASSWORD=${ADMIN_PASSWORD}"
    "OPERATOR_MAIL_PASSWORD=${ADMIN_PASSWORD}"
    "LANGFUSE_INIT_USER_PASSWORD=${ADMIN_PASSWORD}"
  )
fi

if [ "${TLS_MODE}" = "route53" ]; then
  ENV_CHANGES+=("ACME_DNS_PROVIDER=route53")
  ENV_CHANGES+=("ACME_EMAIL=${EMAIL}")
elif [ "${TLS_MODE}" = "acme" ]; then
  ENV_CHANGES+=("ACME_DNS_PROVIDER=")
  ENV_CHANGES+=("ACME_EMAIL=${EMAIL}")
else
  ENV_CHANGES+=("ACME_DNS_PROVIDER=")
fi

if [ "${MARK_WIZARD_COMPLETED}" = true ]; then
  ENV_CHANGES+=("BRAINSOS_WIZARD_COMPLETED=true")
fi

CLOUD_CFG_DIR="${BRAINSOS_CLOUD_CFG_DIR:-/etc/cloud/cloud.cfg.d}"
HOSTS_FILE="${BRAINSOS_HOSTS_FILE:-/etc/hosts}"
WIZARD_FLAG="${REPO_ROOT}/.brainsos-wizard-completed"

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would apply the following environment updates to ${ENV_FILE}:"
  for line in "${ENV_CHANGES[@]}"; do
    case "${line}" in
      *PASSWORD=*)
        echo -e "  ${YELLOW}${line%%=*}=[REDACTED]${NC}"
        ;;
      *)
        echo -e "  ${YELLOW}${line}${NC}"
        ;;
    esac
  done
  if [ -n "${LOCAL_DOMAIN}" ]; then
    SHORT_HOST="${LOCAL_DOMAIN%%.*}"
    log_info "[DRY-RUN] Would set OS hostname via hostnamectl set-hostname ${LOCAL_DOMAIN}"
    log_info "[DRY-RUN] Would update ${HOSTS_FILE} with: 127.0.1.1 ${LOCAL_DOMAIN} ${SHORT_HOST}"
    log_info "[DRY-RUN] Would write ${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg (preserve_hostname: true)"
  fi
  if [ "${MARK_WIZARD_COMPLETED}" = true ]; then
    log_info "[DRY-RUN] Would write ${WIZARD_FLAG}"
  fi
  log_info "[DRY-RUN] Would execute: ${REPO_ROOT}/scripts/control/reload-env.sh --no-urls"
  log_info "[DRY-RUN] Would execute: ${REPO_ROOT}/scripts/setup/setup-portal.sh"
  log_success "[DRY-RUN] Domain configuration simulation complete."
  exit 0
fi

if [ ! -f "${ENV_FILE}" ]; then
  log_error "Environment file not found: ${ENV_FILE}. Run make env or make setup first."
  exit 1
fi

log_info "Updating .env configuration..."
"${ENV_UPSERT}" --file "${ENV_FILE}" \
  --section "Domain & Ingress Settings (configured via set-domain.sh)" \
  "${ENV_CHANGES[@]}"
log_success "Updated ${ENV_FILE}."

# Apply reboot-persistent OS hostname & cloud-init preserve_hostname (#332)
if [ -n "${LOCAL_DOMAIN}" ]; then
  SHORT_HOST="${LOCAL_DOMAIN%%.*}"
  log_info "Configuring reboot-persistent OS hostname: ${LOCAL_DOMAIN} (short: ${SHORT_HOST})..."
  if command -v hostnamectl >/dev/null 2>&1; then
    hostnamectl set-hostname "${LOCAL_DOMAIN}" 2>/dev/null || sudo -n hostnamectl set-hostname "${LOCAL_DOMAIN}" 2>/dev/null || hostname "${LOCAL_DOMAIN}" 2>/dev/null || log_warn "Could not set live hostname via hostnamectl (insufficient privileges or container environment)."
  fi

  # Write /etc/cloud/cloud.cfg.d/99-brainsos-hostname.cfg (preserve_hostname: true)
  if [ -d "${CLOUD_CFG_DIR}" ] || [ -n "${BRAINSOS_CLOUD_CFG_DIR:-}" ]; then
    mkdir -p "${CLOUD_CFG_DIR}" 2>/dev/null || sudo -n mkdir -p "${CLOUD_CFG_DIR}" 2>/dev/null || true
    if [ -w "${CLOUD_CFG_DIR}" ]; then
      printf "# Managed by brainsOS set-domain.sh (#332)\npreserve_hostname: true\n" > "${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg"
      log_success "Wrote ${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg (preserve_hostname: true)."
    elif command -v sudo >/dev/null 2>&1; then
      printf "# Managed by brainsOS set-domain.sh (#332)\npreserve_hostname: true\n" | sudo -n tee "${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg" >/dev/null 2>&1 && \
        log_success "Wrote ${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg (preserve_hostname: true)." || \
        log_warn "Could not write ${CLOUD_CFG_DIR}/99-brainsos-hostname.cfg."
    fi
  fi

  # Update /etc/hosts with 127.0.1.1 <fqdn> <short-host>
  if [ -f "${HOSTS_FILE}" ]; then
    python3 - "${HOSTS_FILE}" "${LOCAL_DOMAIN}" "${SHORT_HOST}" <<'PYEOF' 2>/dev/null || true
import os, sys
hosts_path, fqdn, short_host = sys.argv[1], sys.argv[2], sys.argv[3]
entry = f"127.0.1.1\t{fqdn} {short_host}"
try:
    with open(hosts_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    new_lines = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("127.0.1.1"):
            if not replaced:
                new_lines.append(entry)
                replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(entry)
    with open(hosts_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
except PermissionError:
    pass
PYEOF
    if ! grep -q "${LOCAL_DOMAIN}" "${HOSTS_FILE}" 2>/dev/null && command -v sudo >/dev/null 2>&1; then
      sudo -n python3 - "${HOSTS_FILE}" "${LOCAL_DOMAIN}" "${SHORT_HOST}" <<'PYEOF' 2>/dev/null || true
import sys
hosts_path, fqdn, short_host = sys.argv[1], sys.argv[2], sys.argv[3]
entry = f"127.0.1.1\t{fqdn} {short_host}"
with open(hosts_path, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()
new_lines = [l for l in lines if not l.strip().startswith("127.0.1.1")]
new_lines.append(entry)
with open(hosts_path, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines) + "\n")
PYEOF
    fi
    if grep -q "${LOCAL_DOMAIN}" "${HOSTS_FILE}" 2>/dev/null; then
      log_success "Updated ${HOSTS_FILE} with 127.0.1.1 ${LOCAL_DOMAIN} ${SHORT_HOST}."
    fi
  fi
fi

# Rebuild portal bundle for the new hostname so client-side API routing matches
if [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
  log_info "Rebuilding portal bundle for ${DOMAIN}..."
  "${REPO_ROOT}/scripts/setup/setup-portal.sh" || log_warn "Portal build encountered a warning."
fi

# Reload environment and restart Caddy ingress
log_info "Reloading Caddy ingress gateway & synchronizing credentials..."
"${REPO_ROOT}/scripts/control/reload-env.sh" --no-urls

if [ "${MARK_WIZARD_COMPLETED}" = true ]; then
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "${WIZARD_FLAG}"
  chmod 644 "${WIZARD_FLAG}" 2>/dev/null || true
  log_success "Marked First-Boot Setup Wizard completed (${WIZARD_FLAG})."
fi

# Surface current URLs and TLS certificate status
echo ""
"${REPO_ROOT}/scripts/control/show-urls.sh" --portal

cat <<SUMMARY

================================================================================
 ${GREEN}${BOLD}Domain & Appliance Identity Configuration Complete${NC}
--------------------------------------------------------------------------------
 External URL: https://${DOMAIN}/
 Local Domain: ${EFFECTIVE_LOCAL_DOM}
 Admin User:   ${EFFECTIVE_ADMIN_USER} (${EFFECTIVE_ADMIN_USER}@${EFFECTIVE_LOCAL_DOM})
 TLS Mode:     ${TLS_MODE}
 ACME Email:   ${EMAIL:-none}

 Note: If public ACME certificate issuance takes a few moments or fails,
 Caddy will seamlessly continue serving the internal self-signed certificate.
 You can check certificate status anytime with:
   make urls
================================================================================

SUMMARY
