#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Platform Cloud Infrastructure Deployment Tool (infra/)
# Deploys Route 53 DNS, public redirect, Caddy ACME IAM credentials, and SES.
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Precondition: Rule 13
if [ ! -f .env ]; then
  log_error "Execution precondition failed: No .env file present in repository root."
  exit 1
fi

# Load root .env
set -a
. ./.env
set +a

# Also load infra/.env if present
if [ -f "${REPO_ROOT}/infra/.env" ]; then
  set -a
  . "${REPO_ROOT}/infra/.env"
  set +a
fi

INFRA_DIR="${REPO_ROOT}/infra"
STAGE="production"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --stage)
      STAGE="$2"
      shift 2
      ;;
    production|prod|staging|dev)
      STAGE="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

log_info "======================================================================"
log_info "brainsOS: Deploying Platform Cloud Infrastructure"
log_info "Stage: ${STAGE} | Dry Run: ${DRY_RUN}"
log_info "======================================================================"

# Map namespaced credentials to standard AWS environment variables for SST if provided;
# otherwise SST falls back seamlessly to ~/.aws/credentials and the AWS credential chain.
if [ -n "${BRAINSOS_INFRA_AWS_ACCESS_KEY_ID:-}" ]; then
  export AWS_ACCESS_KEY_ID="${BRAINSOS_INFRA_AWS_ACCESS_KEY_ID}"
  export AWS_SECRET_ACCESS_KEY="${BRAINSOS_INFRA_AWS_SECRET_ACCESS_KEY:-}"
  log_info "Using explicit AWS credentials from environment."
else
  log_info "Using native AWS credentials chain (~/.aws/credentials / default profile)."
fi

if [ -n "${BRAINSOS_INFRA_AWS_REGION:-}" ]; then
  export AWS_REGION="${BRAINSOS_INFRA_AWS_REGION}"
elif [ -z "${AWS_REGION:-}" ]; then
  export AWS_REGION="us-east-1"
fi


# 1. Install npm dependencies in infra/ if needed
if [ ! -d "${INFRA_DIR}/node_modules" ]; then
  log_info "Installing dependencies in infra/..."
  (cd "${INFRA_DIR}" && npm install)
fi

# 2. Install SST providers if needed
if [ ! -d "${INFRA_DIR}/.sst/platform" ]; then
  log_info "Installing SST platform providers in infra/..."
  (cd "${INFRA_DIR}" && npx sst install)
fi

# 3. Typecheck SST TypeScript constructs
log_info "Running TypeScript typecheck..."
(cd "${INFRA_DIR}" && npm run typecheck)
log_success "TypeScript check passed."

# 4. Deploy or Diff
if [ "${DRY_RUN}" = true ]; then
  log_info "Executing SST dry-run diff against AWS (${STAGE})..."
  (cd "${INFRA_DIR}" && npx sst diff --stage "${STAGE}" || log_info "Stage ready for initial deployment.")
  log_success "Dry run diff complete. No cloud changes applied."
  exit 0
fi

log_info "Deploying SST Ion platform infrastructure to AWS (${STAGE})..."
(cd "${INFRA_DIR}" && npx sst deploy --stage "${STAGE}")
log_success "Platform cloud infrastructure successfully deployed!"
