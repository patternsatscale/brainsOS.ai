#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Standalone Data Plane Restore Utility
# Self-contained disaster recovery tool for external private fleet data repositories.
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

show_help() {
  echo -e "${BOLD}brainsOS Standalone Data Plane Restore Utility${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 <archive_file_or_path> [options]"
  echo "  $0 latest [options]"
  echo ""
  echo "Options:"
  echo "  --force, -f         Bypass interactive confirmation prompt"
  echo "  --dry-run           Inspect archive contents without modifying data"
  echo "  --no-snapshot       Skip creating safety pre-restore backup"
  echo "  --help, -h          Display this help documentation"
  echo ""
  echo "Target Restore Destination:"
  echo "  ${DATA_ROOT}"
}

ARCHIVE_INPUT=""
FORCE=false
DRY_RUN=false
CREATE_SAFETY_SNAPSHOT=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      show_help
      exit 0
      ;;
    --force|-f)
      FORCE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --no-snapshot)
      CREATE_SAFETY_SNAPSHOT=false
      shift
      ;;
    -*)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
    *)
      if [ -z "${ARCHIVE_INPUT}" ]; then
        ARCHIVE_INPUT="$1"
        shift
      else
        log_error "Unexpected argument: $1"
        show_help
        exit 1
      fi
      ;;
  esac
done

if [ -z "${ARCHIVE_INPUT}" ]; then
  log_error "No backup archive specified."
  show_help
  exit 1
fi

# Resolve archive path
if [ "${ARCHIVE_INPUT}" = "latest" ]; then
  RESOLVED_ARCHIVE=$(find "${BACKUP_DIR}" -name "brainsos_data_*.tar.gz" -type f | sort | tail -n 1)
  if [ -z "${RESOLVED_ARCHIVE}" ]; then
    log_error "No backup archives found in ${BACKUP_DIR}."
    exit 1
  fi
elif [ -f "${ARCHIVE_INPUT}" ]; then
  RESOLVED_ARCHIVE="${ARCHIVE_INPUT}"
elif [ -f "${BACKUP_DIR}/${ARCHIVE_INPUT}" ]; then
  RESOLVED_ARCHIVE="${BACKUP_DIR}/${ARCHIVE_INPUT}"
else
  log_error "Archive file not found: ${ARCHIVE_INPUT}"
  exit 1
fi

# Validate tarball integrity
log_info "Verifying archive integrity for: $(basename "${RESOLVED_ARCHIVE}")..."
if ! tar -tzf "${RESOLVED_ARCHIVE}" >/dev/null 2>&1; then
  log_error "Archive is corrupted or invalid gzip tarball: ${RESOLVED_ARCHIVE}"
  exit 1
fi

# Dry run inspection
if [ "${DRY_RUN}" = true ]; then
  echo -e "${BOLD}Archive Contents (Dry Run):${NC}"
  echo "------------------------------------------------------------------"
  tar -tzf "${RESOLVED_ARCHIVE}" | head -n 40
  echo "... [truncated]"
  echo "------------------------------------------------------------------"
  log_info "Dry run complete. No live files were modified."
  exit 0
fi

# Warn and confirm
log_warn "=================================================================="
log_warn "WARNING: Restoring will overwrite existing files in ${DATA_ROOT}:"
log_warn "  - agent_memories/"
log_warn "  - souls/"
log_warn "  - settings/"
log_warn "  - agent_workspaces/"
log_warn "  - agent_apps/"
log_warn "  - comms/"
log_warn "  - control_plane/litellm_db"
log_warn "Archive source: ${RESOLVED_ARCHIVE}"
log_warn "=================================================================="

if [ "${FORCE}" != true ]; then
  read -r -p "Are you sure you want to proceed with this restore? [y/N] " response
  case "${response}" in
    [yY][eE][sS]|[yY])
      ;;
    *)
      log_info "Restore cancelled by operator."
      exit 0
      ;;
  esac
fi

# Pre-restore safety snapshot
if [ "${CREATE_SAFETY_SNAPSHOT}" = true ] && [ -x "${BACKUP_DIR}/backup.sh" ]; then
  log_info "Creating pre-restore safety snapshot..."
  "${BACKUP_DIR}/backup.sh" || log_warn "Pre-restore snapshot failed; continuing with restore..."
fi

# Extract into staging area
STAGING_DIR=$(mktemp -d -t brainsos_restore_stage_XXXXXX 2>/dev/null || mktemp -d /tmp/brainsos_restore_stage_XXXXXX)
cleanup() {
  if [ -d "${STAGING_DIR}" ]; then
    rm -rf "${STAGING_DIR}"
  fi
}
trap cleanup EXIT

log_info "Extracting archive into temporary staging area..."
tar -xzf "${RESOLVED_ARCHIVE}" -C "${STAGING_DIR}"

# Atomic-style sync of data planes into DATA_ROOT
PLANES=("agent_memories" "souls" "settings" "agent_workspaces" "agent_apps" "comms" "control_plane")

for plane in "${PLANES[@]}"; do
  if [ -d "${STAGING_DIR}/${plane}" ]; then
    log_info "  [+] Restoring plane: ${plane}..."
    mkdir -p "${DATA_ROOT}/${plane}"
    cp -a "${STAGING_DIR}/${plane}/." "${DATA_ROOT}/${plane}/" 2>/dev/null || true
  fi
done

# Fix directory permissions
chmod -R 775 "${DATA_ROOT}/agent_memories" "${DATA_ROOT}/agent_workspaces" 2>/dev/null || true

log_success "=================================================================="
log_success "Restoration completed successfully from $(basename "${RESOLVED_ARCHIVE}")!"
log_success "Target Data Root: ${DATA_ROOT}"
log_success "=================================================================="
