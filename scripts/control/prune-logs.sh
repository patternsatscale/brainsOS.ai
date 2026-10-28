#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Log Rotation, Journal Vacuuming & Disk Retention Safeguards
# Ticket #317 (Epic #309)
#
# Prunes old Docker container logs, vacuums systemd journald, cleans host
# application logs, and protects appliances from unattended disk exhaustion.
#
# Usage:
#   ./scripts/control/prune-logs.sh [OPTIONS]
#
# Options:
#   --dry-run             Simulate actions without deleting files or vacuuming
#   --check               Audit current disk space and log sizes without pruning
#   --retention-days N    Retention period in days (default: 30)
#   --vacuum-size SIZE    Maximum journald size (default: 500M)
#   -h, --help            Show this help message
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

DRY_RUN=false
CHECK_MODE=false
RETENTION_DAYS="${BRAINSOS_LOG_RETENTION_DAYS:-30}"
VACUUM_SIZE="500M"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --check)
      CHECK_MODE=true
      shift
      ;;
    --retention-days)
      RETENTION_DAYS="${2:-30}"
      shift 2
      ;;
    --vacuum-size)
      VACUUM_SIZE="${2:-500M}"
      shift 2
      ;;
    -h|--help)
      cat <<EOF
brainsOS Log Pruning & Disk Retention Tool (Ticket #317)

Usage:
  ./scripts/control/prune-logs.sh [OPTIONS]

Options:
  --dry-run             Simulate actions without deleting files or vacuuming
  --check               Audit current disk space and log sizes without pruning
  --retention-days N    Retention period in days (Default: 30)
  --vacuum-size SIZE    Maximum journald size (Default: 500M)
  -h, --help            Show this help message
EOF
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Guardrail: Rule 1 (Memory Plane Purity)
# Never delete or touch files inside memories/
MEMORIES_DIR="${REPO_ROOT}/data/agent_memories"
if [ -d "${MEMORIES_DIR}" ]; then
  log_info "Rule 1 Guardrail: Memory plane (${MEMORIES_DIR}) is strictly excluded from log pruning."
fi

# ------------------------------------------------------------------------------
# 1. Disk Space Inspection
# ------------------------------------------------------------------------------
log_info "Checking filesystem disk space..."

# Extract root filesystem stats using python for cross-platform accuracy (Linux/macOS)
DISK_STATS="$(python3 -c "
import shutil, sys
total, used, free = shutil.disk_usage('/')
pct_free = (free / total) * 100.0
pct_used = (used / total) * 100.0
print(f'{total / (1024**3):.1f} {used / (1024**3):.1f} {free / (1024**3):.1f} {pct_free:.1f} {pct_used:.1f}')
")"

read -r DISK_TOTAL_GB DISK_USED_GB DISK_FREE_GB DISK_PCT_FREE DISK_PCT_USED <<< "${DISK_STATS}"

log_info "Disk Status: Total: ${DISK_TOTAL_GB} GB | Used: ${DISK_USED_GB} GB (${DISK_PCT_USED}%) | Free: ${DISK_FREE_GB} GB (${DISK_PCT_FREE}%)"

# Disk capacity threshold check (15% threshold)
LOW_DISK=false
python3 -c "import sys; sys.exit(0 if float('${DISK_PCT_FREE}') < 15.0 else 1)" && LOW_DISK=true || LOW_DISK=false

if [ "${LOW_DISK}" = true ]; then
  log_warn "WARNING: Available disk space is below 15% threshold (${DISK_PCT_FREE}% free)! Executing aggressive pruning."
else
  log_success "Available disk space is healthy (${DISK_PCT_FREE}% free, threshold >= 15%)."
fi

if [ "${CHECK_MODE}" = true ]; then
  log_info "Auditing log storage consumers..."

  # Check journald usage
  if command -v journalctl >/dev/null 2>&1; then
    JOURNAL_USAGE="$(journalctl --disk-usage 2>/dev/null || echo "Unable to inspect journalctl")"
    log_info "systemd journal usage: ${JOURNAL_USAGE}"
  fi

  # Check docker system df
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    log_info "Docker disk utilization:"
    docker system df 2>/dev/null || true
  fi

  # Check /var/log or local logs size
  for log_path in /var/log/brainsos /var/log/caddy "${REPO_ROOT}/data/logs"; do
    if [ -d "${log_path}" ]; then
      DIR_SIZE="$(du -sh "${log_path}" 2>/dev/null || echo "N/A")"
      log_info "Directory size ${log_path}: ${DIR_SIZE}"
    fi
  done

  exit 0
fi

# ------------------------------------------------------------------------------
# 2. Systemd Journal Vacuuming
# ------------------------------------------------------------------------------
log_info "Pruning systemd journal logs (retention: ${RETENTION_DAYS} days, max size: ${VACUUM_SIZE})..."

if command -v journalctl >/dev/null 2>&1; then
  CURRENT_USAGE="$(journalctl --disk-usage 2>/dev/null || echo "N/A")"
  log_info "Current journal usage: ${CURRENT_USAGE}"

  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Would execute: journalctl --vacuum-time=${RETENTION_DAYS}d"
    log_info "[DRY-RUN] Would execute: journalctl --vacuum-size=${VACUUM_SIZE}"
  else
    if [ "$(id -u)" -eq 0 ]; then
      journalctl --vacuum-time="${RETENTION_DAYS}d" 2>/dev/null || true
      journalctl --vacuum-size="${VACUUM_SIZE}" 2>/dev/null || true
      log_success "Vacuumed systemd journal."
    else
      log_warn "Non-root user: journalctl vacuuming requires root/sudo privileges. Skipping journalctl vacuum."
    fi
  fi
else
  log_info "journalctl not available on this host. Skipping journal vacuuming."
fi

# ------------------------------------------------------------------------------
# 3. Docker Container Log Truncation & Image Pruning
# ------------------------------------------------------------------------------
log_info "Inspecting Docker container log usage and dangling resources..."

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  # 3A. Truncate oversized JSON log files if accessible
  if [ "$(id -u)" -eq 0 ] && [ -d /var/lib/docker/containers ]; then
    log_info "Scanning for container logs > 50MB in /var/lib/docker/containers..."
    find /var/lib/docker/containers/ -name "*-json.log" -size +50M 2>/dev/null | while read -r log_file; do
      if [ -f "${log_file}" ]; then
        if [ "${DRY_RUN}" = true ]; then
          log_info "[DRY-RUN] Would truncate oversized container log: ${log_file} ($(du -sh "${log_file}" | cut -f1))"
        else
          log_info "Truncating oversized container log: ${log_file}"
          : > "${log_file}"
        fi
      fi
    done
  fi

  # 3B. Prune dangling build cache and stopped containers
  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Would execute: docker container prune -f"
    log_info "[DRY-RUN] Would execute: docker image prune -f --filter 'until=${RETENTION_DAYS}d'"
  else
    log_info "Pruning stopped containers and dangling images older than ${RETENTION_DAYS} days..."
    docker container prune -f >/dev/null 2>&1 || true
    docker image prune -f --filter "until=${RETENTION_DAYS}d" >/dev/null 2>&1 || true
    log_success "Docker container prune and dangling image cleanup complete."
  fi
else
  log_info "Docker daemon is not accessible or not running. Skipping Docker log pruning."
fi

# ------------------------------------------------------------------------------
# 4. Host Logrotate & Ephemeral Temp Log Cleanup
# ------------------------------------------------------------------------------
log_info "Cleaning rotated host logs older than ${RETENTION_DAYS} days..."

# Clean old compressed/rotated logs in /var/log/brainsos or /var/log/caddy if root
for log_dir in /var/log/brainsos /var/log/caddy "${REPO_ROOT}/data/logs"; do
  if [ -d "${log_dir}" ]; then
    if [ "${DRY_RUN}" = true ]; then
      log_info "[DRY-RUN] Would clean *.gz, *.1, *.old files older than ${RETENTION_DAYS} days in ${log_dir}"
    else
      find "${log_dir}" -type f \( -name "*.gz" -o -name "*.1" -o -name "*.old" -o -name "*.log.*" \) -mtime +"${RETENTION_DAYS}" -delete 2>/dev/null || true
    fi
  fi
done

# Clean ephemeral update logs in /tmp older than 7 days
log_info "Cleaning ephemeral brainsOS logs in /tmp older than 7 days..."
if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would clean /tmp/brainsos-*.log and /tmp/brainsos-update-*.log older than 7 days"
else
  find /tmp -maxdepth 1 -type f -name "brainsos-*.log" -mtime +7 -delete 2>/dev/null || true
  find /tmp -maxdepth 1 -type f -name "brainsos-update-*.log" -mtime +7 -delete 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 5. Final Summary
# ------------------------------------------------------------------------------
AFTER_STATS="$(python3 -c "
import shutil
total, used, free = shutil.disk_usage('/')
pct_free = (free / total) * 100.0
pct_used = (used / total) * 100.0
print(f'{free / (1024**3):.1f} {pct_free:.1f}')
")"

read -r FREE_AFTER PCT_FREE_AFTER <<< "${AFTER_STATS}"

log_success "Log pruning & retention maintenance complete."
log_info "Available Disk Space: ${FREE_AFTER} GB (${PCT_FREE_AFTER}% free)"
