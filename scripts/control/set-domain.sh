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
EMAIL=""
DNS_PROVIDER=""
INTERNAL_MODE=false
SKIP_DNS_CHECK=false
FORCE=false
DRY_RUN=false

usage() {
  cat <<EOF
${BOLD}brainsOS Bring-Your-Own-Domain (BYOD) & TLS Configuration${NC}

Usage:
  ./scripts/control/set-domain.sh --domain <fqdn> --email <addr> [OPTIONS]

Options:
  --domain FQDN         Fully qualified domain name (e.g. brainsos.example.com)
  --email EMAIL         ACME contact email address for Let's Encrypt / ZeroSSL
  --dns PROVIDER        DNS-01 ACME challenge provider (e.g. 'route53')
  --internal            Use Caddy's internal private CA (self-signed)
  --skip-dns-check      Skip DNS resolution pre-flight check
  --force               Proceed even if DNS does not resolve to this instance
  --dry-run             Simulate configuration changes without writing .env
  -h, --help            Show this help message

Examples:
  # Public ACME (TLS-ALPN-01 / HTTP-01):
  ./scripts/control/set-domain.sh --domain brainsos.myorg.com --email ops@myorg.com

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

if [ -z "${DOMAIN}" ]; then
  if [ "${INTERNAL_MODE}" = true ]; then
    if [ -f "${ENV_FILE}" ]; then
      CURRENT_DOMAIN="$(grep -E '^BRAINSOS_DOMAIN=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)"
      DOMAIN="${CURRENT_DOMAIN:-localhost}"
    else
      DOMAIN="localhost"
    fi
  else
    log_error "Missing required option: --domain <fqdn>"
    usage
    exit 1
  fi
fi

DOMAIN="$(echo "${DOMAIN}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"

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

log_info "Configuring brainsOS Domain & Ingress:"
log_info "  Domain:       ${DOMAIN}"
log_info "  TLS Mode:     ${TLS_MODE}"
[ -n "${EMAIL}" ] && log_info "  ACME Email:   ${EMAIL}"
[ -n "${DNS_PROVIDER}" ] && log_info "  DNS Provider: ${DNS_PROVIDER}"

ENV_CHANGES=(
  "BRAINSOS_DOMAIN=${DOMAIN}"
  "BRAINSOS_TLS_MODE=${TLS_MODE}"
  "NEXTAUTH_URL=https://langfuse.${DOMAIN}"
)

if [ "${TLS_MODE}" = "route53" ]; then
  ENV_CHANGES+=("ACME_DNS_PROVIDER=route53")
  ENV_CHANGES+=("ACME_EMAIL=${EMAIL}")
elif [ "${TLS_MODE}" = "acme" ]; then
  ENV_CHANGES+=("ACME_DNS_PROVIDER=")
  ENV_CHANGES+=("ACME_EMAIL=${EMAIL}")
else
  ENV_CHANGES+=("ACME_DNS_PROVIDER=")
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would apply the following environment updates to ${ENV_FILE}:"
  for line in "${ENV_CHANGES[@]}"; do
    echo -e "  ${YELLOW}${line}${NC}"
  done
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

# Rebuild portal bundle for the new hostname so client-side API routing matches
if [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
  log_info "Rebuilding portal bundle for ${DOMAIN}..."
  "${REPO_ROOT}/scripts/setup/setup-portal.sh" || log_warn "Portal build encountered a warning."
fi

# Reload environment and restart Caddy ingress
log_info "Reloading Caddy ingress gateway..."
"${REPO_ROOT}/scripts/control/reload-env.sh" --no-urls

# Surface current URLs and TLS certificate status
echo ""
"${REPO_ROOT}/scripts/control/show-urls.sh" --portal

cat <<SUMMARY

================================================================================
 ${GREEN}${BOLD}Domain Configuration Complete${NC}
--------------------------------------------------------------------------------
 Primary URL:  https://${DOMAIN}/
 TLS Mode:     ${TLS_MODE}
 ACME Email:   ${EMAIL:-none}

 Note: If public ACME certificate issuance takes a few moments or fails,
 Caddy will seamlessly continue serving the internal self-signed certificate.
 You can check certificate status anytime with:
   make urls
================================================================================

SUMMARY
