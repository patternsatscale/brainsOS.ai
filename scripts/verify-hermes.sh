#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Hermes Agent Workspace & Persistence Automated Verification
# Validates host bind-mount persistence, unprivileged sandbox boundaries,
# skills scaffolding, full backup readiness, and secret hygiene.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Load environment
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

HERMES_PORT="${HERMES_PORT:-8642}"
DATA_DIR="${TITAN_DATA_DIR:-./data/memories}"
WORKSPACE_PATH="${TITAN_WORKSPACE_DIR:-./data/workspace}"

if [[ "$WORKSPACE_PATH" != /* ]]; then
  HOST_WORKSPACE="${REPO_ROOT}/${WORKSPACE_PATH#./}"
else
  HOST_WORKSPACE="${WORKSPACE_PATH}"
fi

if [[ "$DATA_DIR" != /* ]]; then
  HOST_MEMORIES="${REPO_ROOT}/${DATA_DIR#./}"
else
  HOST_MEMORIES="${DATA_DIR}"
fi

log_info "Running Project Titan Hermes Workspace & Persistence Verification..."
log_info "Host Workspace Path: ${HOST_WORKSPACE}"
log_info "Host Memories Path:  ${HOST_MEMORIES}"

# ------------------------------------------------------------------------------
# 1. Container Running & Health Check
# ------------------------------------------------------------------------------
log_info "Step 1: Checking Hermes container status..."
if ! docker compose ps --services --filter "status=running" | grep -q "^hermes$"; then
  log_warn "Hermes container is not running. Starting hermes..."
  docker compose up -d hermes
  sleep 2
fi

CONTAINER_USER=$(docker compose exec -T hermes id -u)
if [ "${CONTAINER_USER}" != "1000" ]; then
  log_error "Hermes container is running as UID ${CONTAINER_USER} (expected 1000: unprivileged hermes)."
  exit 1
fi
log_success "Hermes container verified running as unprivileged UID 1000."

# ------------------------------------------------------------------------------
# 2. Web Console Reachability
# ------------------------------------------------------------------------------
log_info "Step 2: Checking Hermes web console on port ${HERMES_PORT}..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${HERMES_PORT}/" || echo "failed")
if [ "${HTTP_STATUS}" == "200" ]; then
  log_success "Hermes web console reachable (HTTP 200)."
else
  log_error "Hermes web console returned HTTP ${HTTP_STATUS}."
  exit 1
fi

# ------------------------------------------------------------------------------
# 3. Host Bind-Mount Verification
# ------------------------------------------------------------------------------
log_info "Step 3: Verifying workspace is a host bind-mount..."
COMPOSE_MOUNT_TYPE=$(docker inspect titan-hermes --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Type}}{{end}}{{end}}')
if [ "${COMPOSE_MOUNT_TYPE}" == "bind" ]; then
  log_success "Verified /workspace is mounted as a host 'bind' mount."
else
  log_error "Expected /workspace to be 'bind' mount, but found '${COMPOSE_MOUNT_TYPE}'."
  exit 1
fi

COMPOSE_MOUNT_SRC=$(docker inspect titan-hermes --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}')
log_success "Verified host source path: ${COMPOSE_MOUNT_SRC}"

# ------------------------------------------------------------------------------
# 4. Bidirectional File Persistence Across Restarts
# ------------------------------------------------------------------------------
log_info "Step 4: Testing file write from inside container and host reflection..."
TEST_MARKER="test_persist_$(date +%s)"
docker compose exec -T hermes bash -c "echo '${TEST_MARKER}' > /workspace/test_marker.txt"

if [ ! -f "${HOST_WORKSPACE}/test_marker.txt" ]; then
  log_error "File written inside container did not appear on host at ${HOST_WORKSPACE}/test_marker.txt"
  exit 1
fi

HOST_CONTENT=$(cat "${HOST_WORKSPACE}/test_marker.txt")
if [ "${HOST_CONTENT}" != "${TEST_MARKER}" ]; then
  log_error "Content mismatch: expected '${TEST_MARKER}', got '${HOST_CONTENT}'"
  exit 1
fi
log_success "File written inside container reflected immediately on host."

# Test persistence across container recreation
log_info "Recreating Hermes container to verify persistence..."
docker compose up -d --force-recreate hermes
sleep 2

CONTAINER_CONTENT=$(docker compose exec -T hermes cat /workspace/test_marker.txt 2>/dev/null || echo "")
if [ "${CONTAINER_CONTENT}" == "${TEST_MARKER}" ]; then
  log_success "File persistence verified across container recreation!"
else
  log_error "File did not persist across container recreation (read: '${CONTAINER_CONTENT}')."
  exit 1
fi

# Clean up test marker
rm -f "${HOST_WORKSPACE}/test_marker.txt"

# ------------------------------------------------------------------------------
# 5. Skills Auto-Scaffolding
# ------------------------------------------------------------------------------
log_info "Step 5: Verifying skills auto-scaffolding in /workspace/skills..."
if docker compose exec -T hermes test -f /workspace/skills/hermes_okf.py; then
  log_success "Skills scaffolding verified: /workspace/skills/hermes_okf.py is present."
else
  log_error "Expected /workspace/skills/hermes_okf.py to exist."
  exit 1
fi

# ------------------------------------------------------------------------------
# 6. Memory Plane Purity Verification
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying Memory Plane purity (Rule 1)..."
DISALLOWED_IN_MEMORIES=$(find "${HOST_MEMORIES}" -type f -name "*.db" -o -name "*.sqlite" -o -name "*.pyc" 2>/dev/null || true)
if [ -n "${DISALLOWED_IN_MEMORIES}" ]; then
  log_error "Disallowed non-OKF runtime files detected in memories plane: ${DISALLOWED_IN_MEMORIES}"
  exit 1
fi
log_success "Memory Plane remains pure OKF Markdown."

# ------------------------------------------------------------------------------
# 7. Unified Backup & Retention Verification
# ------------------------------------------------------------------------------
log_info "Step 7: Testing unified full-data backup script (scripts/backup.sh)..."
if [ -x "${REPO_ROOT}/scripts/backup.sh" ]; then
  "${REPO_ROOT}/scripts/backup.sh"
  "${REPO_ROOT}/scripts/backup.sh" --list
  LATEST_BACKUP=$(find "${REPO_ROOT}/data/backups" -name "titan_data_*.tar.gz" -type f | sort | tail -n 1)
  if [ -n "${LATEST_BACKUP}" ] && tar -tzf "${LATEST_BACKUP}" | grep -q "manifest.json"; then
    log_success "Full data backup created and validated with manifest: $(basename "${LATEST_BACKUP}")"
  else
    log_error "Latest backup missing or invalid manifest."
    exit 1
  fi
else
  log_error "scripts/backup.sh not found or not executable."
  exit 1
fi

# ------------------------------------------------------------------------------
# 8. Git Secret Hygiene Verification
# ------------------------------------------------------------------------------
log_info "Step 8: Checking Git status for uncommitted runtime workspace files..."
UNTRACKED_WORKSPACE=$(git ls-files -o --exclude-standard data/workspace/ | grep -v 'data/workspace/\.gitkeep$' || true)
TRACKED_WORKSPACE=$(git ls-files data/workspace/ | grep -v 'data/workspace/\.gitkeep$' || true)
if [ -n "${UNTRACKED_WORKSPACE}" ] || [ -n "${TRACKED_WORKSPACE}" ]; then
  log_error "Untracked or tracked live workspace files detected: ${UNTRACKED_WORKSPACE} ${TRACKED_WORKSPACE}"
  exit 1
fi
log_success "Git tracking is clean: data/workspace/* properly ignored."

echo ""
echo -e "${GREEN}${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Hermes Workspace & Full-Data Persistence Checks Passed!     ${NC}"
echo -e "${GREEN}${BOLD}=================================================================${NC}"
