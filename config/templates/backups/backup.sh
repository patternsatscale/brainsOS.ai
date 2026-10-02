#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Standalone Data Plane Backup Utility
# Self-contained backup tool for external private fleet data repositories.
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

BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_ROOT="$(cd "${BACKUP_DIR}/.." && pwd)"

MAX_BACKUPS="${MAX_BACKUPS:-14}"

show_help() {
  echo -e "${BOLD}brainsOS Standalone Data Plane Backup Utility${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --retention <num>   Maximum number of backup archives to keep (default: 14)"
  echo "  --list, -l          List existing backup archives and sizes"
  echo "  --help, -h          Display this help documentation"
  echo ""
  echo "Data Planes Backed Up:"
  echo "  - Memories:   ${DATA_ROOT}/agent_memories"
  echo "  - Souls:      ${DATA_ROOT}/souls"
  echo "  - Settings:   ${DATA_ROOT}/settings"
  echo "  - Workspaces: ${DATA_ROOT}/agent_workspaces"
  echo "  - Agent Apps: ${DATA_ROOT}/agent_apps"
  echo "  - Comms:      ${DATA_ROOT}/comms"
  echo "  - Database:   ${DATA_ROOT}/control_plane/litellm_db"
  echo "  - Destination:${BACKUP_DIR}"
}

list_backups() {
  echo -e "${BOLD}Available Backup Archives in ${BACKUP_DIR}:${NC}"
  echo "------------------------------------------------------------------"
  local count=0
  while IFS= read -r archive; do
    if [ -n "${archive}" ] && [ -f "${archive}" ]; then
      local size
      size=$(du -h "${archive}" | cut -f1)
      local mod_date
      mod_date=$(date -r "${archive}" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || stat -c "%y" "${archive}" 2>/dev/null || echo "Unknown")
      echo -e "${GREEN}$(basename "${archive}")${NC} (${size}) - ${mod_date}"
      count=$((count + 1))
    fi
  done < <(find "${BACKUP_DIR}" -name "brainsos_data_*.tar.gz" -type f | sort -r)

  if [ "${count}" -eq 0 ]; then
    echo "No backup archives found."
  fi
  echo "------------------------------------------------------------------"
}

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      show_help
      exit 0
      ;;
    --list|-l)
      list_backups
      exit 0
      ;;
    --retention)
      if [[ -n "${2:-}" ]] && [[ "$2" =~ ^[0-9]+$ ]]; then
        MAX_BACKUPS="$2"
        shift 2
      else
        log_error "Option --retention requires a numeric argument."
        exit 1
      fi
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
ARCHIVE_NAME="brainsos_data_${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"

log_info "Initializing standalone brainsOS data plane backup..."
log_info "Target Data Root: ${DATA_ROOT}"
log_info "Backup Archive:   ${ARCHIVE_PATH}"

# Create staging directory
STAGING_DIR=$(mktemp -d -t brainsos_backup_stage_XXXXXX 2>/dev/null || mktemp -d /tmp/brainsos_backup_stage_XXXXXX)
cleanup() {
  if [ -d "${STAGING_DIR}" ]; then
    rm -rf "${STAGING_DIR}"
  fi
}
trap cleanup EXIT

# 1. Package Open Knowledge Format (OKF) Memories
if [ -d "${DATA_ROOT}/agent_memories" ]; then
  log_info "  [+] Packaging Memories (agent_memories)..."
  mkdir -p "${STAGING_DIR}/agent_memories"
  cp -a "${DATA_ROOT}/agent_memories/." "${STAGING_DIR}/agent_memories/" 2>/dev/null || true
fi

# 2. Package Souls (Agent Personas)
if [ -d "${DATA_ROOT}/souls" ]; then
  log_info "  [+] Packaging Souls (souls)..."
  mkdir -p "${STAGING_DIR}/souls"
  cp -a "${DATA_ROOT}/souls/." "${STAGING_DIR}/souls/" 2>/dev/null || true
fi

