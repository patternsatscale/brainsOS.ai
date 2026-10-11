#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Turnkey Appliance Installer (make install)
#
# 1. Configures .env with interactive domain prompts and secure passwords.
# 2. Bootstraps environment (scaffolds directories, venv, portal, & Docker images).
# 3. Displays the single unified Portal URL and SSO credentials.
# 4. Prompts the operator to run 'make up' to turn everything on.
# ==============================================================================

set -euo pipefail

# Visual styling
BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

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

cd "${REPO_ROOT}"

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║                         brainsOS Turnkey Installer                           ║${NC}"
echo -e "${CYAN}${BOLD}║              Autonomous AI Appliance & Multi-Agent Operating System          ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ------------------------------------------------------------------------------
# Phase 1: Environment & Credential Generation (make env)
# ------------------------------------------------------------------------------
echo -e "${BOLD}[Phase 1/3] Configuring Environment & Generating Cryptographic Keys${NC}"
echo -e "${DIM}Generating .env with custom domain and secure random passwords...${NC}"
echo ""

if [ -f "${SCRIPT_DIR}/generate-env.sh" ]; then
  "${SCRIPT_DIR}/generate-env.sh" --no-rebuild "$@"
else
  log_error "generate-env.sh script missing at ${SCRIPT_DIR}/generate-env.sh"
  exit 1
fi

echo ""
log_success "Phase 1 complete: Environment and credentials configured."
echo ""

# ------------------------------------------------------------------------------
# Phase 2: Environment Bootstrap (make setup)
# ------------------------------------------------------------------------------
echo -e "${BOLD}[Phase 2/3] Bootstrapping Runtime Data, Dependencies & Container Images${NC}"
echo -e "${DIM}Scaffolding storage planes, building portal SPA, and building Docker images...${NC}"
echo ""

if [ -f "${SCRIPT_DIR}/bootstrap-env.sh" ]; then
  "${SCRIPT_DIR}/bootstrap-env.sh"
else
  log_error "bootstrap-env.sh script missing at ${SCRIPT_DIR}/bootstrap-env.sh"
  exit 1
fi

echo ""
log_success "Phase 2 complete: Appliance bootstrap finished."
echo ""

# ------------------------------------------------------------------------------
# Phase 3: Appliance Portal URL & Single SSO Credential Presentation
# ------------------------------------------------------------------------------
echo -e "${BOLD}[Phase 3/3] Appliance Gateway & Portal Access${NC}"
echo ""

if [ -f "${SCRIPT_DIR}/show-urls.sh" ]; then
  "${SCRIPT_DIR}/show-urls.sh" --portal --no-hosts
fi

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  brainsOS Installation Successfully Completed!                                   ${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "To turn on all platform services and start your autonomous AI fleet, type:"
echo ""
echo -e "    ${BOLD}${CYAN}make up${NC}"
echo ""
echo -e "${DIM}Tip: You can inspect individual service health at any time with: make urls${NC}"
echo ""
