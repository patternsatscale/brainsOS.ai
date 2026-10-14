#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Environment Teardown & Clean Slate Reset Script
# Stops all containers, removes Docker volumes and networks, terminates host
# background daemons, and removes runtime data and .env for a fresh install test.
# ==============================================================================

set -euo pipefail

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
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Parse options
FORCE=false
INCLUDE_DATA=false
KEEP_ENV=false
REMOVE_IMAGES=false
REMOVE_VENV=false

show_help() {
  echo -e "${BOLD}brainsOS Environment Destroy & Clean Slate Reset${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  -f, --force       Skip confirmation prompt (non-interactive)"
  echo "  --include-data    Also delete runtime data directory (BRAINSOS_DATA_DIR) [default: preserved]"
  echo "  --keep-data       Explicitly preserve runtime data directory (default behavior)"
  echo "  --keep-env        Preserve .env configuration file"
  echo "  --images          Also remove all local brainsos-* Docker images"
  echo "  --venv            Also delete Python .venv virtual environment"
  echo "  -h, --help        Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--force)
      FORCE=true
      shift
      ;;
    --include-data|--wipe-data|--with-data)
      INCLUDE_DATA=true
      shift
      ;;
    --keep-data)
      INCLUDE_DATA=false
      shift
      ;;
    --keep-env)
      KEEP_ENV=true
      shift
      ;;
    --images)
      REMOVE_IMAGES=true
      shift
      ;;
    --venv)
      REMOVE_VENV=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_warn "Unknown option: $1 (ignoring)"
      shift
      ;;
  esac
done

