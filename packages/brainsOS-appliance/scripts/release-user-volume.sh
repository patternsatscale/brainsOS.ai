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
  fi
  log_info "[DRY-RUN] Would remove symlinks ${REPO_ROOT}/.env and ${REPO_ROOT}/.brainsos-initialized"
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
# 2. Remove Ephemeral Host Symlinks (/opt/brainsos/.env & .brainsos-initialized)
# ------------------------------------------------------------------------------
for link_path in "${REPO_ROOT}/.env" "${REPO_ROOT}/.brainsos-initialized"; do
  if [ -L "${link_path}" ]; then
    rm -f "${link_path}"
    log_info "Removed host symlink: ${link_path}"
  fi
done

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
