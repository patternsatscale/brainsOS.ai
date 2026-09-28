#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Memories Snapshot & Rollback Manager
# Backs up the pure OKF Markdown knowledge plane and manages retention
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
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
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

# Read data dir from .env if available
cd "${REPO_ROOT}"
DATA_DIR=$(grep -E '^BRAINSOS_AGENT_MEMORIES_DIR=' .env 2>/dev/null | head -n1 | cut -d '=' -f2- || echo "./data/agent_memories")
DATA_DIR="${DATA_DIR:-./data/agent_memories}"

if [[ "$DATA_DIR" != /* ]]; then
  MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  MEMORIES_DIR="${DATA_DIR}"
fi

BACKUP_DIR="${REPO_ROOT}/data/backups"
mkdir -p "${BACKUP_DIR}"

# ------------------------------------------------------------------------------
# Handle Restore Mode
# ------------------------------------------------------------------------------
if [ "${1:-}" = "--restore" ]; then
  if [ -z "${2:-}" ] || [ ! -f "${2}" ]; then
    log_error "Usage: $0 --restore <path-to-snapshot.tar.gz>"
    exit 1
  fi
  SNAPSHOT_FILE="$2"
  log_warn "Restoring memories from: ${SNAPSHOT_FILE}"
  log_warn "Target directory: ${MEMORIES_DIR}"
  read -p "Are you sure you want to overwrite current memories? (y/N): " -r CONFIRM
  if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    mkdir -p "${MEMORIES_DIR}"
    tar -xzf "${SNAPSHOT_FILE}" -C "${MEMORIES_DIR}"
    log_success "Memories successfully restored from ${SNAPSHOT_FILE}."
    exit 0
  else
    log_info "Restore cancelled."
    exit 0
  fi
fi

# ------------------------------------------------------------------------------
# Snapshot Creation
# ------------------------------------------------------------------------------
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SNAPSHOT_NAME="brainsos_memories_${TIMESTAMP}.tar.gz"
SNAPSHOT_PATH="${BACKUP_DIR}/${SNAPSHOT_NAME}"

if [ ! -d "${MEMORIES_DIR}" ]; then
  log_error "Memories directory does not exist: ${MEMORIES_DIR}"
  exit 1
fi

log_info "Creating snapshot of OKF memories from ${MEMORIES_DIR}..."

# Create compressed tarball excluding any temp files or sockets
tar -czf "${SNAPSHOT_PATH}" -C "${MEMORIES_DIR}" .

SNAPSHOT_SIZE=$(du -h "${SNAPSHOT_PATH}" | cut -f1)
log_success "Snapshot created: ${SNAPSHOT_NAME} (${SNAPSHOT_SIZE})"

# ------------------------------------------------------------------------------
# Snapshot Retention (Keep last 14 snapshots)
# ------------------------------------------------------------------------------
MAX_SNAPSHOTS=14
TOTAL_SNAPSHOTS=$(find "${BACKUP_DIR}" -name "brainsos_memories_*.tar.gz" | wc -l | tr -d ' ')

if [ "${TOTAL_SNAPSHOTS}" -gt "${MAX_SNAPSHOTS}" ]; then
  EXCESS=$((TOTAL_SNAPSHOTS - MAX_SNAPSHOTS))
  log_info "Pruning ${EXCESS} older snapshot(s) to maintain retention limit of ${MAX_SNAPSHOTS}..."
  find "${BACKUP_DIR}" -name "brainsos_memories_*.tar.gz" -type f | sort | head -n "${EXCESS}" | xargs rm -f
  log_success "Old snapshots pruned."
fi