# 3. Package Settings & Fleet Manifests
if [ -d "${DATA_ROOT}/settings" ]; then
  log_info "  [+] Packaging Fleet Settings (settings)..."
  mkdir -p "${STAGING_DIR}/settings"
  cp -a "${DATA_ROOT}/settings/." "${STAGING_DIR}/settings/" 2>/dev/null || true
fi

# 4. Package Agent Workspaces
if [ -d "${DATA_ROOT}/agent_workspaces" ]; then
  log_info "  [+] Packaging Workspaces (agent_workspaces)..."
  mkdir -p "${STAGING_DIR}/agent_workspaces"
  cp -a "${DATA_ROOT}/agent_workspaces/." "${STAGING_DIR}/agent_workspaces/" 2>/dev/null || true
fi

# 5. Package Agent Applications (e.g. Cindy Pawford site)
if [ -d "${DATA_ROOT}/agent_apps" ]; then
  log_info "  [+] Packaging Agent Apps (agent_apps)..."
  mkdir -p "${STAGING_DIR}/agent_apps"
  cp -a "${DATA_ROOT}/agent_apps/." "${STAGING_DIR}/agent_apps/" 2>/dev/null || true
fi

# 6. Package Communications Plane
if [ -d "${DATA_ROOT}/comms" ]; then
  log_info "  [+] Packaging Communications Plane (comms)..."
  mkdir -p "${STAGING_DIR}/comms"
  cp -a "${DATA_ROOT}/comms/." "${STAGING_DIR}/comms/" 2>/dev/null || true
fi

# 7. Package LiteLLM Database
DB_SOURCE="${DATA_ROOT}/control_plane/litellm_db"
if [ ! -d "${DB_SOURCE}" ] && [ -d "${DATA_ROOT}/litellm_db" ]; then
  DB_SOURCE="${DATA_ROOT}/litellm_db"
fi
if [ -d "${DB_SOURCE}" ]; then
  log_info "  [+] Packaging Control Plane Database (${DB_SOURCE})..."
  mkdir -p "${STAGING_DIR}/control_plane/litellm_db"
  cp -a "${DB_SOURCE}/." "${STAGING_DIR}/control_plane/litellm_db/" 2>/dev/null || true
fi

# Exclude runtime sockets and pid files from staging
find "${STAGING_DIR}" -type s -delete 2>/dev/null || true
find "${STAGING_DIR}" -type f -name "*.pid" -delete 2>/dev/null || true
find "${STAGING_DIR}" -type f -name "*.sock" -delete 2>/dev/null || true
find "${STAGING_DIR}" -type f -name "*.lock" -delete 2>/dev/null || true

# Compress staging directory into target archive
log_info "Compressing data planes into ${ARCHIVE_NAME}..."
tar -czf "${ARCHIVE_PATH}" -C "${STAGING_DIR}" .

# Verify archive integrity
if tar -tzf "${ARCHIVE_PATH}" >/dev/null 2>&1; then
  ARCHIVE_SIZE=$(du -h "${ARCHIVE_PATH}" | cut -f1)
  log_success "Backup completed successfully: ${ARCHIVE_NAME} (${ARCHIVE_SIZE})"
  log_success "Stored at: ${ARCHIVE_PATH}"
else
  log_error "Archive creation failed or generated corrupted tarball."
  rm -f "${ARCHIVE_PATH}"
  exit 1
fi

# Prune old backups beyond retention threshold
log_info "Enforcing retention policy (keeping last ${MAX_BACKUPS} archives)..."
OLD_BACKUPS=$(find "${BACKUP_DIR}" -name "brainsos_data_*.tar.gz" -type f | sort | head -n -"${MAX_BACKUPS}" 2>/dev/null || true)
if [ -n "${OLD_BACKUPS}" ]; then
  echo "${OLD_BACKUPS}" | while IFS= read -r old_file; do
    if [ -f "${old_file}" ]; then
      log_warn "Pruning aged backup: $(basename "${old_file}")"
      rm -f "${old_file}"
    fi
  done
fi

log_success "Backup process finished."
