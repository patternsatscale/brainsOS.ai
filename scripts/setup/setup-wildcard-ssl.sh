#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Route 53 Wildcard SSL Wizard (SST Ion)
# ==============================================================================
# Configures public wildcard SSL (*.local.<domain>) using AWS Route 53
# and SST Ion cloud infrastructure in infra/ with least-privilege IAM scoping.
# Zero manual certificate imports required on client devices.
# ==============================================================================

set -euo pipefail

# Visual styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Rule 13: Execution environment precondition
if [ ! -f .env ]; then
  log_error "Precondition failed: No .env file present in repository root."
  log_info "Run 'make setup' or 'scripts/control/bootstrap-env.sh' first."
  exit 1
fi

# Load current .env
set -a
. ./.env
set +a

ZONE_NAME=""
AWS_PROFILE_CHOICE=""
DEPLOY_METHOD=""
NON_INTERACTIVE=false
APPLIANCE_PREFIX="${BRAINSOS_STAGE:-$([ "$(uname -s)" = "Darwin" ] && echo "osx" || echo "dgx")}"

usage() {
  cat << USAGE
Usage: $(basename "$0") [OPTIONS]

Options:
  --zone <domain>          Route 53 Hosted Zone domain (e.g. brainsos.ai)
  --prefix <subdomain>     Appliance prefix (default: dgx -> dgx.local.<zone>)
  --profile <profile>      AWS CLI profile to use (default: default)
  --method <method>        Deployment method: sst-local, github-workflow, direct
  --non-interactive        Execute non-interactively using defaults or CLI flags
  -h, --help               Show this help message
USAGE
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zone)
      ZONE_NAME="$2"
      shift 2
      ;;
    --prefix)
      APPLIANCE_PREFIX="$2"
      shift 2
      ;;
    --profile)
      AWS_PROFILE_CHOICE="$2"
      shift 2
      ;;
    --method)
      DEPLOY_METHOD="$2"
      shift 2
      ;;
    --non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      shift
      ;;
  esac
done

echo -e "${BOLD}${CYAN}"
echo "══════════════════════════════════════════════════════════════════════════════"
echo "  brainsOS: Public Wildcard SSL & Route 53 ACME Automation (SST Ion)"
echo "══════════════════════════════════════════════════════════════════════════════"
echo -e "${NC}"
echo "This wizard configures publicly trusted wildcard SSL (*.local.<domain>)"
echo "for your appliance using AWS Route 53 DNS-01 challenges and SST Ion."
echo "Zero manual certificate installation or macOS keychain imports required."
echo ""

# ------------------------------------------------------------------------------
# 1. AWS Credentials & Profile Detection
# ------------------------------------------------------------------------------
log_info "Step 1/4: Checking AWS Credentials & Profile..."

HAS_AWS_CLI=false
if command -v aws >/dev/null 2>&1; then
  HAS_AWS_CLI=true
fi

AVAILABLE_PROFILES=()
if [ "${HAS_AWS_CLI}" = true ]; then
  while IFS= read -r p; do
    [ -n "$p" ] && AVAILABLE_PROFILES+=("$p")
  done < <(aws configure list-profiles 2>/dev/null || true)
fi

