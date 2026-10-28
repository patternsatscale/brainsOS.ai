#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Golden AMI Build, Staging & Promotion Wrapper
# Tickets #313 / #322 (Epic #309, Remediation Epic #321)
#
# Builds the brainsOS ARM64 appliance golden AMI from a clean, git-staged
# artifact (never the working tree), then optionally promotes a private AMI to
# public after an AWS Block Public Access pre-flight.
#
# Recommended release flow:
#   1. ./scripts/control/build-ami.sh --ref v0.1.0           # private AMI
#   2. Rehearse the private AMI (#320)
#   3. ./scripts/control/build-ami.sh --promote ami-0123...  # make public
#
# Usage:
#   ./scripts/control/build-ami.sh [OPTIONS]
#
# Options:
#   --ref REF               Git tag/branch/commit to bake (Default: latest v* tag)
#   --allow-dirty           Permit building while the working tree has local changes
#   --region REGION         Target AWS region (Default: us-east-1 or $AWS_REGION)
#   --instance-type TYPE    EC2 instance type for builder (Default: c7g.xlarge)
#   --volume-size SIZE      Root EBS volume size in GB (Default: 50)
#   --ssh-interface IFACE   Packer communicator interface (Default: session_manager)
#   --publish-community     Publish publicly at build time (prefer --promote)
#   --promote AMI_ID        Make an existing private AMI public (BPA pre-flight)
#   --keep-stage            Keep the staged artifact directory after exit
#   --validate-only         Validate Packer templates without starting build
#   --dry-run               Stage + scan the artifact and print the build command
#   -h, --help              Show this help message
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

PACKER_DIR="${REPO_ROOT}/packages/brainsOS-appliance/packer"
PROVISION_SH="${PACKER_DIR}/provision.sh"
PUBLIC_REMOTE_URL="${BRAINSOS_PUBLIC_REMOTE:-https://github.com/patternsatscale/brainsOS.ai}"

# Default options
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
INSTANCE_TYPE="c7g.xlarge"
VOLUME_SIZE=50
SSH_INTERFACE="session_manager"
PUBLISH_COMMUNITY=false
VALIDATE_ONLY=false
DRY_RUN=false
ALLOW_DIRTY=false
KEEP_STAGE=false
BUILD_REF=""
PROMOTE_AMI=""

usage() {
  cat <<EOF
brainsOS ARM64 AMI Build, Staging & Promotion Wrapper (Tickets #313 / #322)

Usage:
  ./scripts/control/build-ami.sh [OPTIONS]

Options:
  --ref REF               Git tag/branch/commit to bake (Default: latest v* tag)
  --allow-dirty           Permit building while the working tree has local changes
  --region REGION         Target AWS region (Default: ${AWS_REGION})
  --instance-type TYPE    EC2 instance type for builder (Default: ${INSTANCE_TYPE})
  --volume-size SIZE      Root EBS volume size in GB (Default: ${VOLUME_SIZE})
  --ssh-interface IFACE   Packer communicator interface (Default: ${SSH_INTERFACE})
  --publish-community     Publish publicly at build time (prefer --promote)
  --promote AMI_ID        Make an existing private AMI public (BPA pre-flight)
  --keep-stage            Keep the staged artifact directory after exit
  --validate-only         Validate Packer templates without starting build
  --dry-run               Stage + scan the artifact and print the build command
  -h, --help              Show this help message

Release flow:
  1. build-ami.sh --ref v0.1.0            (private AMI)
  2. rehearse the private AMI             (#320)
  3. build-ami.sh --promote <ami-id>      (public)
EOF
}

require_arg() {
  if [ -z "${2:-}" ] || [[ "${2}" == --* ]]; then
    log_error "Option $1 requires a value."
    exit 1
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ref)            require_arg "$1" "${2:-}"; BUILD_REF="$2"; shift 2 ;;
    --allow-dirty)    ALLOW_DIRTY=true; shift ;;
    --region)         require_arg "$1" "${2:-}"; AWS_REGION="$2"; shift 2 ;;
    --instance-type)  require_arg "$1" "${2:-}"; INSTANCE_TYPE="$2"; shift 2 ;;
    --volume-size)    require_arg "$1" "${2:-}"; VOLUME_SIZE="$2"; shift 2 ;;
    --ssh-interface)  require_arg "$1" "${2:-}"; SSH_INTERFACE="$2"; shift 2 ;;
    --publish-community) PUBLISH_COMMUNITY=true; shift ;;
    --promote)        require_arg "$1" "${2:-}"; PROMOTE_AMI="$2"; shift 2 ;;
    --keep-stage)     KEEP_STAGE=true; shift ;;
    --validate-only)  VALIDATE_ONLY=true; shift ;;
    --dry-run)        DRY_RUN=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)
      log_error "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# AWS pre-flight helpers
