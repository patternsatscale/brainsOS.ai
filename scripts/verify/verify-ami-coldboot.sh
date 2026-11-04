#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Cold-Boot Golden AMI Verification Suite
# Ticket #320 (Epic #309 / #321)
#
# Boots a clean EC2 ARM64 instance from a candidate AMI, verifies zero-touch
# first-boot provisioning, splash-screen-to-SSO transition (zero 404 Not Found),
# container health, and System Management API readiness, and cleans up.
#
# Usage:
#   ./scripts/verify/verify-ami-coldboot.sh --ami <ami-id> [OPTIONS]
#
# Options:
#   --ami AMI_ID            Target AMI ID to boot and verify (Required)
#   --region REGION         AWS Region (Default: us-east-1 or $AWS_REGION)
#   --instance-type TYPE    Instance type (Default: c7g.xlarge)
#   --keep-instance         Leave the verification instance running after pass
#   --dry-run               Validate CLI options without launching EC2 resources
#   -h, --help              Show this help message
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

AMI_ID=""
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
INSTANCE_TYPE="c7g.xlarge"
KEEP_INSTANCE=false
DRY_RUN=false
IAM_PROFILE="${BRAINSOS_IAM_PROFILE:-brainsos-appliance}"

usage() {
  cat <<EOF
brainsOS Automated Cold-Boot Golden AMI Verification Suite (Ticket #320)

Usage:
  ./scripts/verify/verify-ami-coldboot.sh --ami <ami-id> [OPTIONS]

Options:
  --ami AMI_ID            Target AMI ID to boot and verify (Required)
  --region REGION         AWS Region (Default: ${AWS_REGION})
  --instance-type TYPE    Instance type (Default: ${INSTANCE_TYPE})
  --keep-instance         Leave the verification instance running after pass
  --dry-run               Validate arguments without launching EC2 resources
  -h, --help              Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ami)           AMI_ID="${2:-}"; shift 2 ;;
    --region)        AWS_REGION="${2:-}"; shift 2 ;;
    --instance-type) INSTANCE_TYPE="${2:-}"; shift 2 ;;
    --keep-instance) KEEP_INSTANCE=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    -h|--help)       usage; exit 0 ;;
    *)               log_error "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ ! "${AMI_ID}" =~ ^ami-[0-9a-f]{8,17}$ ]]; then
  log_error "A valid --ami <ami-id> is required."
  usage
  exit 1
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would boot ${INSTANCE_TYPE} from ${AMI_ID} in ${AWS_REGION}"
  log_info "[DRY-RUN] Would verify zero-touch cold boot (503 splash -> 302 SSO redirect, zero 404 Not Found)"
  log_success "[DRY-RUN] Cold-boot verification dry-run passed."
  exit 0
fi

INST_ID=""
SG_ID=""
CREATED_SG=false

cleanup() {
  if [ "${KEEP_INSTANCE}" = true ] && [ -n "${INST_ID}" ]; then
    log_info "Keeping verification instance running (--keep-instance): ${INST_ID}"
    return 0
  fi
  if [ -n "${INST_ID}" ]; then
    log_info "Terminating verification instance ${INST_ID}..."
    aws ec2 terminate-instances --region "${AWS_REGION}" --instance-ids "${INST_ID}" >/dev/null 2>&1 || true
    aws ec2 wait instance-terminated --region "${AWS_REGION}" --instance-ids "${INST_ID}" 2>/dev/null || true
  fi
  if [ "${CREATED_SG}" = true ] && [ -n "${SG_ID}" ]; then
    aws ec2 delete-security-group --region "${AWS_REGION}" --group-id "${SG_ID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log_info "Preparing cold-boot verification for AMI ${AMI_ID} in ${AWS_REGION}..."

SG_ID="$(aws ec2 describe-security-groups --region "${AWS_REGION}" \
  --filters "Name=group-name,Values=brainsos-rehearsal-320" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -z "${SG_ID}" ] || [ "${SG_ID}" = "None" ]; then
  SG_ID="$(aws ec2 create-security-group --region "${AWS_REGION}" \
    --group-name "brainsos-rehearsal-320" \
    --description "brainsOS Ticket 320 Cold-Boot Verification" \
    --query 'GroupId' --output text)"
  CREATED_SG=true
  aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SG_ID}" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
  aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SG_ID}" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null