# Resolve data directory from .env if present
DATA_DIR="${BRAINSOS_DATA_DIR:-}"
if [ -f .env ]; then
  RESOLVED_DATA=$(grep "^BRAINSOS_DATA_DIR=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
  if [ -n "${RESOLVED_DATA}" ]; then
    DATA_DIR="${RESOLVED_DATA}"
  fi
fi
if [ -z "${DATA_DIR}" ]; then
  if [ -d "${REPO_ROOT}/../data" ]; then
    DATA_DIR="../data"
  else
    DATA_DIR="./data"
  fi
fi
if [[ "${DATA_DIR}" != /* ]]; then
  DATA_DIR="$(cd "${REPO_ROOT}" && cd "${DATA_DIR}" 2>/dev/null && pwd || echo "${REPO_ROOT}/${DATA_DIR#./}")"
fi

echo -e "${BOLD}======================================================================${NC}"
echo -e "${BOLD}brainsOS: Environment Reset & Clean Slate Reset                       ${NC}"
echo -e "${BOLD}======================================================================${NC}"
echo -e "Target Root: ${REPO_ROOT}"
echo -e "Data Dir:    ${DATA_DIR}"
echo ""

if [ "${FORCE}" != true ] && [ -t 0 ]; then
  echo -e "${YELLOW}${BOLD}WARNING:${NC} This will reset the brainsOS platform state:"
  echo "  - Stop and remove all 21 brainsOS Docker containers"
  echo "  - Delete all Docker volumes and isolated bridge networks"
  echo "  - Terminate background host processes (Ollama, Queue Worker, DGX bridge)"
  if [ "${INCLUDE_DATA}" = true ]; then
    echo -e "  - ${RED}Delete all runtime data in: ${DATA_DIR}${NC}"
  else
    echo -e "  - ${GREEN}Runtime data PRESERVED in: ${DATA_DIR} (use --include-data to wipe)${NC}"
  fi
  if [ "${KEEP_ENV}" != true ]; then
    echo "  - Delete .env configuration file"
  else
    echo "  - .env configuration file PRESERVED"
  fi
  if [ "${REMOVE_IMAGES}" = true ]; then
    echo "  - Delete all local brainsos-* Docker images"
  fi
  echo ""
  read -r -p "Are you sure you want to proceed? [y/N]: " CONFIRM
  case "${CONFIRM}" in
    [yY][eE][sS]|[yY])
      echo ""
      ;;
    *)
      log_info "Operation cancelled by user."
      exit 0
      ;;
  esac
fi

# ------------------------------------------------------------------------------
# 1. Stop Host Control Plane & Background Daemons
# ------------------------------------------------------------------------------
log_info "Step 1/5: Terminating background host processes and control plane..."

if [ -x "${REPO_ROOT}/scripts/control/start-control-plane.sh" ]; then
  "${REPO_ROOT}/scripts/control/start-control-plane.sh" stop 2>/dev/null || true
fi

# Terminate any lingering background workers or host engines
pkill -f "brainsos_agent.worker" 2>/dev/null || true
pkill -f "litellm" 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
pkill -9 -f "brainsos" 2>/dev/null || true

# Remove PID and lock files
if [ -d "${DATA_DIR}/control_plane" ]; then
  rm -f "${DATA_DIR}/control_plane/"*.pid "${DATA_DIR}/control_plane/"*.lock "${DATA_DIR}/control_plane/"*.log 2>/dev/null || true
fi

log_success "Host background processes terminated."

# ------------------------------------------------------------------------------
# 2. Stop and Tear Down Docker Compose Services, Volumes, and Networks
# ------------------------------------------------------------------------------
log_info "Step 2/5: Stopping and removing Docker containers, volumes, and networks..."

docker compose down -v --remove-orphans --timeout 10 2>/dev/null || true

# Force remove any residual brainsos containers
RESIDUAL_CONTAINERS=$(docker ps -a -q --filter "name=brainsos" 2>/dev/null || true)
if [ -n "${RESIDUAL_CONTAINERS}" ]; then
  log_info "Cleaning residual containers: ${RESIDUAL_CONTAINERS}"
  docker rm -f ${RESIDUAL_CONTAINERS} 2>/dev/null || true
fi

# Remove brainsos volumes
RESIDUAL_VOLUMES=$(docker volume ls -q --filter "name=brainsos" 2>/dev/null || true)
if [ -n "${RESIDUAL_VOLUMES}" ]; then
  log_info "Cleaning Docker volumes..."
  docker volume rm -f ${RESIDUAL_VOLUMES} 2>/dev/null || true
fi

# Remove brainsos networks
RESIDUAL_NETWORKS=$(docker network ls -q --filter "name=brainsos" 2>/dev/null || true)
if [ -n "${RESIDUAL_NETWORKS}" ]; then
  log_info "Cleaning Docker networks..."
  docker network rm ${RESIDUAL_NETWORKS} 2>/dev/null || true
fi

log_success "Docker containers, volumes, and networks removed."

# ------------------------------------------------------------------------------
# 3. Clean Runtime Data Directory (Preserved by default; only wiped if --include-data)
# ------------------------------------------------------------------------------
if [ "${INCLUDE_DATA}" = true ]; then
  log_info "Step 3/5: Removing runtime data directories (--include-data specified)..."
  if [ -d "${DATA_DIR}" ]; then
    if [ -d "${DATA_DIR}/.git" ]; then
      log_warn "Data directory is a git repository (${DATA_DIR}). Preserving git repository root and cleaning subfolders..."
      rm -rf "${DATA_DIR}/control_plane" \
             "${DATA_DIR}/comms" \
             "${DATA_DIR}/queue" \
             "${DATA_DIR}/telemetry" \
             "${DATA_DIR}/agents"/*/workspace \
             "${DATA_DIR}/agents/bawtford/apps/cindypawford/site" \
             "${DATA_DIR}/agent_workspaces" \
             "${DATA_DIR}/agent_apps/cindypawford/site" \
             "${DATA_DIR}/.vscode" 2>/dev/null || true
    else
      rm -rf "${DATA_DIR}"
    fi
    log_success "Runtime data cleaned (${DATA_DIR})."
  else
    log_info "Runtime data directory does not exist (${DATA_DIR})."
  fi
else
  log_info "Step 3/5: Preserving runtime data directory (${DATA_DIR})."
  log_info "        (To delete runtime data, rerun with: make destroy ARGS=\"--include-data\")"
fi

# ------------------------------------------------------------------------------
# 4. Clean Ephemeral Artifacts and .env
# ------------------------------------------------------------------------------
log_info "Step 4/5: Cleaning build artifacts and configuration files..."

# Portal compiled bundle
rm -rf "${REPO_ROOT}/packages/brainsOS-portal/dist"

# Caddy runtime state
rm -f "${REPO_ROOT}/config/caddy/autosave.json"

# Revert generated TLS policy to template default
if [ -f "${REPO_ROOT}/config/caddy/tls_policy.caddy" ]; then
  git -C "${REPO_ROOT}" checkout -- config/caddy/tls_policy.caddy 2>/dev/null || true
fi

# Remove .env if requested
if [ "${KEEP_ENV}" != true ]; then
  if [ -f "${REPO_ROOT}/.env" ]; then
    cp -f "${REPO_ROOT}/.env" "${REPO_ROOT}/.env.bak" 2>/dev/null || true
    rm -f "${REPO_ROOT}/.env"
    log_success "Removed .env configuration file (backed up to .env.bak)."
  fi
else
  log_info "Preserving .env configuration file (--keep-env)."
fi

# Optional: remove Python virtual environment
if [ "${REMOVE_VENV}" = true ] && [ -d "${REPO_ROOT}/.venv" ]; then
  log_info "Removing Python .venv virtual environment..."
  rm -rf "${REPO_ROOT}/.venv"
  log_success "Removed .venv."
fi

# ------------------------------------------------------------------------------
# 5. Optional Docker Images Clean
# ------------------------------------------------------------------------------
if [ "${REMOVE_IMAGES}" = true ]; then
  log_info "Step 5/5: Removing brainsOS Docker images..."
  BRAINSOS_IMAGES=$(docker images -q "brainsos-*" 2>/dev/null || true)
  if [ -n "${BRAINSOS_IMAGES}" ]; then
    docker rmi -f ${BRAINSOS_IMAGES} 2>/dev/null || true
  fi
  docker rmi -f brainsos-runner-base:latest 2>/dev/null || true
  log_success "brainsOS Docker images removed."
else
  log_info "Step 5/5: Preserving Docker images for fast rebuild (use --images to remove)."
fi

echo ""
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo -e "${GREEN}${BOLD}brainsOS: Environment Successfully Destroyed!                         ${NC}"
echo -e "${GREEN}${BOLD}======================================================================${NC}"
echo "The system is at a 100% clean-slate state."
echo ""
echo "To test a fresh setup from scratch, run:"
echo -e "  ${BOLD}make env${NC}     # or cp .env.example .env"
echo -e "  ${BOLD}make up${NC}      # starts all platform services"
echo -e "  ${BOLD}make urls${NC}    # displays all service endpoints & credentials"
echo ""