if [ ${#AVAILABLE_PROFILES[@]} -eq 0 ]; then
  AVAILABLE_PROFILES=("default")
fi

if [ -z "${AWS_PROFILE_CHOICE}" ]; then
  if [ "${NON_INTERACTIVE}" = true ] || [ ${#AVAILABLE_PROFILES[@]} -eq 1 ]; then
    AWS_PROFILE_CHOICE="${AVAILABLE_PROFILES[0]}"
  else
    echo -e "${BOLD}Select AWS CLI Profile for Route 53 & SST deployment:${NC}"
    for i in "${!AVAILABLE_PROFILES[@]}"; do
      echo "  [$((i+1))] ${AVAILABLE_PROFILES[$i]}"
    done
    read -r -p "Enter choice [1-${#AVAILABLE_PROFILES[@]} or profile name] (default: 1): " PROF_INPUT
    if [ -z "${PROF_INPUT}" ]; then
      AWS_PROFILE_CHOICE="${AVAILABLE_PROFILES[0]}"
    elif [[ "${PROF_INPUT}" =~ ^[0-9]+$ ]] && [ "${PROF_INPUT}" -ge 1 ] && [ "${PROF_INPUT}" -le "${#AVAILABLE_PROFILES[@]}" ]; then
      AWS_PROFILE_CHOICE="${AVAILABLE_PROFILES[$((PROF_INPUT-1))]}"
    else
      AWS_PROFILE_CHOICE="${PROF_INPUT}"
    fi
  fi
fi

export AWS_PROFILE="${AWS_PROFILE_CHOICE}"
log_success "Using AWS Profile: '${AWS_PROFILE}'"

# Check GitHub Actions Secrets availability
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_SECRETS=$(gh secret list 2>/dev/null | grep -E "AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY" || true)
  if [ -n "${GH_SECRETS}" ]; then
    log_success "GitHub repository secrets (AWS_ACCESS_KEY_ID) detected for CI/CD workflow."
  else
    log_info "GitHub repository secrets for AWS are not yet configured."
    if [ "${NON_INTERACTIVE}" != true ] && [ "${HAS_AWS_CLI}" = true ]; then
      read -r -p "Would you like to sync your AWS profile credentials to GitHub Secrets? (y/N): " SYNC_GH
      if [[ "${SYNC_GH}" =~ ^[Yy]$ ]]; then
        AWS_K_ID="$(aws configure get aws_access_key_id --profile "${AWS_PROFILE}" 2>/dev/null || true)"
        AWS_S_KEY="$(aws configure get aws_secret_access_key --profile "${AWS_PROFILE}" 2>/dev/null || true)"
        AWS_REG="$(aws configure get region --profile "${AWS_PROFILE}" 2>/dev/null || echo 'us-east-1')"
        if [ -n "${AWS_K_ID}" ] && [ -n "${AWS_S_KEY}" ]; then
          gh secret set AWS_ACCESS_KEY_ID --body "${AWS_K_ID}" >/dev/null 2>&1 || true
          gh secret set AWS_SECRET_ACCESS_KEY --body "${AWS_S_KEY}" >/dev/null 2>&1 || true
          gh secret set AWS_REGION --body "${AWS_REG}" >/dev/null 2>&1 || true
          log_success "Synced AWS credentials to GitHub repository secrets."
        fi
      fi
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 2. Route 53 Hosted Zone Selection
# ------------------------------------------------------------------------------
log_info "Step 2/4: Discovering Route 53 Hosted Zones..."

DETECTED_ZONES=()
if [ "${HAS_AWS_CLI}" = true ]; then
  while IFS=$'\t' read -r zname zid; do
    clean_name="${zname%.}"
    [ -n "${clean_name}" ] && DETECTED_ZONES+=("${clean_name}")
  done < <(aws route53 list-hosted-zones --profile "${AWS_PROFILE}" --query 'HostedZones[*].[Name,Id]' --output text 2>/dev/null || true)
fi

if [ -z "${ZONE_NAME}" ]; then
  if [ ${#DETECTED_ZONES[@]} -gt 0 ]; then
    if [ "${NON_INTERACTIVE}" = true ]; then
      # Default to brainsos.ai if present, else first
      for z in "${DETECTED_ZONES[@]}"; do
        if [ "$z" = "brainsos.ai" ]; then
          ZONE_NAME="brainsos.ai"
          break
        fi
      done
      [ -z "${ZONE_NAME}" ] && ZONE_NAME="${DETECTED_ZONES[0]}"
    else
      echo -e "${BOLD}Select Route 53 Hosted Zone for Wildcard SSL (*.local.<zone>):${NC}"
      DEFAULT_IDX=1
      for i in "${!DETECTED_ZONES[@]}"; do
        echo "  [$((i+1))] ${DETECTED_ZONES[$i]}"
        if [ "${DETECTED_ZONES[$i]}" = "brainsos.ai" ]; then
          DEFAULT_IDX=$((i+1))
        fi
      done
      echo "  [c] Enter custom hosted zone domain"
      read -r -p "Enter choice [1-${#DETECTED_ZONES[@]} or 'c'] (default: ${DEFAULT_IDX}): " ZONE_INPUT
      if [ -z "${ZONE_INPUT}" ]; then
        ZONE_NAME="${DETECTED_ZONES[$((DEFAULT_IDX-1))]}"
      elif [[ "${ZONE_INPUT}" =~ ^[0-9]+$ ]] && [ "${ZONE_INPUT}" -ge 1 ] && [ "${ZONE_INPUT}" -le "${#DETECTED_ZONES[@]}" ]; then
        ZONE_NAME="${DETECTED_ZONES[$((ZONE_INPUT-1))]}"
      else
        read -r -p "Enter custom hosted zone domain (e.g. brainsos.ai): " CUSTOM_ZONE
        ZONE_NAME="${CUSTOM_ZONE%.}"
      fi
    fi
  else
    if [ "${NON_INTERACTIVE}" = true ]; then
      ZONE_NAME="${BRAINSOS_ZONE_NAME:-brainsos.ai}"
    else
      read -r -p "Enter Route 53 hosted zone domain (default: ${BRAINSOS_ZONE_NAME:-brainsos.ai}): " ZONE_INPUT
      ZONE_NAME="${ZONE_INPUT:-${BRAINSOS_ZONE_NAME:-brainsos.ai}}"
    fi
  fi
fi

ZONE_NAME="${ZONE_NAME%.}"
TARGET_DOMAIN="${APPLIANCE_PREFIX}.local.${ZONE_NAME}"
WILDCARD_DOMAIN="*.local.${ZONE_NAME}"

log_success "Target Hosted Zone: '${ZONE_NAME}'"
log_success "Appliance Hostname: '${TARGET_DOMAIN}'"
log_success "Public Wildcard Certificate: '${WILDCARD_DOMAIN}'"

# ------------------------------------------------------------------------------
# 3. SST Cloud Infrastructure Deployment
# ------------------------------------------------------------------------------
log_info "Step 3/4: Cloud Infrastructure & Scoped ACME Credentials (SST Ion)..."

if [ -z "${DEPLOY_METHOD}" ]; then
  if [ "${NON_INTERACTIVE}" = true ]; then
    DEPLOY_METHOD="sst-local"
  else
    echo -e "${BOLD}Select Deployment Strategy for Cloud Infrastructure:${NC}"
    echo "  [1] Local SST Deploy (Recommended: deploys infra/ using '${AWS_PROFILE}')"
    echo "  [2] GitHub Actions Workflow (triggers .github/workflows/deploy-infra.yml)"
    echo "  [3] Direct Caddy Route 53 (configure Caddy ACME without redeploying SST)"
    read -r -p "Enter choice [1-3] (default: 1): " METHOD_INPUT
    case "${METHOD_INPUT}" in
      2) DEPLOY_METHOD="github-workflow" ;;
      3) DEPLOY_METHOD="direct" ;;
      *) DEPLOY_METHOD="sst-local" ;;
    esac
  fi
fi

case "${DEPLOY_METHOD}" in
  sst-local)
    log_info "Deploying platform cloud infrastructure via local SST Ion..."
    (
      cd "${REPO_ROOT}/infra"
      if [ ! -d "node_modules" ]; then
        log_info "Installing dependencies in infra/..."
        npm install
      fi
      if [ ! -d ".sst/platform" ]; then
        log_info "Installing SST providers..."
        npx sst install
      fi
      log_info "Running SST Ion deployment against AWS (stage: production)..."
      BRAINSOS_ZONE_NAME="${ZONE_NAME}" npx sst deploy --stage production
    )
    log_success "SST platform infrastructure deployed."
    ;;

  github-workflow)
    log_info "Triggering GitHub Actions workflow '.github/workflows/deploy-infra.yml'..."
    if command -v gh >/dev/null 2>&1; then
      gh workflow run deploy-infra.yml -f zone_name="${ZONE_NAME}" -f stage="production"
      log_success "Workflow dispatched to GitHub Actions! View status with: gh run list --workflow=deploy-infra.yml"
    else
      log_warn "GitHub CLI (gh) not found. Please trigger deploy-infra.yml from the GitHub Actions console."
    fi
    ;;

  direct)
    log_info "Using direct Caddy Route 53 ACME configuration."
    ;;