# ------------------------------------------------------------------------------
require_aws_cli() {
  if ! command -v aws >/dev/null 2>&1; then
    log_error "AWS CLI v2 is required (https://docs.aws.amazon.com/cli/)."
    exit 1
  fi
  if ! aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1; then
    log_error "AWS credentials are not configured or have expired (aws sts get-caller-identity failed)."
    exit 1
  fi
}

# Account-level Block Public Access for AMIs silently prevents public sharing.
check_block_public_access() {
  local state
  state="$(aws ec2 get-image-block-public-access-state --region "${AWS_REGION}" \
    --query 'ImageBlockPublicAccessState' --output text 2>/dev/null || echo "unknown")"
  case "${state}" in
    unblocked)
      log_success "AMI Block Public Access is disabled in ${AWS_REGION}."
      ;;
    block-new-sharing)
      log_error "AMI Block Public Access is ENABLED in ${AWS_REGION} (state: ${state})."
      log_error "Public sharing will be rejected. An account administrator must run:"
      log_error "  aws ec2 disable-image-block-public-access --region ${AWS_REGION}"
      exit 1
      ;;
    *)
      log_error "Unable to determine AMI Block Public Access state in ${AWS_REGION} (got: ${state})."
      log_error "Grant ec2:GetImageBlockPublicAccessState or verify the setting manually."
      exit 1
      ;;
  esac
}

# ------------------------------------------------------------------------------
# Promotion mode: private AMI -> public (no build)
# ------------------------------------------------------------------------------
if [ -n "${PROMOTE_AMI}" ]; then
  if [[ ! "${PROMOTE_AMI}" =~ ^ami-[0-9a-f]{8,17}$ ]]; then
    log_error "Invalid AMI ID: ${PROMOTE_AMI}"
    exit 1
  fi
  log_info "Promoting ${PROMOTE_AMI} to public in ${AWS_REGION}..."
  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Would check AMI Block Public Access state in ${AWS_REGION}"
    log_info "[DRY-RUN] Would verify ${PROMOTE_AMI} exists, is available and has no encrypted snapshots"
    log_info "[DRY-RUN] Would run: aws ec2 modify-image-attribute --region ${AWS_REGION} --image-id ${PROMOTE_AMI} --launch-permission Add=[{Group=all}]"
    log_success "[DRY-RUN] Promotion simulation complete."
    exit 0
  fi

  require_aws_cli
  check_block_public_access

  IMAGE_STATE="$(aws ec2 describe-images --region "${AWS_REGION}" --image-ids "${PROMOTE_AMI}" \
    --query 'Images[0].State' --output text)"
  if [ "${IMAGE_STATE}" != "available" ]; then
    log_error "AMI ${PROMOTE_AMI} is not available (state: ${IMAGE_STATE})."
    exit 1
  fi
  ENCRYPTED="$(aws ec2 describe-images --region "${AWS_REGION}" --image-ids "${PROMOTE_AMI}" \
    --query 'Images[0].BlockDeviceMappings[].Ebs.Encrypted' --output text)"
  if echo "${ENCRYPTED}" | grep -qi "true"; then
    log_error "AMI ${PROMOTE_AMI} references encrypted snapshots; public AMIs cannot be encrypted."
    exit 1
  fi

  aws ec2 modify-image-attribute --region "${AWS_REGION}" --image-id "${PROMOTE_AMI}" \
    --launch-permission "Add=[{Group=all}]"
  PUBLIC_FLAG="$(aws ec2 describe-images --region "${AWS_REGION}" --image-ids "${PROMOTE_AMI}" \
    --query 'Images[0].Public' --output text)"
  if [ "${PUBLIC_FLAG}" != "True" ]; then
    log_error "Launch permission was set but ${PROMOTE_AMI} does not report Public=True."
    exit 1
  fi
  log_success "AMI ${PROMOTE_AMI} is now public in ${AWS_REGION}."
  exit 0
fi

# ------------------------------------------------------------------------------
# Build mode
# ------------------------------------------------------------------------------
if [ ! -d "${PACKER_DIR}" ]; then
  log_error "Packer template directory not found at: ${PACKER_DIR}"
  exit 1
fi

