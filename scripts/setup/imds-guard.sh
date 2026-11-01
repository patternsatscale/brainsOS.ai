#!/usr/bin/env bash
# ==============================================================================
# brainsOS: EC2 Instance Metadata Service (IMDS) Container Isolation Guard
# Ticket #330 (B6)
#
# Restricts container access to the AWS EC2 Instance Metadata Service
# (169.254.169.254/32) via the DOCKER-USER iptables chain:
#   - Only current IPv4 addresses of brainsos-control-litellm are allowed
#     (RETURN) so LiteLLM can fetch ambient Bedrock instance-role credentials.
#   - All other container traffic to 169.254.169.254/32 is dropped (DROP).
#   - If LiteLLM is not running, the chain fails closed (DROP only).
#   - Host processes use OUTPUT and are unaffected.
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
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

show_help() {
  cat <<EOF
Usage: scripts/setup/imds-guard.sh [--apply | --check | --remove] [--dry-run] [--force]
  --apply   (default) create/refresh chain BRAINSOS-IMDS and the DOCKER-USER jump
  --check   exit 0 only if the jump exists AND the chain ends with DROP AND every current LiteLLM IP has a RETURN rule
  --remove  delete the jump and the chain
  --dry-run print the iptables commands instead of executing them
  --force   run even when BRAINSOS_APPLIANCE != true
EOF
}

ACTION="apply"
DRY_RUN=false
FORCE=false

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)
      ACTION="apply"
      shift
      ;;
    --check)
      ACTION="check"
      shift
      ;;
    --remove)
      ACTION="remove"
      shift
      ;;
    --dry-run)
      DRY_RUN=false
      DRY_RUN=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

# No-op guard: Linux + iptables + (BRAINSOS_APPLIANCE=true or --force)
if [ "$(uname -s)" != "Linux" ] || ! command -v iptables >/dev/null 2>&1 || { [ "${FORCE}" != true ] && [ "${BRAINSOS_APPLIANCE:-false}" != "true" ]; }; then
  log_info "IMDS guard not applicable on this host; skipping."
  exit 0
fi

if [ "${DRY_RUN}" != true ] && [ "$(id -u)" -ne 0 ]; then
  log_error "Root privileges are required to ${ACTION} the IMDS iptables guard (run with sudo or --dry-run)."
  exit 1
fi

run_ipt() {
  if [ "${DRY_RUN}" = true ]; then
    echo "iptables $*"
  else
    iptables "$@"
  fi
}

RAW_IPS="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' brainsos-control-litellm 2>/dev/null || true)"
LITELLM_IPS=()
for ip in ${RAW_IPS}; do
  if [ -n "${ip}" ]; then
    LITELLM_IPS+=("${ip}")
  fi
done

case "${ACTION}" in
  apply)
    log_info "Applying IMDS container isolation guard (chain BRAINSOS-IMDS)..."
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -N BRAINSOS-IMDS
      run_ipt -F BRAINSOS-IMDS
      for ip in "${LITELLM_IPS[@]+"${LITELLM_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -A BRAINSOS-IMDS -s "${ip}/32" -j RETURN
        fi
      done
      run_ipt -A BRAINSOS-IMDS -j DROP
      run_ipt -N DOCKER-USER
      if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null; then
        run_ipt -I DOCKER-USER 1 -d 169.254.169.254/32 -j BRAINSOS-IMDS
      fi
    else
      iptables -N BRAINSOS-IMDS 2>/dev/null || true
      iptables -F BRAINSOS-IMDS
      for ip in "${LITELLM_IPS[@]+"${LITELLM_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          iptables -A BRAINSOS-IMDS -s "${ip}/32" -j RETURN
        fi
      done
      iptables -A BRAINSOS-IMDS -j DROP
      iptables -N DOCKER-USER 2>/dev/null || true
      iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null \
        || iptables -I DOCKER-USER 1 -d 169.254.169.254/32 -j BRAINSOS-IMDS
      log_info "Active BRAINSOS-IMDS rules:"
      iptables -S BRAINSOS-IMDS
    fi
    log_success "IMDS guard applied (${#LITELLM_IPS[@]} LiteLLM IP(s) allowed; all other containers dropped)."
    ;;

  check)
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS
      run_ipt -S BRAINSOS-IMDS
      exit 0
    fi
    if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null; then
      log_error "DOCKER-USER jump to BRAINSOS-IMDS is missing."
      exit 1
    fi
    CHAIN_RULES="$(iptables -S BRAINSOS-IMDS 2>/dev/null || true)"
    if [ -z "${CHAIN_RULES}" ]; then
      log_error "Chain BRAINSOS-IMDS does not exist or is empty."
      exit 1
    fi
    LAST_RULE="$(printf '%s\n' "${CHAIN_RULES}" | tail -n 1)"
    if [ "${LAST_RULE}" != "-A BRAINSOS-IMDS -j DROP" ]; then
      log_error "Chain BRAINSOS-IMDS does not end with -j DROP (last rule: ${LAST_RULE})."
      exit 1
    fi
    for ip in "${LITELLM_IPS[@]+"${LITELLM_IPS[@]}"}"; do
      if [ -n "${ip}" ]; then
        if ! iptables -C BRAINSOS-IMDS -s "${ip}/32" -j RETURN 2>/dev/null; then
          log_error "Missing RETURN rule in BRAINSOS-IMDS for LiteLLM IP ${ip}/32."
          exit 1
        fi
      fi
    done
    log_success "IMDS guard verified: jump present, ${#LITELLM_IPS[@]} LiteLLM IP(s) permitted, ending with DROP."
    ;;

  remove)
    log_info "Removing IMDS container isolation guard..."
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS
      run_ipt -F BRAINSOS-IMDS
      run_ipt -X BRAINSOS-IMDS
    else
      while iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null; do
        iptables -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null || break
      done
      iptables -F BRAINSOS-IMDS 2>/dev/null || true
      iptables -X BRAINSOS-IMDS 2>/dev/null || true
    fi
    log_success "IMDS guard removed."
    ;;
esac

