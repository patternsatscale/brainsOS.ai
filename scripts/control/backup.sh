#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Unified Data Plane Backup & Restore Manager
# Backs up the entire brainsOS data layout (memories, workspace, and database)
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
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
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

cd "${REPO_ROOT}"

# Load environment configuration
_EXPLICIT_DATA_DIR="${BRAINSOS_DATA_DIR:-}"
if [ ! -f "${REPO_ROOT}/.env" ]; then
  log_error "Missing .env configuration in ${REPO_ROOT}. An initialized .env is required (Rule 13)."
  exit 1
fi
set -a
. "${REPO_ROOT}/.env"
set +a
if [ -n "${_EXPLICIT_DATA_DIR}" ]; then
  BRAINSOS_DATA_DIR="${_EXPLICIT_DATA_DIR}"
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

DATA_ROOT=$(resolve_path "${BRAINSOS_DATA_DIR:-}" "./data")
AGENTS_DIR=$(resolve_path "${BRAINSOS_AGENTS_DIR:-}" "${DATA_ROOT}/agents")
MEMORIES_DIR=$(resolve_path "${BRAINSOS_AGENT_MEMORIES_DIR:-}" "${DATA_ROOT}/agent_memories")
WORKSPACE_DIR=$(resolve_path "${BRAINSOS_AGENT_WORKSPACES_DIR:-}" "${DATA_ROOT}/agent_workspaces")
COMMS_DIR=$(resolve_path "${BRAINSOS_COMMS_DIR:-}" "${DATA_ROOT}/comms")
DB_DIR=$(resolve_path "${LITELLM_DB_DATA_DIR:-}" "${DATA_ROOT}/control_plane/litellm_db")
if [ ! -d "${DB_DIR}" ] && [ -d "${REPO_ROOT}/data/litellm_db" ]; then
  DB_DIR="${REPO_ROOT}/data/litellm_db"
fi
BACKUP_DIR="${DATA_ROOT}/backups"
MAX_BACKUPS="${MAX_BACKUPS:-14}"

mkdir -p "${BACKUP_DIR}"

# ------------------------------------------------------------------------------
# Help & Usage
# ------------------------------------------------------------------------------
show_help() {
  echo -e "${BOLD}brainsOS Unified Backup & Restore Utility${NC}"
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
  echo "  - Comms Plane:     ${COMMS_DIR}"
  echo "  - Database Plane:  ${DB_DIR}"
  echo "  - Backup Storage:  ${BACKUP_DIR}"
  echo ""
}