# Locate packer binary
PACKER_BIN="$(command -v packer || true)"
if [ -z "${PACKER_BIN}" ] && [ -x "${REPO_ROOT}/.venv/bin/packer" ]; then
  PACKER_BIN="${REPO_ROOT}/.venv/bin/packer"
elif [ -z "${PACKER_BIN}" ] && [ -x "/usr/local/bin/packer" ]; then
  PACKER_BIN="/usr/local/bin/packer"
fi
if [ -z "${PACKER_BIN}" ]; then
  if [ "${DRY_RUN}" = true ]; then
    log_warn "Packer executable not found; template validation will be skipped in dry-run."
  else
    log_error "Packer executable not found in PATH or .venv/bin/packer."
    log_info "Please install Packer (https://developer.hashicorp.com/packer/install)."
    exit 1
  fi
fi

STAGE_PARENT=""
cleanup_stage() {
  if [ -n "${STAGE_PARENT}" ] && [ -d "${STAGE_PARENT}" ]; then
    if [ "${KEEP_STAGE}" = true ]; then
      log_info "Staged artifact kept at: ${STAGE_PARENT}/brainsos"
    else
      rm -rf "${STAGE_PARENT}"
    fi
  fi
}
trap cleanup_stage EXIT

packer_vars() {
  local source_dir="$1" ref="$2" commit="$3"
  printf '%s\n' \
    "-var=aws_region=${AWS_REGION}" \
    "-var=instance_type=${INSTANCE_TYPE}" \
    "-var=volume_size=${VOLUME_SIZE}" \
    "-var=publish_community=${PUBLISH_COMMUNITY}" \
    "-var=ssh_interface=${SSH_INTERFACE}" \
    "-var=source_dir=${source_dir}" \
    "-var=brainsos_ref=${ref}" \
    "-var=brainsos_commit=${commit}"
}

# --validate-only does not need a staged artifact; an empty directory suffices.
if [ "${VALIDATE_ONLY}" = true ]; then
  STAGE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/brainsos-ami-validate.XXXXXX")"
  mapfile -t VARS < <(packer_vars "${STAGE_PARENT}" "validate" "0000000")
  log_info "Validating Packer templates..."
  "${PACKER_BIN}" validate "${VARS[@]}" "${PACKER_DIR}"
  log_success "Validation complete (--validate-only). Exiting."
  exit 0
fi

# 1. Resolve the git ref (default: latest release tag)
if [ -z "${BUILD_REF}" ]; then
  BUILD_REF="$(git -C "${REPO_ROOT}" describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
  if [ -z "${BUILD_REF}" ]; then
    log_error "No v* release tag found. Pass --ref <tag|branch|commit> explicitly."
    exit 1
  fi
fi
BUILD_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --verify --quiet "${BUILD_REF}^{commit}" || true)"
if [ -z "${BUILD_COMMIT}" ]; then
  log_error "Git ref not found: ${BUILD_REF}"
  exit 1
fi

# 2. Refuse a dirty working tree (guards against assuming local edits are baked)
if [ -n "$(git -C "${REPO_ROOT}" status --porcelain 2>/dev/null)" ]; then
  if [ "${ALLOW_DIRTY}" = true ]; then
    log_warn "Working tree has local changes; they are NOT included (artifact is staged from ${BUILD_REF})."
  else
    log_error "Working tree has uncommitted changes. Commit/stash them or pass --allow-dirty."
    log_error "Note: the AMI is always staged from the git ref (${BUILD_REF}), never the working tree."
    exit 1
  fi
fi

# 3. Warn when the commit is not published (appliance update engine pulls from origin)
if [ -z "$(git -C "${REPO_ROOT}" branch -r --contains "${BUILD_COMMIT}" 2>/dev/null)" ] && \
   [ -z "$(git -C "${REPO_ROOT}" ls-remote --tags origin 2>/dev/null | grep "${BUILD_COMMIT}" || true)" ]; then
  log_warn "Commit ${BUILD_COMMIT:0:12} is not on any known remote branch or tag; appliance updates may not resolve it."
fi

log_info "brainsOS Appliance Golden AMI Builder"
log_info "Git Ref:         ${BUILD_REF} (${BUILD_COMMIT:0:12})"
log_info "Packer Binary:   ${PACKER_BIN:-<not found>}"
log_info "AWS Region:      ${AWS_REGION}"
log_info "Instance Type:   ${INSTANCE_TYPE}"
log_info "Root Volume:     ${VOLUME_SIZE} GB"
log_info "Communicator:    ${SSH_INTERFACE}"
log_info "Publish Public:  ${PUBLISH_COMMUNITY}"

