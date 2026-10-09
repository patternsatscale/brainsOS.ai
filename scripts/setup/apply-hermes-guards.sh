#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Apply Hermes Runtime Guards (Ticket #295)
# Idempotently enforces the runtime guards the email -> run -> reply pipeline
# relies on, then recreates the shared Hermes runner so they take effect:
#
#   1. gateway.api_server.max_concurrent_runs: 1 in the LIVE runner config
#      (${BRAINSOS_RUNNERS_DIR}/hermes/config.yaml). bootstrap-env.sh seeds that
#      file with `cp -n`, so template changes never reach existing hosts.
#   2. The read-only brainsOS provider plugin mount
#      (docker/hermes/plugins/model-providers -> /opt/data/plugins/model-providers)
#      that forwards session_id to LiteLLM Langfuse traces.
#
# Usage:
#   ./scripts/setup/apply-hermes-guards.sh            # apply + recreate runner-hermes
#   ./scripts/setup/apply-hermes-guards.sh --check    # verify only, no changes
#
# Recreating runner-hermes interrupts any in-flight run (the worker sends the
# sender a failure email). Stop the queue worker first if that matters.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

CHECK_ONLY=false
for arg in "$@"; do
  case "${arg}" in
    --check) CHECK_ONLY=true ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) log_error "Unknown argument: ${arg}"; exit 2 ;;
  esac
done

# Rule 13: never act on an unconfigured clone.
if [ ! -f "${REPO_ROOT}/.env" ]; then
  log_error "No .env found in ${REPO_ROOT}; this host is not an execution host. Aborting."
  exit 1
fi
set -a
# shellcheck disable=SC1091
. "${REPO_ROOT}/.env"
set +a

DATA_ROOT="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}"
RUNNERS_ROOT="${BRAINSOS_RUNNERS_DIR:-${DATA_ROOT}/runners}"
LIVE_CONFIG="${RUNNERS_ROOT}/hermes/config.yaml"
PLUGIN_DIR="${REPO_ROOT}/docker/hermes/plugins/model-providers/brainsos-litellm-session"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
[ -x "${PYTHON_BIN}" ] || PYTHON_BIN="python3"

if [ ! -f "${LIVE_CONFIG}" ]; then
  log_error "Live Hermes config not found at ${LIVE_CONFIG}. Run ./scripts/control/bootstrap-env.sh first."
  exit 1
fi
if [ ! -f "${PLUGIN_DIR}/__init__.py" ]; then
  log_error "Provider plugin missing at ${PLUGIN_DIR}."
  exit 1
fi

# --- 1. max_concurrent_runs guard (comment-preserving where possible) ---------
GUARD_MODE="apply"
${CHECK_ONLY} && GUARD_MODE="check"
GUARD_RESULT="$("${PYTHON_BIN}" - "${LIVE_CONFIG}" "${GUARD_MODE}" <<'PY'
import re
import sys

import yaml

path, mode = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
cfg = yaml.safe_load(text) or {}
gateway = cfg.get("gateway") if isinstance(cfg.get("gateway"), dict) else None
api = gateway.get("api_server") if gateway and isinstance(gateway.get("api_server"), dict) else None
current = api.get("max_concurrent_runs") if api else None

if current == 1:
    print("ok")
    sys.exit(0)
if mode == "check":
    print(f"missing:{current}")
    sys.exit(0)

if current is not None and re.search(r"^(\s+)max_concurrent_runs:\s*\S+", text, re.M):
    text = re.sub(r"^(\s+)max_concurrent_runs:\s*\S+", r"\1max_concurrent_runs: 1", text, count=1, flags=re.M)
elif gateway is None:
    block = (
        "\n# brainsOS Rule 3 guard (#295): one agent run at a time; enforced by "
        "scripts/setup/apply-hermes-guards.sh\n"
        "gateway:\n  api_server:\n    max_concurrent_runs: 1\n"
    )
    text = text.rstrip("\n") + "\n" + block
else:
    # A gateway section exists without the key: fall back to a YAML round-trip (drops comments).
    cfg.setdefault("gateway", {}).setdefault("api_server", {})["max_concurrent_runs"] = 1
    text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)

open(path, "w", encoding="utf-8").write(text)
check = (yaml.safe_load(text) or {}).get("gateway", {}).get("api_server", {}).get("max_concurrent_runs")
print("applied" if check == 1 else f"failed:{check}")
PY
)"

case "${GUARD_RESULT}" in
  ok) log_success "Live config already has gateway.api_server.max_concurrent_runs: 1" ;;
  applied) log_success "Set gateway.api_server.max_concurrent_runs: 1 in ${LIVE_CONFIG}" ;;
  missing:*)
    log_error "Guard missing in live config (current: ${GUARD_RESULT#missing:})."
    exit 1 ;;
  *) log_error "Could not apply max_concurrent_runs guard: ${GUARD_RESULT}"; exit 1 ;;
esac

if ${CHECK_ONLY}; then
  if docker compose exec -T runner-hermes test -f /opt/data/plugins/model-providers/brainsos-litellm-session/__init__.py 2>/dev/null; then
    log_success "Provider plugin is mounted in runner-hermes."
  else
    log_error "Provider plugin is NOT mounted in runner-hermes (run without --check)."
    exit 1
  fi
  exit 0
fi

# --- 2. Recreate runner-hermes so config + plugin mount take effect -----------
log_info "Recreating runner-hermes to apply guards..."
docker compose up -d --force-recreate runner-hermes

HERMES_PORT="${HERMES_RUNNER_PORT:-8642}"
log_info "Waiting for Hermes API on 127.0.0.1:${HERMES_PORT}..."
for _ in $(seq 1 60); do
  if curl -fsS -m 3 "http://127.0.0.1:${HERMES_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 3
done
if ! curl -fsS -m 3 "http://127.0.0.1:${HERMES_PORT}/health" >/dev/null 2>&1; then
  log_error "Hermes API did not become healthy within 180s."
  exit 1
fi
log_success "Hermes API is healthy."

# --- 3. Verify inside the container --------------------------------------------
if docker compose exec -T runner-hermes test -f /opt/data/plugins/model-providers/brainsos-litellm-session/__init__.py; then
  log_success "Provider plugin mounted at /opt/data/plugins/model-providers/brainsos-litellm-session"
else
  log_error "Provider plugin mount missing inside runner-hermes."
  exit 1
fi
if docker compose exec -T runner-hermes grep -Eq '^\s+max_concurrent_runs:\s*1\b' /opt/data/config.yaml; then
  log_success "runner-hermes sees gateway.api_server.max_concurrent_runs: 1"
else
  log_error "runner-hermes config does not show max_concurrent_runs: 1"
  exit 1
fi

log_success "Hermes runtime guards applied."
