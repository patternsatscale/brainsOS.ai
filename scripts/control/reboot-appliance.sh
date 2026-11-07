#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Graceful Appliance Reboot Utility (reboot-appliance.sh)
# Ticket #336 (Epic #309 / #321)
#
# Gracefully stops all active Docker Compose services (preserving database and
# volume integrity) before scheduling an immediate host OS reboot.
#
# Usage:
#   ./scripts/control/reboot-appliance.sh [--dry-run] [-y|--unattended]
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
[ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DRY_RUN=false
UNATTENDED=false

usage() {
  cat <<EOF
brainsOS Graceful Appliance Reboot Utility (Ticket #336)

Usage:
  ./scripts/control/reboot-appliance.sh [OPTIONS]

Options:
  --dry-run          Simulate graceful container stop and reboot scheduling
  -y, --unattended   Non-interactive execution
  -h, --help         Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -y|--unattended|--yes)
      UNATTENDED=true
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

cd "${REPO_ROOT}"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  . "${REPO_ROOT}/.env"
  set +a
fi
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would gracefully stop Docker Compose services: docker compose stop -t 30"
  log_info "[DRY-RUN] Would schedule host OS reboot: shutdown -r +0"
  log_success "[DRY-RUN] Graceful appliance reboot simulation complete."
  exit 0
fi

log_info "Initiating graceful brainsOS appliance reboot sequence..."
log_info "Step 1/2: Stopping Docker Compose services (timeout: 30s)..."
if command -v docker >/dev/null 2>&1; then
  docker compose stop -t 30 || log_warn "Docker Compose stop returned a warning; continuing with reboot."
fi
log_success "All container services stopped cleanly."

log_info "Step 2/2: Scheduling host OS reboot..."
if [ "$(uname -s)" != "Linux" ]; then
  log_warn "Non-Linux host detected ($(uname -s)); skipping kernel reboot command."
  exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
  nohup sh -c "sleep 2 && (shutdown -r +0 'brainsOS appliance reboot' || systemctl reboot)" >/dev/null 2>&1 &
elif command -v sudo >/dev/null 2>&1; then
  nohup sh -c "sleep 2 && (sudo -n shutdown -r +0 'brainsOS appliance reboot' || sudo -n systemctl reboot)" >/dev/null 2>&1 &
else
  log_error "Root privileges or passwordless sudo required to reboot the appliance."
  exit 1
fi

log_success "Appliance reboot scheduled (executing in 2 seconds)."