# 4. Stage a clean artifact from git (shallow clone of exactly one commit)
STAGE_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/brainsos-ami-stage.XXXXXX")"
STAGE_DIR="${STAGE_PARENT}/brainsos"
log_info "Staging clean artifact from ${BUILD_REF} into ${STAGE_DIR}..."
git init --quiet --initial-branch=main "${STAGE_DIR}"
git -C "${STAGE_DIR}" fetch --quiet --depth 1 \
  --upload-pack="git -c uploadpack.allowAnySHA1InWant=true upload-pack" \
  "file://${REPO_ROOT}" "${BUILD_COMMIT}"
git -C "${STAGE_DIR}" checkout --quiet -B main FETCH_HEAD
git -C "${STAGE_DIR}" remote add origin "${PUBLIC_REMOTE_URL}"
git -C "${STAGE_DIR}" update-ref refs/remotes/origin/main "${BUILD_COMMIT}"
git -C "${STAGE_DIR}" branch --quiet --set-upstream-to=origin/main main
if git -C "${REPO_ROOT}" rev-parse --verify --quiet "refs/tags/${BUILD_REF}" >/dev/null; then
  git -C "${STAGE_DIR}" tag "${BUILD_REF}" "${BUILD_COMMIT}"
fi
STAGED_FILES="$(git -C "${STAGE_DIR}" ls-files | wc -l | tr -d ' ')"
log_success "Staged ${STAGED_FILES} tracked files at commit ${BUILD_COMMIT:0:12}."

for required in packages/brainsOS-appliance/packer/provision.sh \
                packages/brainsOS-appliance/scripts/firstboot.sh \
                packages/brainsOS-appliance/configs/brainsos.service \
                config/litellm/config.bedrock.yaml; do
  if [ ! -f "${STAGE_DIR}/${required}" ]; then
    log_error "Ref ${BUILD_REF} does not contain ${required}; it predates the appliance package."
    log_error "Pass --ref with a release that includes Epic #309 / #321."
    exit 1
  fi
done

# 5. Fail-closed scan of the staged artifact before anything leaves this host
log_info "Scanning staged artifact for secrets and runtime data..."
if ! bash "${PROVISION_SH}" --scan-only --app-dir "${STAGE_DIR}"; then
  log_error "Staged artifact failed the snapshot scan. Aborting before Packer."
  exit 1
fi

# 6. Packer validate against the staged artifact
mapfile -t VARS < <(packer_vars "${STAGE_DIR}" "${BUILD_REF}" "${BUILD_COMMIT}")
if [ -n "${PACKER_BIN}" ]; then
  log_info "Validating Packer templates..."
  "${PACKER_BIN}" validate "${VARS[@]}" "${PACKER_DIR}"
  log_success "Packer templates are valid."
fi

BUILD_CMD=("${PACKER_BIN:-packer}" build "${VARS[@]}" "${PACKER_DIR}")

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Staged artifact top-level contents:"
  git -C "${STAGE_DIR}" ls-tree --name-only HEAD | sed 's/^/    /'
  if [ "${SSH_INTERFACE}" = "session_manager" ]; then
    log_info "[DRY-RUN] Would require AWS CLI + session-manager-plugin on this host"
  fi
  if [ "${PUBLISH_COMMUNITY}" = true ]; then
    log_info "[DRY-RUN] Would check AMI Block Public Access state in ${AWS_REGION}"
  fi
  log_info "[DRY-RUN] Would execute:"
  echo -e "${YELLOW}${BUILD_CMD[*]}${NC}"
  log_success "[DRY-RUN] AMI build simulation complete."
  exit 0
fi

# 7. Build-host pre-flights
require_aws_cli
if [ "${SSH_INTERFACE}" = "session_manager" ] && ! command -v session-manager-plugin >/dev/null 2>&1; then
  log_error "session-manager-plugin is required for the SSM communicator:"
  log_error "  https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html"
  exit 1
fi
if [ "${PUBLISH_COMMUNITY}" = true ]; then
  check_block_public_access
fi

log_info "Starting Packer AMI build..."
"${BUILD_CMD[@]}"
log_success "brainsOS ARM64 golden AMI build completed (ref ${BUILD_REF}, commit ${BUILD_COMMIT:0:12})."
if [ "${PUBLISH_COMMUNITY}" != true ]; then
  log_info "The AMI is private. After rehearsal (#320), publish it with:"
  log_info "  ./scripts/control/build-ami.sh --region ${AWS_REGION} --promote <ami-id>"
fi
