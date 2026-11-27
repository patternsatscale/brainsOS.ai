#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Cleanly Release & Unmount Persistent User EBS Volume
# Ticket #382
#
# Stops all platform containers and systemd services referencing the mounted
# user EBS volume, removes host-side symlinks (/opt/brainsos/.env and
# /opt/brainsos/.brainsos-initialized), flushes dirty filesystem buffers via
# sync, and unmounts the volume so AWS EC2 DetachVolume can proceed without
# risking Postgres, ClickHouse, Redis, or MinIO data corruption.
# ==============================================================================

set -euo pipefail

for sbin_dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
  if [ -d "${sbin_dir}" ] && [[ ":${PATH}:" != *":${sbin_dir}:"* ]]; then
    export PATH="${PATH}:${sbin_dir}"
  fi
done

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
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

MOUNT_PATH="${BRAINSOS_MOUNT_ROOT:-/mnt/brainsos-data}"
SUDOERS_FILE="${BRAINSOS_SUDOERS_FILE:-/etc/sudoers.d/90-brainsos-admin}"
SKIP_SERVICE_STOP=false
SKIP_UMOUNT=false
DRY_RUN=false

usage() {
  cat <<EOF
brainsOS Persistent User Volume Release & Unmount Engine (Ticket #382)

Usage:
  sudo ./scripts/control/release-user-volume.sh [OPTIONS]

Options:
  --mount <path>         Mount directory to release (default: /mnt/brainsos-data)
  --skip-service-stop    Skip stopping systemd units and Docker containers (tests)
  --skip-umount          Skip kernel umount syscall (pre-mounted dir / rootless tests)
  --dry-run              Simulate release steps without stopping services or unmounting
  -h, --help             Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mount|--mount-root)
      MOUNT_PATH="${2:?--mount requires a directory path}"
      shift 2
      ;;
    --skip-service-stop)
      SKIP_SERVICE_STOP=true
      shift
      ;;
    --skip-umount)
      SKIP_UMOUNT=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
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

MOUNT_PATH="${MOUNT_PATH%/}"
if [ -z "${MOUNT_PATH}" ] || [ "${MOUNT_PATH}" = "/" ]; then
  log_error "Refusing unsafe --mount path: '${MOUNT_PATH:-/}'"
  exit 1
fi

if [ "${DRY_RUN}" = true ]; then
  if [ "${SKIP_SERVICE_STOP}" != true ]; then
    log_info "[DRY-RUN] Would stop brainsos.service, brainsos-system-api.service, and any containers mounting ${MOUNT_PATH}"
    log_info "[DRY-RUN] Would purge sensitive ephemeral Docker named volumes (brainsos_caddy_config, brainsos_tool_egress_proxy_data, etc.)"
  fi
  log_info "[DRY-RUN] Would remove host files ${REPO_ROOT}/.env, ${REPO_ROOT}/.brainsos-initialized, ${REPO_ROOT}/.brainsos-wizard-completed, ${REPO_ROOT}/docker/langfuse/.env, and host data/system_jobs/*"
  log_info "[DRY-RUN] Would delete prior tenant OS user(s) listed in ${SUDOERS_FILE} and remove ${SUDOERS_FILE}"
  log_info "[DRY-RUN] Would run sync"
  if [ "${SKIP_UMOUNT}" != true ]; then
    log_info "[DRY-RUN] Would unmount ${MOUNT_PATH} and verify ! mountpoint -q ${MOUNT_PATH}"
  fi
  log_success "[DRY-RUN] User volume release simulation complete."
  exit 0
fi

# ------------------------------------------------------------------------------
# 1. Stop Services & Ensure Zero Containers Hold Mounts Under MOUNT_PATH
# ------------------------------------------------------------------------------
container_uses_mount() {
  local cid="$1" target_a="$2" target_b="$3"
  local src
  while IFS= read -r src; do
    [ -z "${src}" ] && continue
    case "${src}" in
      "${target_a}"|"${target_a}/"*|"${target_b}"|"${target_b}/"*)
        return 0
        ;;
    esac
  done < <(docker inspect --format '{{range .Mounts}}{{println .Source}}{{end}}' "${cid}" 2>/dev/null || true)
  return 1
}