# ------------------------------------------------------------------------------
# List Backups
# ------------------------------------------------------------------------------
list_backups() {
  echo -e "${BOLD}Available brainsOS Data Archives in ${BACKUP_DIR}:${NC}"
  echo "--------------------------------------------------------------------------------"
  local count=0
  for archive in "${BACKUP_DIR}"/brainsos_data_*.tar.gz; do
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
  local archive_name="brainsos_data_${timestamp}.tar.gz"
  local archive_path="${BACKUP_DIR}/${archive_name}"
  local staging_dir
  staging_dir=$(mktemp -d "${TMPDIR:-/tmp}/brainsos_backup_XXXXXX")

  log_info "Initializing brainsOS full data plane backup..."
  log_info "Packaging planes:"
  log_info "  - Agents:    ${AGENTS_DIR}"
  log_info "  - Memories:  ${MEMORIES_DIR}"
  log_info "  - Workspace: ${WORKSPACE_DIR}"
  log_info "  - Comms:     ${COMMS_DIR}"
  log_info "  - Databases: Logical pg_dump of active Postgres services"

  mkdir -p "${staging_dir}/agents"
  mkdir -p "${staging_dir}/memories"
  mkdir -p "${staging_dir}/workspace"
  mkdir -p "${staging_dir}/comms"
  mkdir -p "${staging_dir}/db_dumps"

  # 0. Copy agents if present
  if [ -d "${AGENTS_DIR}" ]; then
    cp -a "${AGENTS_DIR}/." "${staging_dir}/agents/" 2>/dev/null || true
  fi

  # 1. Copy memories if present
  if [ -d "${MEMORIES_DIR}" ]; then
    cp -a "${MEMORIES_DIR}/." "${staging_dir}/memories/" 2>/dev/null || true
  elif [ -d "${REPO_ROOT}/data/memories" ]; then
    cp -a "${REPO_ROOT}/data/memories/." "${staging_dir}/memories/" 2>/dev/null || true
  fi

  # 2. Copy workspace if present
  if [ -d "${WORKSPACE_DIR}" ]; then
    cp -a "${WORKSPACE_DIR}/." "${staging_dir}/workspace/" 2>/dev/null || true
  elif [ -d "${REPO_ROOT}/data/workspace" ]; then
    cp -a "${REPO_ROOT}/data/workspace/." "${staging_dir}/workspace/" 2>/dev/null || true
  fi

  # 3. Copy comms if present
  if [ -d "${COMMS_DIR}" ]; then
    cp -a "${COMMS_DIR}/." "${staging_dir}/comms/" 2>/dev/null || true
  fi

  # 4. Logical database dumps for all running Postgres containers (Rule 6: credentials from container env)
  local active_dbs=()
  for db_svc in litellm-db langfuse-db authentik-db sogo-db; do
    local cid
    cid="$(docker compose ps -q "${db_svc}" 2>/dev/null || true)"
    if [ -n "${cid}" ]; then
      local is_running
      is_running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || echo "false")"
      if [ "${is_running}" = "true" ]; then
        log_info "Creating logical dump for ${db_svc} via pg_dump..."
        if docker compose exec -T "${db_svc}" sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "${staging_dir}/db_dumps/${db_svc}.sql" 2>/dev/null; then
          local dsize
          dsize=$(du -h "${staging_dir}/db_dumps/${db_svc}.sql" | cut -f1)
          log_success "Logical dump created for ${db_svc} (${dsize})."
          active_dbs+=("${db_svc}")
        else
          log_error "Failed to generate logical database dump for ${db_svc}."
          rm -rf "${staging_dir}"
          exit 1
        fi
      fi
    fi
  done

  # Write backup manifest
  cat <<EOF > "${staging_dir}/manifest.json"
{
  "timestamp": "${timestamp}",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "version": "2.0.0",
  "planes": {
    "agents": "${AGENTS_DIR}",
    "memories": "${MEMORIES_DIR}",
    "workspace": "${WORKSPACE_DIR}",
    "comms": "${COMMS_DIR}",
    "databases": [$(printf '"%s",' "${active_dbs[@]}" | sed 's/,$//')]
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
  total_backups=$(find "${BACKUP_DIR}" -maxdepth 1 -name "brainsos_data_*.tar.gz" | wc -l | tr -d ' ')

  if [ "${total_backups}" -gt "${MAX_BACKUPS}" ]; then
    local excess=$((total_backups - MAX_BACKUPS))
    log_info "Pruning ${excess} oldest archive(s) to enforce retention limit of ${MAX_BACKUPS}..."
    find "${BACKUP_DIR}" -maxdepth 1 -name "brainsos_data_*.tar.gz" -type f | sort | head -n "${excess}" | while read -r old_file; do
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
  echo "  - ${AGENTS_DIR}"
  echo "  - ${MEMORIES_DIR}"
  echo "  - ${WORKSPACE_DIR}"
  echo "  - ${COMMS_DIR}"
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
  extract_dir=$(mktemp -d "${TMPDIR:-/tmp}/brainsos_restore_XXXXXX")
  tar -xzf "${archive_file}" -C "${extract_dir}"

  if [ -d "${extract_dir}/agents" ]; then
    mkdir -p "${AGENTS_DIR}"
    cp -a "${extract_dir}/agents/." "${AGENTS_DIR}/" 2>/dev/null || true
    log_success "Restored agents plane."
  fi

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

  if [ -d "${extract_dir}/comms" ]; then
    mkdir -p "${COMMS_DIR}"
    cp -a "${extract_dir}/comms/." "${COMMS_DIR}/" 2>/dev/null || true
    chmod 775 "${COMMS_DIR}" || true
    log_success "Restored communications plane."
  fi

  # Logical database restores
  if [ -d "${extract_dir}/db_dumps" ]; then
    for dump_file in "${extract_dir}/db_dumps/"*.sql; do
      if [ -f "${dump_file}" ]; then
        local db_svc
        db_svc="$(basename "${dump_file}" .sql)"
        log_info "Restoring logical database dump for ${db_svc}..."
        
        # Stop dependent services before database restore
        case "${db_svc}" in
          litellm-db)
            docker compose stop litellm 2>/dev/null || true
            ;;
          langfuse-db)
            docker compose stop langfuse-web langfuse-worker 2>/dev/null || true
            ;;
          authentik-db)
            docker compose stop authentik-server authentik-worker 2>/dev/null || true
            ;;
          sogo-db)
            docker compose stop sogo 2>/dev/null || true
            ;;
        esac

        # Ensure database container is up and ready
        docker compose up -d "${db_svc}" 2>/dev/null || true
        for _w in {1..30}; do
          if docker compose exec -T "${db_svc}" pg_isready >/dev/null 2>&1; then
            break
          fi
          sleep 1
        done

        # Recreate public schema and stream dump into psql
        docker compose exec -T "${db_svc}" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"' 2>/dev/null || true
        if docker compose exec -T "${db_svc}" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" --quiet' < "${dump_file}" 2>/dev/null; then
          log_success "Restored ${db_svc} from logical dump."
        else
          log_error "Failed to restore database for ${db_svc}."
          rm -rf "${extract_dir}"
          exit 1
        fi

        # Restart dependent services
        case "${db_svc}" in
          litellm-db)
            docker compose up -d litellm 2>/dev/null || true
            ;;
          langfuse-db)
            docker compose up -d langfuse-web langfuse-worker 2>/dev/null || true
            ;;
          authentik-db)
            docker compose up -d authentik-server authentik-worker 2>/dev/null || true
            ;;
          sogo-db)
            docker compose up -d sogo 2>/dev/null || true
            ;;
        esac
      fi
    done
  elif [ -d "${extract_dir}/litellm_db" ]; then
    # Legacy flat database directory fallback
    mkdir -p "${DB_DIR}"
    cp -a "${extract_dir}/litellm_db/." "${DB_DIR}/" 2>/dev/null || true
    chmod 700 "${DB_DIR}" || true
    log_success "Restored legacy litellm_db files."
  fi

  rm -rf "${extract_dir}"
  log_success "brainsOS data planes successfully restored from ${archive_file}."
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
        log_error "Option --restore requires an archive file path or 'latest'."
        exit 1
      fi
      if [ "${ARCHIVE_ARG}" = "latest" ]; then
        ARCHIVE_ARG="$(find "${BACKUP_DIR}" -maxdepth 1 -name "brainsos_data_*.tar.gz" -type f | sort | tail -n1 || true)"
        if [ -z "${ARCHIVE_ARG}" ] || [ ! -f "${ARCHIVE_ARG}" ]; then
          log_error "No backup archives found in ${BACKUP_DIR} to restore."
          exit 1
        fi
        log_info "Resolved 'latest' backup archive to: ${ARCHIVE_ARG}"
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