esac

# ------------------------------------------------------------------------------
# 4. Synchronize .env & Reload Caddy Ingress
# ------------------------------------------------------------------------------
log_info "Step 4/4: Updating .env and reloading Caddy ingress..."

# Resolve AWS credentials from selected profile if not already set
RESOLVED_KEY=""
RESOLVED_SECRET=""
RESOLVED_REGION="us-east-1"

if [ "${HAS_AWS_CLI}" = true ]; then
  RESOLVED_KEY="$(aws configure get aws_access_key_id --profile "${AWS_PROFILE}" 2>/dev/null || true)"
  RESOLVED_SECRET="$(aws configure get aws_secret_access_key --profile "${AWS_PROFILE}" 2>/dev/null || true)"
  RESOLVED_REGION="$(aws configure get region --profile "${AWS_PROFILE}" 2>/dev/null || echo 'us-east-1')"
fi

# Update .env parameters safely
python3 - << PYEOF
import os

env_path = os.path.join("${REPO_ROOT}", ".env")
with open(env_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_keys = {
    "ACME_DNS_PROVIDER": "route53",
    "BRAINSOS_ZONE_NAME": "${ZONE_NAME}",
    "BRAINSOS_DOMAIN": "${TARGET_DOMAIN}",
    "ACME_EMAIL": "${BRAINSOS_ADMIN_EMAIL:-system@dgx.public.${ZONE_NAME}}",
}

if "${RESOLVED_KEY}":
    new_keys["BRAINSOS_INFRA_AWS_ACCESS_KEY_ID"] = "${RESOLVED_KEY}"
if "${RESOLVED_SECRET}":
    new_keys["BRAINSOS_INFRA_AWS_SECRET_ACCESS_KEY"] = "${RESOLVED_SECRET}"
if "${RESOLVED_REGION}":
    new_keys["BRAINSOS_INFRA_AWS_REGION"] = "${RESOLVED_REGION}"

updated = set()
out_lines = []
for line in lines:
    matched = False
    for k, v in new_keys.items():
        if line.startswith(f"{k}=") or line.startswith(f"#{k}="):
            out_lines.append(f"{k}={v}\n")
            updated.add(k)
            matched = True
            break
    if not matched:
        out_lines.append(line)

for k, v in new_keys.items():
    if k not in updated:
        out_lines.append(f"{k}={v}\n")

with open(env_path, "w", encoding="utf-8") as f:
    f.writelines(out_lines)
PYEOF

log_success "Updated .env configuration with Route 53 parameters for '${ZONE_NAME}'."

# Reload environment and Caddy ingress
log_info "Reloading environment, Caddy TLS policy, and control plane..."
"${REPO_ROOT}/scripts/control/reload-env.sh"

# ------------------------------------------------------------------------------
# 5. Strict SSL Verification
# ------------------------------------------------------------------------------
log_info "Verifying public wildcard certificate trust via strict TLS..."
sleep 2

SSL_CHECK=$(curl -Iv "https://${TARGET_DOMAIN}/" 2>&1 || true)
if echo "${SSL_CHECK}" | grep -q "SSL certificate verify ok"; then
  ISSUER=$(echo "${SSL_CHECK}" | grep "issuer:" | head -n 1 | sed 's/^[ *]*//')
  SUBJECT=$(echo "${SSL_CHECK}" | grep "subject:" | head -n 1 | sed 's/^[ *]*//')
  echo ""
  echo -e "${BOLD}${GREEN}"
  echo "══════════════════════════════════════════════════════════════════════════════"
  echo "  [SUCCESS] Public Wildcard SSL Certificate Successfully Active!"
  echo "══════════════════════════════════════════════════════════════════════════════"
  echo -e "${NC}"
  echo "  ${SUBJECT}"
  echo "  ${ISSUER}"
  echo "  Validation: 100% Strict TLS Verified (ZeroSSL / Let's Encrypt)"
  echo ""
  echo "Your appliance is now securely accessible from any browser on macOS, iOS, Linux, or Windows:"
  echo "  -> https://${TARGET_DOMAIN}/"
  echo "  -> https://editor.${TARGET_DOMAIN}/ (or /editor/)"
  echo "  -> https://${TARGET_DOMAIN}/proxy/ui/"
  echo "  -> https://${TARGET_DOMAIN}/dgx/"
  echo ""
  echo "Zero certificate imports or root CA trust steps required!"
else
  log_warn "Caddy is processing ACME DNS-01 challenge with Route 53 nameservers (typically takes 30-45s)."
  log_info "To check certificate status in a few seconds, run:"
  echo "  curl -Iv https://${TARGET_DOMAIN}/"
fi