if [ "${SKIP_SERVICE_STOP}" != true ]; then
  if command -v systemctl >/dev/null 2>&1; then
    log_info "Stopping brainsos.service and brainsos-system-api.service..."
    systemctl stop brainsos.service 2>/dev/null || true
    systemctl stop brainsos-system-api.service 2>/dev/null || true
  fi

  if [ -f "${MOUNT_PATH}/.env" ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    log_info "Ensuring compose topology for ${MOUNT_PATH}/.env is down..."
    (cd "${REPO_ROOT}" && docker compose --env-file "${MOUNT_PATH}/.env" down --remove-orphans >/dev/null 2>&1) || true
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    REAL_MOUNT="$(readlink -f "${MOUNT_PATH}" 2>/dev/null || printf '%s' "${MOUNT_PATH}")"
    for cid in $(docker ps -q 2>/dev/null || true); do
      if container_uses_mount "${cid}" "${MOUNT_PATH}" "${REAL_MOUNT}"; then
        log_warn "Stopping residual container ${cid} still holding mount under ${MOUNT_PATH}..."
        docker stop -t 30 "${cid}" >/dev/null 2>&1 || true
      fi
    done

    STILL_ATTACHED=0
    for cid in $(docker ps -q 2>/dev/null || true); do
      if container_uses_mount "${cid}" "${MOUNT_PATH}" "${REAL_MOUNT}"; then
        log_error "Container ${cid} is still mounted on ${MOUNT_PATH} after stop attempt."
        STILL_ATTACHED=$((STILL_ATTACHED + 1))
      fi
    done
    if [ "${STILL_ATTACHED}" -gt 0 ]; then
      log_error "Refusing to unmount ${MOUNT_PATH}: ${STILL_ATTACHED} running container(s) remain attached."
      exit 1
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 2. Scrub Root-Disk Secrets, Wizard State, Job Logs & Named Volumes (#388)
# ------------------------------------------------------------------------------
for host_artifact in \
  "${REPO_ROOT}/.env" \
  "${REPO_ROOT}/.brainsos-initialized" \
  "${REPO_ROOT}/.brainsos-wizard-completed" \
  "${REPO_ROOT}/docker/langfuse/.env"; do
  if [ -L "${host_artifact}" ] || [ -f "${host_artifact}" ]; then
    rm -f "${host_artifact}"
    log_info "Removed root-disk state artifact: ${host_artifact}"
  fi
done

# Scrub transient host-disk job logs (never touch mounted user EBS volume data)
HOST_JOBS_DIR="${REPO_ROOT}/data/system_jobs"
if [ -d "${HOST_JOBS_DIR}" ] && [ ! -L "${HOST_JOBS_DIR}" ]; then
  REAL_JOBS="$(readlink -f "${HOST_JOBS_DIR}" 2>/dev/null || printf '%s' "${HOST_JOBS_DIR}")"
  REAL_MOUNT_CMP="$(readlink -f "${MOUNT_PATH}" 2>/dev/null || printf '%s' "${MOUNT_PATH}")"
  case "${REAL_JOBS}" in
    "${MOUNT_PATH}"|"${MOUNT_PATH}/"*|"${REAL_MOUNT_CMP}"|"${REAL_MOUNT_CMP}/"*)
      log_warn "Skipping system_jobs scrub because ${HOST_JOBS_DIR} resolves inside ${MOUNT_PATH}."
      ;;
    *)
      find "${HOST_JOBS_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
      log_info "Scrubbed host system job directory: ${HOST_JOBS_DIR}"
      ;;
  esac
fi

# Delete prior tenant Linux OS user(s) referenced in sudoers and remove 90-brainsos-admin
if [ -f "${SUDOERS_FILE}" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    while IFS= read -r sudo_user; do
      [ -z "${sudo_user}" ] && continue
      case "${sudo_user}" in
        root|admin|ubuntu|ec2-user|ec2_user|debian|patternsatscale)
          continue
          ;;
      esac
      if [[ "${sudo_user}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] && id -u "${sudo_user}" >/dev/null 2>&1; then
        userdel -r "${sudo_user}" 2>/dev/null || userdel "${sudo_user}" 2>/dev/null || true
        log_info "Removed prior tenant OS account: ${sudo_user}"
      fi
    done < <(awk '!/^[[:space:]]*(#|$)/ {print $1}' "${SUDOERS_FILE}" 2>/dev/null || true)
  fi
  rm -f "${SUDOERS_FILE}" 2>/dev/null || true
  log_info "Removed sudoers file: ${SUDOERS_FILE}"
fi

# Purge ephemeral named Docker volumes containing per-tenant certificates/secrets/caches
if [ "${SKIP_SERVICE_STOP}" != true ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  for vol_name in brainsos_caddy_config brainsos_tool_egress_proxy_data; do
    if docker volume inspect "${vol_name}" >/dev/null 2>&1; then
      docker volume rm -f "${vol_name}" >/dev/null 2>&1 || true
      log_info "Purged ephemeral Docker named volume: ${vol_name}"
    fi
  done
fi

# ------------------------------------------------------------------------------
# 3. Flush Filesystem Buffers
# ------------------------------------------------------------------------------
log_info "Flushing dirty filesystem pages (sync)..."
sync

# ------------------------------------------------------------------------------
# 4. Unmount Persistent User Volume
# ------------------------------------------------------------------------------
if [ "${SKIP_UMOUNT}" != true ]; then
  if command -v mountpoint >/dev/null 2>&1 && [ -d "${MOUNT_PATH}" ] && mountpoint -q "${MOUNT_PATH}"; then
    log_info "Unmounting ${MOUNT_PATH}..."
    for attempt in 1 2 3 4 5; do
      if umount "${MOUNT_PATH}" 2>/dev/null; then
        break
      fi
      if [ "${attempt}" -eq 4 ]; then
        log_warn "Mount ${MOUNT_PATH} busy on retry ${attempt}; terminating open file handles via fuser..."
        command -v fuser >/dev/null 2>&1 && fuser -km "${MOUNT_PATH}" 2>/dev/null || true
        sync
      fi
      sleep 1
    done

    if mountpoint -q "${MOUNT_PATH}"; then
      log_error "Failed to unmount ${MOUNT_PATH}; volume remains mounted."
      exit 1
    fi
    log_success "Unmounted ${MOUNT_PATH} cleanly."
  else
    log_info "${MOUNT_PATH} is not currently a mountpoint; nothing to unmount."
  fi

  if command -v mountpoint >/dev/null 2>&1 && [ -d "${MOUNT_PATH}" ] && mountpoint -q "${MOUNT_PATH}"; then
    log_error "Mountpoint assertion failed: ${MOUNT_PATH} is still mounted."
    exit 1
  fi
fi

log_success "User volume at ${MOUNT_PATH} cleanly released and safe for EBS detachment."
