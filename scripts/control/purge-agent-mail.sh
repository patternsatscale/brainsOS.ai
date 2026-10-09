#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Agent Mail Clean-Slate Purge
# Empties every agent mailbox (all folders, all domains), clears the inbound
# mail spool and the work queue, and restarts the Hermes runner so no orphaned
# in-flight runs survive. Human mailboxes (admin, operator) are NOT touched.
#
# Usage:
#   ./scripts/control/start-control-plane.sh stop
#   ./scripts/control/purge-agent-mail.sh --yes [--keep-hermes]
#   ./scripts/control/start-control-plane.sh start
#
# Destructive and irreversible. Requires --yes. Refuses to run while the
# queue worker is running (it would race the purge).
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
[ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

CONFIRM=false
RESTART_HERMES=true
for arg in "$@"; do
  case "${arg}" in
    --yes) CONFIRM=true ;;
    --keep-hermes) RESTART_HERMES=false ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      log_error "Unknown argument: ${arg}"
      exit 1
      ;;
  esac
done

# Rule 13: only run on a configured execution host
if [ ! -f .env ]; then
  log_error "No .env found. This is not a configured execution host."
  exit 1
fi
set -a
. ./.env
set +a

if [ "${CONFIRM}" != true ]; then
  log_error "Destructive operation. Re-run with --yes to confirm."
  exit 1
fi

if pgrep -f "brainsos_agent.worker" >/dev/null 2>&1; then
  log_error "Queue worker is running. Stop it first: ./scripts/control/start-control-plane.sh stop"
  exit 1
fi

DATA_DIR="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}"
COMMS_DIR="${BRAINSOS_COMMS_DIR:-${DATA_DIR}/comms}"
SPOOL_DIR="${BRAINSOS_SPOOL_DIR:-${COMMS_DIR}/spool}"
QUEUE_DB="${BRAINSOS_QUEUE_DB:-${DATA_DIR}/queue/tasks.db}"
MANIFEST="${BRAINSOS_AGENTS_MANIFEST:-${BRAINSOS_SETTINGS_DIR:-${DATA_DIR}/settings}/agents.yaml}"
[ -f "${MANIFEST}" ] || MANIFEST="${REPO_ROOT}/config/default_settings/agents.yaml"

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
[ -x "${PYTHON_BIN}" ] || PYTHON_BIN="python3"

# ------------------------------------------------------------------------------
# 1. Agent mailboxes (Dovecot). Homes are keyed by local part (%n), so one
#    login per agent covers every domain alias.
# ------------------------------------------------------------------------------
log_info "Resolving agent mailboxes from manifest: ${MANIFEST}"
AGENT_IDS="$("${PYTHON_BIN}" - "${MANIFEST}" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1])) or {}
for a in data.get("agents", []):
    email = a.get("email") or {}
    if a.get("id") and email.get("enabled", True):
        print(a["id"])
PY
)"

if [ -z "${AGENT_IDS}" ]; then
  log_warn "No agents with email enabled found in manifest."
fi

if ! docker compose ps mail-server 2>/dev/null | grep -qE "(Up|running)"; then
  log_error "mail-server container is not running; cannot purge mailboxes."
  exit 1
fi

DOVECOT_USERS="$(docker compose exec -T mail-server doveadm user '*' 2>/dev/null || true)"

for agent_id in ${AGENT_IDS}; do
  login="$(printf '%s\n' "${DOVECOT_USERS}" | grep -m1 "^${agent_id}@" || true)"
  if [ -z "${login}" ]; then
    log_warn "No Dovecot account for agent '${agent_id}'; skipping."
    continue
  fi
  count="$(docker compose exec -T mail-server doveadm search -u "${login}" mailbox '*' all 2>/dev/null | wc -l | tr -d ' ')"
  docker compose exec -T mail-server doveadm expunge -u "${login}" mailbox '*' all
  log_success "Mailbox '${agent_id}': expunged ${count} message(s) across all folders."
done

# ------------------------------------------------------------------------------
# 2. Inbound spool (raw .eml + .done markers). Files are written by the mail
#    container and are container-owned, so delete through its mount.
# ------------------------------------------------------------------------------
CONTAINER_SPOOL="/var/spool/brainsos/inbound"
if docker compose exec -T mail-server test -d "${CONTAINER_SPOOL}" 2>/dev/null; then
  spool_count="$(docker compose exec -T mail-server sh -c "find '${CONTAINER_SPOOL}' -maxdepth 1 -type f \( -name '*.eml' -o -name '*.done' \) | wc -l" | tr -d ' \r')"
  docker compose exec -T mail-server sh -c "find '${CONTAINER_SPOOL}' -maxdepth 1 -type f \( -name '*.eml' -o -name '*.done' \) -delete"
  log_success "Spool: removed ${spool_count} file(s) from ${SPOOL_DIR}."
elif [ -d "${SPOOL_DIR}" ]; then
  spool_count="$(find "${SPOOL_DIR}" -maxdepth 1 -type f \( -name '*.eml' -o -name '*.done' \) | wc -l | tr -d ' ')"
  find "${SPOOL_DIR}" -maxdepth 1 -type f \( -name '*.eml' -o -name '*.done' \) -delete
  log_success "Spool: removed ${spool_count} file(s) from ${SPOOL_DIR}."
else
  log_info "Spool directory not found (${SPOOL_DIR}); nothing to clear."
fi

# ------------------------------------------------------------------------------
# 3. Work queue (schema is recreated by the worker on next start)
# ------------------------------------------------------------------------------
if [ -f "${QUEUE_DB}" ]; then
  rm -f "${QUEUE_DB}" "${QUEUE_DB}-wal" "${QUEUE_DB}-shm"
  log_success "Queue: removed ${QUEUE_DB}."
else
  log_info "Queue DB not found (${QUEUE_DB}); nothing to clear."
fi

# ------------------------------------------------------------------------------
# 4. Hermes runner: drop any orphaned in-flight runs
# ------------------------------------------------------------------------------
if [ "${RESTART_HERMES}" = true ]; then
  if docker compose ps runner-hermes 2>/dev/null | grep -qE "(Up|running)"; then
    log_info "Restarting runner-hermes to terminate orphaned in-flight runs..."
    docker compose restart runner-hermes >/dev/null
    log_success "runner-hermes restarted."
  fi
fi

log_success "Agent mail clean slate complete. OKF thread memories were not modified."
