#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Unified Data Plane Backup & Restore Manager
# Backs up the entire Titan data layout (memories, workspace, and database)
# into timestamped gzip archives with retention pruning and safe restoration.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Load environment configuration
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

# Resolve directories
resolve_path() {
  local path_var="$1"
  local default_path="$2"
  local val="${path_var:-$default_path}"
  if [[ "$val" != /* ]]; then
    echo "${REPO_ROOT}/${val#./}"
  else
    echo "${val}"
  fi
}

MEMORIES_DIR=$(resolve_path "${TITAN_DATA_DIR:-}" "./data/memories")
WORKSPACE_DIR=$(resolve_path "${TITAN_WORKSPACE_DIR:-}" "./data/workspace")
DB_DIR=$(resolve_path "${LITELLM_DB_DATA_DIR:-}" "./data/litellm_db")
DATA_ROOT="${REPO_ROOT}/data"
BACKUP_DIR="${DATA_ROOT}/backups"
MAX_BACKUPS="${MAX_BACKUPS:-14}"

mkdir -p "${BACKUP_DIR}"

# ------------------------------------------------------------------------------
# Help & Usage
# ------------------------------------------------------------------------------
show_help() {
  echo -e "${BOLD}Project Titan Unified Backup & Restore Utility${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --backup              Create a timestamped compressed archive of all data (default)"
  echo "  --restore <archive>   Restore all data planes from a tar.gz archive"
  echo "  --list                List all available archives in the backup directory"
  echo "  --force, -f           Bypass interactive confirmation during restore"
  echo "  --help, -h            Show this help documentation"
  echo ""
  echo "Target Data Planes:"
  echo "  - Memories Plane:  ${MEMORIES_DIR}"
  echo "  - Workspace Plane: ${WORKSPACE_DIR}"
  echo "  - Database Plane:  ${DB_DIR}"
  echo "  - Backup Storage:  ${BACKUP_DIR}"
  echo ""
}

# ------------------------------------------------------------------------------
# List Backups
# ------------------------------------------------------------------------------
list_backups() {
  echo -e "${BOLD}Available Titan Data Archives in ${BACKUP_DIR}:${NC}"
  echo "--------------------------------------------------------------------------------"
  local count=0
  for archive in "${BACKUP_DIR}"/titan_data_*.tar.gz; do
    if [ -f "${archive}" ]; then
      count=$((count + 1))
      local size
      size=$(du -h "${archive}" | cut -f1)
      local modified
      modified=$(date -r "${archive}" +"%Y-%m-%d %H:%M:%S" 2>/dev/null || stat -c "%y" "${archive}" 2>/dev/null | cut -d'.' -f1 || echo "unknown")
      printf "  [%02d] %-40s | %8s | %s\n" "${count}" "$(basename "${archive}")" "${size}" "${modified}"
    fi
  done

  if [ "${count}" -eq 0 ]; then
    echo "  (No archives found in ${BACKUP_DIR})"
  fi
  echo "--------------------------------------------------------------------------------"
  echo "Total archives: ${count} (Retention limit: ${MAX_BACKUPS})"
}

# ------------------------------------------------------------------------------
# Create Backup
# ------------------------------------------------------------------------------
create_backup() {
  local timestamp
  timestamp=$(date +"%Y%m%d_%H%M%S")
  local archive_name="titan_data_${timestamp}.tar.gz"
  local archive_path="${BACKUP_DIR}/${archive_name}"
  local staging_dir
  staging_dir=$(mktemp -d "${TMPDIR:-/tmp}/titan_backup_XXXXXX")

  log_info "Initializing Project Titan full data plane backup..."
  log_info "Packaging planes:"
  log_info "  - Memories:  ${MEMORIES_DIR}"
  log_info "  - Workspace: ${WORKSPACE_DIR}"
  log_info "  - Database:  ${DB_DIR}"

  mkdir -p "${staging_dir}/memories"
  mkdir -p "${staging_dir}/workspace"
  mkdir -p "${staging_dir}/litellm_db"

  # 1. Copy memories if present
  if [ -d "${MEMORIES_DIR}" ]; then
    cp -a "${MEMORIES_DIR}/." "${staging_dir}/memories/" 2>/dev/null || true
  fi

  # 2. Copy workspace if present
  if [ -d "${WORKSPACE_DIR}" ]; then
    cp -a "${WORKSPACE_DIR}/." "${staging_dir}/workspace/" 2>/dev/null || true
  fi

  # 3. Copy database if present and readable
  if [ -d "${DB_DIR}" ]; then
    cp -a "${DB_DIR}/." "${staging_dir}/litellm_db/" 2>/dev/null || true
  fi

  # Write backup manifest
  cat <<EOF > "${staging_dir}/manifest.json"
{
  "timestamp": "${timestamp}",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "version": "1.0.0",
  "planes": {
    "memories": "${MEMORIES_DIR}",
    "workspace": "${WORKSPACE_DIR}",
    "litellm_db": "${DB_DIR}"
  }
}
EOF

  log_info "Compressing data planes into ${archive_name}..."
  tar -czf "${archive_path}" \
    --exclude=".DS_Store" \
    --exclude="*.sock" \
    --exclude="*.pid" \
    -C "${staging_dir}" .

  rm -rf "${staging_dir}"

  local size
  size=$(du -h "${archive_path}" | cut -f1)
  log_success "Backup completed successfully: ${archive_name} (${size})"
  log_success "Stored at: ${archive_path}"

  # Enforce retention policy
  prune_retention
}

# ------------------------------------------------------------------------------
# Prune Retention
# ------------------------------------------------------------------------------
prune_retention() {
  local total_backups
  total_backups=$(find "${BACKUP_DIR}" -maxdepth 1 -name "titan_data_*.tar.gz" | wc -l | tr -d ' ')

  if [ "${total_backups}" -gt "${MAX_BACKUPS}" ]; then
    local excess=$((total_backups - MAX_BACKUPS))
    log_info "Pruning ${excess} oldest archive(s) to enforce retention limit of ${MAX_BACKUPS}..."
    find "${BACKUP_DIR}" -maxdepth 1 -name "titan_data_*.tar.gz" -type f | sort | head -n "${excess}" | while read -r old_file; do
      rm -f "${old_file}"
      log_info "  Pruned: $(basename "${old_file}")"
    done
    log_success "Backup retention policy enforced."
  fi
}

# ------------------------------------------------------------------------------
# Restore Backup
# ------------------------------------------------------------------------------
restore_backup() {
  local archive_file="$1"
  local force="${2:-false}"

  if [ ! -f "${archive_file}" ]; then
    log_error "Specified archive does not exist: ${archive_file}"
    exit 1
  fi

  # Test archive integrity
  log_info "Testing archive integrity: $(basename "${archive_file}")..."
  if ! tar -tzf "${archive_file}" >/dev/null 2>&1; then
    log_error "Archive file is corrupt or not a valid gzip tarball: ${archive_file}"
    exit 1
  fi
  log_success "Archive integrity verified."

  echo -e "${YELLOW}${BOLD}WARNING: Restoring data will overwrite existing files in:${NC}"
  echo "  - ${MEMORIES_DIR}"
  echo "  - ${WORKSPACE_DIR}"
  echo "  - ${DB_DIR}"
  echo ""

  if [ "${force}" != true ]; then
    read -p "Are you sure you want to proceed with restoration? (y/N): " -r CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
      log_info "Restoration cancelled by user."
      exit 0
    fi
  fi

  log_info "Unpacking archive into target data planes..."
  local extract_dir
  extract_dir=$(mktemp -d "${TMPDIR:-/tmp}/titan_restore_XXXXXX")
  tar -xzf "${archive_file}" -C "${extract_dir}"

  if [ -d "${extract_dir}/memories" ]; then
    mkdir -p "${MEMORIES_DIR}"
    cp -a "${extract_dir}/memories/." "${MEMORIES_DIR}/" 2>/dev/null || true
    log_success "Restored memories plane."
  fi

  if [ -d "${extract_dir}/workspace" ]; then
    mkdir -p "${WORKSPACE_DIR}"
    cp -a "${extract_dir}/workspace/." "${WORKSPACE_DIR}/" 2>/dev/null || true
    chmod 775 "${WORKSPACE_DIR}" || true
    log_success "Restored workspace plane."
  fi

  if [ -d "${extract_dir}/litellm_db" ]; then
    mkdir -p "${DB_DIR}"
    cp -a "${extract_dir}/litellm_db/." "${DB_DIR}/" 2>/dev/null || true
    chmod 700 "${DB_DIR}" || true
    log_success "Restored database plane."
  fi

  rm -rf "${extract_dir}"
  log_success "Titan data planes successfully restored from ${archive_file}."
}

# ------------------------------------------------------------------------------
# Entrypoint & CLI Parsing
# ------------------------------------------------------------------------------
ACTION="backup"
ARCHIVE_ARG=""
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup)
      ACTION="backup"
      shift
      ;;
    --restore)
      ACTION="restore"
      ARCHIVE_ARG="${2:-}"
      if [ -z "${ARCHIVE_ARG}" ]; then
        log_error "Option --restore requires an archive file path."
        exit 1
      fi
      shift 2
      ;;
    --list)
      ACTION="list"
      shift
      ;;
    --force|-f)
      FORCE=true
      shift
      ;;
    --help|-h)
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

case "${ACTION}" in
  backup)
    create_backup
    ;;
  restore)
    restore_backup "${ARCHIVE_ARG}" "${FORCE}"
    ;;
  list)
    list_backups
    ;;
esac