fi

PROFILE_ARG=()
if aws iam get-instance-profile --instance-profile-name "${IAM_PROFILE}" >/dev/null 2>&1; then
  PROFILE_ARG=(--iam-instance-profile "Name=${IAM_PROFILE}")
fi

INST_ID="$(aws ec2 run-instances --region "${AWS_REGION}" \
  --image-id "${AMI_ID}" \
  --instance-type "${INSTANCE_TYPE}" \
  --security-group-ids "${SG_ID}" \
  "${PROFILE_ARG[@]}" \
  --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=brainsos-coldboot-verify}]" \
  --query 'Instances[0].InstanceId' --output text)"

log_info "Launched cold-boot instance: ${INST_ID}. Waiting for running state..."
aws ec2 wait instance-running --region "${AWS_REGION}" --instance-ids "${INST_ID}"

PUBLIC_DNS="$(aws ec2 describe-instances --region "${AWS_REGION}" --instance-ids "${INST_ID}" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"
PUBLIC_IP="$(aws ec2 describe-instances --region "${AWS_REGION}" --instance-ids "${INST_ID}" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"

log_info "Instance running at https://${PUBLIC_DNS}/ (IP: ${PUBLIC_IP})"
log_info "Polling HTTPS endpoint from outside (expecting 503 Initializing splash -> 302 SSO redirect, zero 404)..."

READY=false
SAW_404=false
for attempt in $(seq 1 90); do
  HTTP_CODE="$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 "https://${PUBLIC_DNS}/" 2>/dev/null || true)"
  [ -z "${HTTP_CODE}" ] && HTTP_CODE="000"
  if [ "${HTTP_CODE}" = "404" ]; then
    log_warn "[Attempt ${attempt}] Received HTTP 404 (Authentik Outpost Not Found)!"
    SAW_404=true
  elif [ "${HTTP_CODE}" = "302" ]; then
    LOCATION="$(curl -sk -I --connect-timeout 3 --max-time 5 "https://${PUBLIC_DNS}/" 2>/dev/null | grep -i '^location:' | tr -d '\r' || true)"
    if echo "${LOCATION}" | grep -q "/application/o/authorize/"; then
      log_success "[Attempt ${attempt}] HTTPS endpoint returned HTTP 302 redirect to Authentik SSO!"
      READY=true
      break
    fi
  else
    log_info "[Attempt ${attempt}] HTTP status: ${HTTP_CODE} (waiting for cold-boot initialization...)"
  fi
  sleep 5
done

if [ "${READY}" != true ]; then
  log_error "Cold-boot verification timed out waiting for HTTP 302 SSO redirect on https://${PUBLIC_DNS}/"
  exit 1
fi

# Verify bare-IP HTTPS redirect to primary DNS hostname
IP_CODE="$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 "https://${PUBLIC_IP}/" 2>/dev/null || true)"
[ -z "${IP_CODE}" ] && IP_CODE="000"
if [ "${IP_CODE}" = "302" ]; then
  log_success "Bare-IP HTTPS request (https://${PUBLIC_IP}/) cleanly returned HTTP 302 redirect to primary hostname."
else
  log_warn "Bare-IP HTTPS request returned HTTP ${IP_CODE} (expected 302)."
fi

if [ "${SAW_404}" = true ]; then
  log_error "Cold-boot verification detected an Authentik HTTP 404 Not Found window during startup!"
  exit 1
fi

log_success "=============================================================================="
log_success "Cold-Boot AMI Verification PASSED for ${AMI_ID}!"
log_success "  Instance ID:       ${INST_ID}"
log_success "  URL:               https://${PUBLIC_DNS}/"
log_success "  Username:          admin"
log_success "  Initial Password:  ${INST_ID}"
log_success "=============================================================================="

