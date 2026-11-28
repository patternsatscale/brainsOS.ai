#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Operator IDE Setup & Provisioning Script
# Provisions storage directories, registers operator virtual key in LiteLLM,
# builds the native ARM64/AMD64 code-server image, and launches the service.
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

# Load environment variables
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
else
  log_warn ".env file not found. Using defaults."
  if [ -f .env.example ]; then
    set -a
    . ./.env.example
    set +a
  fi
fi

log_info "Setting up brainsOS Operator IDE from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 1. Scaffold Storage Directories
# ------------------------------------------------------------------------------
DATA_ROOT="${BRAINSOS_DATA_DIR:-./data}"
if [[ "$DATA_ROOT" != /* ]]; then
  DATA_ROOT="${REPO_ROOT}/${DATA_ROOT#./}"
fi

CONFIG_DIR="${BRAINSOS_CODE_SERVER_CONFIG:-${DATA_ROOT}/control_plane/vscode_config}"
DATA_DIR="${BRAINSOS_CODE_SERVER_DATA:-${DATA_ROOT}/control_plane/vscode_data}"

if [[ "$CONFIG_DIR" != /* ]]; then
  CONFIG_DIR="${REPO_ROOT}/${CONFIG_DIR#./}"
fi
if [[ "$DATA_DIR" != /* ]]; then
  DATA_DIR="${REPO_ROOT}/${DATA_DIR#./}"
fi

mkdir -p "${CONFIG_DIR}" "${DATA_DIR}"
chmod -R 775 "${CONFIG_DIR}" "${DATA_DIR}" 2>/dev/null || true

# Seed workspace settings to .vscode/settings.json in data root if missing
mkdir -p "${DATA_ROOT}/.vscode"
if [ ! -f "${DATA_ROOT}/.vscode/settings.json" ] && [ -f "${REPO_ROOT}/config/editor/settings.json" ]; then
  cp "${REPO_ROOT}/config/editor/settings.json" "${DATA_ROOT}/.vscode/settings.json"
fi

log_success "Scaffolded operator configuration and data directories:"
log_info "  - Config: ${CONFIG_DIR}"
log_info "  - Data:   ${DATA_DIR}"

# Ensure canvas site directory exists
APPS_DIR="${DATA_ROOT}/agents/bawtford/apps"
mkdir -p "${APPS_DIR}/cindypawford/site"

# Ensure Caddy root CA certificate is exported for in-container SSL trust
CONTROL_PLANE_DIR="${BRAINSOS_CONTROL_PLANE_DIR:-${DATA_ROOT}/control_plane}"
if [[ "$CONTROL_PLANE_DIR" != /* ]]; then
  CONTROL_PLANE_DIR="${REPO_ROOT}/${CONTROL_PLANE_DIR#./}"
fi
mkdir -p "${CONTROL_PLANE_DIR}"
touch "${CONTROL_PLANE_DIR}/caddy_root.crt"
chmod 664 "${CONTROL_PLANE_DIR}/caddy_root.crt" 2>/dev/null || true
if [ -x "${REPO_ROOT}/scripts/setup/trust-caddy-ca.sh" ]; then
  "${REPO_ROOT}/scripts/setup/trust-caddy-ca.sh" --export-only >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# 2. Register Operator Virtual Key in LiteLLM Control Plane Database
# ------------------------------------------------------------------------------
LITELLM_PORT="${LITELLM_PORT:-4000}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-}"
OPERATOR_LITELLM_KEY="${OPERATOR_LITELLM_KEY:-}"
OPERATOR_KEY_ALIAS="brainsOs.console"

if [ -n "${LITELLM_MASTER_KEY}" ] && [ -n "${OPERATOR_LITELLM_KEY}" ] && curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LITELLM_PORT}/health/liveness" | grep -qE '^(200|401|405)'; then
  log_info "Checking operator virtual key '${OPERATOR_KEY_ALIAS}' in LiteLLM DB..."
  KEY_QS="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlencode({"key": sys.argv[1]}))' "${OPERATOR_LITELLM_KEY}")"
  KEY_INFO=$(curl -s -X GET "http://127.0.0.1:${LITELLM_PORT}/key/info?${KEY_QS}" \
    -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" || echo "")

  if ! printf '%s' "${KEY_INFO}" | python3 -c '
import json, sys
target_alias = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
info = data.get("info") if isinstance(data.get("info"), dict) else data
if not isinstance(info, dict):
    sys.exit(1)
if info.get("key_alias") == target_alias and info.get("status") != "deleted":
    sys.exit(0)
sys.exit(1)
' "${OPERATOR_KEY_ALIAS}" 2>/dev/null; then
    log_info "Provisioning dedicated operator virtual key '${OPERATOR_KEY_ALIAS}' in LiteLLM DB..."
    OP_KEY_VAL="${OPERATOR_LITELLM_KEY}" python3 - << 'PYEOF' | curl -s -o /dev/null -X POST "http://127.0.0.1:${LITELLM_PORT}/key/delete" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      --data-binary @- || true
import json, os
print(json.dumps({"keys": [os.environ["OP_KEY_VAL"]]}))
PYEOF
    OP_ALIAS="${OPERATOR_KEY_ALIAS}" OP_DOMAIN="${BRAINSOS_DOMAIN:-local.brainsos.ai}" python3 - << 'PYEOF' | curl -s -o /dev/null -X POST "http://127.0.0.1:${LITELLM_PORT}/key/delete" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      --data-binary @- || true
import json, os
print(json.dumps({
    "key_aliases": [
        os.environ["OP_ALIAS"],
        "brainsOS.console",
        "brainsos-operator",
        f"{os.environ['OP_DOMAIN']}/editor/",
        "local.brainsos.ai/editor/",
    ]
}))
PYEOF
    local_res=$(OP_KEY_VAL="${OPERATOR_LITELLM_KEY}" OP_ALIAS="${OPERATOR_KEY_ALIAS}" OP_BUDGET="${LITELLM_DEFAULT_MAX_BUDGET:-25.0}" python3 - << 'PYEOF' | curl -s -w "\nHTTP_STATUS:%{http_code}" \
      -X POST "http://127.0.0.1:${LITELLM_PORT}/key/generate" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
      -H "Content-Type: application/json" \
      --data-binary @-
import json, os
print(json.dumps({
    "key": os.environ["OP_KEY_VAL"],
    "key_alias": os.environ["OP_ALIAS"],
    "user_id": "admin",
    "max_budget": float(os.environ["OP_BUDGET"]),
    "models": [],
}))
PYEOF
)
    if echo "${local_res}" | grep -q "HTTP_STATUS:200"; then
      log_success "Operator virtual key '${OPERATOR_KEY_ALIAS}' provisioned in LiteLLM control plane."
    else
      log_warn "Failed to register operator virtual key: $(echo "${local_res}" | head -n 1)"
    fi
  else
    log_info "Operator virtual key '${OPERATOR_KEY_ALIAS}' is already registered in LiteLLM control plane."
  fi
else
  log_info "LiteLLM control plane standby or required keys unset; skipping live key provisioning."
fi

# ------------------------------------------------------------------------------
# 3. Build & Launch Containerized Operator IDE
# ------------------------------------------------------------------------------
log_info "Building native brainsos-code-server container image..."
docker compose build code-server

log_info "Starting brainsos-code-server service..."
docker compose up -d code-server

# Ensure Caddy is recreated or updated with the new brainsos-ide-net
log_info "Ensuring Caddy gateway is connected to operator IDE network..."
docker compose up -d caddy

log_success "======================================================================"
log_success "brainsOS Operator IDE is running!"
log_success "Access URLs:"
log_success "  - Ingress:      http://editor.localhost (or http://editor.brainsos.local)"
log_success "  - Alternate:    http://code.localhost   (or http://code.brainsos.local)"
log_success "  - Direct Port:  http://127.0.0.1:${CODE_SERVER_PORT:-8443}"
log_success "Credentials:"
if [ -n "${CODE_SERVER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-}}" ]; then
  log_success "  - Operator User: ${OPERATOR_USER:-operator} (password configured in .env; run 'make urls' to inspect)"
else
  log_success "  - Operator User: ${OPERATOR_USER:-operator} (<unset>)"
fi
log_success "======================================================================"
