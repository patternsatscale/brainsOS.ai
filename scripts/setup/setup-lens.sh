#!/usr/bin/env bash
# ==============================================================================
# brainsOS: LiteLLM Lens Observability Setup & Key Provisioning (setup-lens.sh)
#
# Idempotent provisioning harness for LiteLLM Lens (Ticket #375):
#   1. Ensures cryptographic secrets (LENS_ADMIN_TOKEN, LENS_GATEWAY_SECRET,
#      LITELLM_LENS_SERVICE_TOKEN, LENS_CLICKHOUSE_PASSWORD) & LITELLM_IMAGE_TAG=v1.109.1
#      are present in .env with 0600 permissions (never echoing secrets).
#   2. Initializes shared ClickHouse (`brainsos-telemetry-clickhouse`) with
#      embedded ClickHouse Keeper (`KeeperMap`) and isolated `lens` DB + `lens` user
#      without modifying existing Langfuse (`default` DB) tables or volumes.
#   3. Mints a tenant-matched `LITELLM_TRACING_KEY` (`lens-trace-...`) owned by
#      the active LiteLLM key owner so gateway spend records match OTLP LLM spans.
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
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi
cd "${REPO_ROOT}"

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
ENV_UPSERT="${REPO_ROOT}/scripts/control/env-upsert.sh"

# Rule 13: Mandatory .env precondition
if [ ! -f "${ENV_FILE}" ]; then
  log_warn "No .env file present at ${ENV_FILE}; skipping Lens setup (Rule 13)."
  exit 0
fi

ACTION="${1:-setup}"

load_env() {
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
}

is_placeholder_or_short() {
  local val="${1:-}"
  local min_len="${2:-32}"
  if [ -z "${val}" ] || [ "${#val}" -lt "${min_len}" ]; then
    return 0
  fi
  local lower
  lower="$(printf '%s' "${val}" | tr '[:upper:]' '[:lower:]')"
  case "${lower}" in
    *change_me*|*change-me*|*changeme*|*must_be_*|*mock*|brainsos_lens_*|lens_clickhouse_password*)
      return 0
      ;;
  esac
  return 1
}

gen_hex() {
  local bytes="${1:-32}"
  python3 -c "import secrets; print(secrets.token_hex(${bytes}))"
}

ensure_lens_env_secrets() {
  load_env
  local updates=()

  if is_placeholder_or_short "${LENS_ADMIN_TOKEN:-}" 32; then
    updates+=("LENS_ADMIN_TOKEN=$(gen_hex 32)")
  fi
  if is_placeholder_or_short "${LENS_GATEWAY_SECRET:-}" 32; then
    updates+=("LENS_GATEWAY_SECRET=$(gen_hex 32)")
  fi
  if is_placeholder_or_short "${LITELLM_LENS_SERVICE_TOKEN:-}" 32; then
    updates+=("LITELLM_LENS_SERVICE_TOKEN=$(gen_hex 32)")
  fi
  if is_placeholder_or_short "${LENS_CLICKHOUSE_PASSWORD:-}" 16; then
    updates+=("LENS_CLICKHOUSE_PASSWORD=$(gen_hex 20)")
  fi
  if [ -z "${LENS_CLICKHOUSE_DB:-}" ]; then
    updates+=("LENS_CLICKHOUSE_DB=lens")
  fi
  if [ -z "${LENS_CLICKHOUSE_USER:-}" ]; then
    updates+=("LENS_CLICKHOUSE_USER=lens")
  fi
  if [ -z "${LANGFUSE_ENABLED:-}" ]; then
    updates+=("LANGFUSE_ENABLED=true")
  fi
  if [ -z "${LENS_ENABLED:-}" ]; then
    updates+=("LENS_ENABLED=true")
  fi

  # Upgrade legacy LiteLLM image tags (< v1.109.1) so native /lens/* gateway adapter is present
  case "${LITELLM_IMAGE_TAG:-}" in
    ""|v1.105.*|v1.106.*|v1.107.*|v1.108.*)
      updates+=("LITELLM_IMAGE_TAG=v1.109.1")
      ;;
  esac

  if [ "${#updates[@]}" -gt 0 ]; then
    "${ENV_UPSERT}" --file "${ENV_FILE}" "${updates[@]}" >/dev/null
    chmod 600 "${ENV_FILE}"
    load_env
    log_success "Initialized per-instance LiteLLM Lens secrets in .env (0600, redacted)."
  fi
}

provision_clickhouse_lens() {
  ensure_lens_env_secrets

  local ch_container="brainsos-telemetry-clickhouse"
  local needs_recreate=false

  if ! docker ps --format '{{.Names}}' | grep -q "^${ch_container}$"; then
    needs_recreate=true
  else
    local current_ch_image
    current_ch_image="$(docker inspect --format '{{.Config.Image}}' "${ch_container}" 2>/dev/null || true)"
    if [ "${current_ch_image}" != "clickhouse/clickhouse-server:26.2" ]; then
      needs_recreate=true
    elif ! docker exec "${ch_container}" test -f /etc/clickhouse-server/config.d/lens-keeper.xml 2>/dev/null; then
      needs_recreate=true
    elif ! docker exec "${ch_container}" grep -q "<access_management>1</access_management>" /etc/clickhouse-server/users.d/default-user.xml 2>/dev/null; then
      needs_recreate=true
    fi
  fi

  if [ "${needs_recreate}" = true ]; then
    log_info "Updating ${ch_container} with ClickHouse KeeperMap & SQL access management..."
    docker compose up -d clickhouse >/dev/null
  fi

  local ready=false
  for _ in $(seq 1 30); do
    if docker exec "${ch_container}" sh -c 'wget --no-verbose --tries=1 --spider http://127.0.0.1:8123/ping' >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 2
  done

  if [ "${ready}" != true ]; then
    log_warn "ClickHouse (${ch_container}) is not yet reachable; deferring Lens DB provisioning."
    return 1
  fi

  # Provision isolated `lens` database and `lens` user via stdin without exposing passwords on CLI
  local lens_db="${LENS_CLICKHOUSE_DB:-lens}"
  local lens_user="${LENS_CLICKHOUSE_USER:-lens}"

  LENS_CH_DB="${lens_db}" LENS_CH_USER="${lens_user}" LENS_CH_PASS="${LENS_CLICKHOUSE_PASSWORD}" \
    python3 - <<'PY' | docker exec -i "${ch_container}" sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery' >/dev/null
import os, re

db = os.environ["LENS_CH_DB"]
user = os.environ["LENS_CH_USER"]
pw = os.environ["LENS_CH_PASS"]

if not re.fullmatch(r"[A-Za-z0-9_]+", db) or not re.fullmatch(r"[A-Za-z0-9_]+", user):
    raise SystemExit("Invalid ClickHouse identifier")

pw_escaped = pw.replace("\\", "\\\\").replace("'", "\\'")
print(f"CREATE DATABASE IF NOT EXISTS {db};")
print(f"CREATE USER IF NOT EXISTS {user} IDENTIFIED WITH sha256_password BY '{pw_escaped}';")
print(f"ALTER USER {user} IDENTIFIED WITH sha256_password BY '{pw_escaped}';")
print(f"GRANT ALL ON {db}.* TO {user};")
print(f"GRANT SELECT ON system.* TO {user};")
print(f"GRANT TABLE ENGINE ON * TO {user};")
PY

  local keeper_check
  keeper_check="$(docker exec "${ch_container}" sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT name FROM system.table_engines WHERE name = '\''KeeperMap'\''"' 2>/dev/null | tr -d '[:space:]' || true)"
  if [ "${keeper_check}" != "KeeperMap" ]; then
    log_error "ClickHouse KeeperMap table engine is unavailable on ${ch_container}."
    return 1
  fi

  log_success "ClickHouse KeeperMap & isolated '${lens_db}' database/user ready (Langfuse 'default' DB untouched)."
}

lens_http_request() {
  # Executes an HTTP request against Lens (via host loopback if bound, or container loopback on appliances).
  local method="$1"
  local path="$2"
  local body="${3:-}"
  shift 3 || true
  local lens_port="${LENS_PORT:-4318}"

  if curl -fsS --connect-timeout 1 --max-time 2 "http://127.0.0.1:${lens_port}/health/live" >/dev/null 2>&1; then
    if [ -n "${body}" ]; then
      curl -sS --connect-timeout 3 --max-time 10 -X "${method}" "$@" -d "${body}" "http://127.0.0.1:${lens_port}${path}"
    else
      curl -sS --connect-timeout 3 --max-time 10 -X "${method}" "$@" "http://127.0.0.1:${lens_port}${path}"
    fi
  else
    if [ -n "${body}" ]; then
      printf '%s' "${body}" | docker exec -i brainsos-telemetry-lens curl -sS --connect-timeout 3 --max-time 10 -X "${method}" "$@" --data-binary @- "http://127.0.0.1:4318${path}"
    else
      docker exec brainsos-telemetry-lens curl -sS --connect-timeout 3 --max-time 10 -X "${method}" "$@" "http://127.0.0.1:4318${path}"
    fi
  fi
}

lens_check_ready() {
  local lens_port="${LENS_PORT:-4318}"
  if curl -fsS --connect-timeout 2 --max-time 3 "http://127.0.0.1:${lens_port}/health/ready" >/dev/null 2>&1; then
    return 0
  fi
  docker exec brainsos-telemetry-lens curl -fsS --connect-timeout 2 --max-time 3 "http://127.0.0.1:4318/health/ready" >/dev/null 2>&1
}

resolve_key_owner_user() {
  local su="${BRAINSOS_SUPERUSER_USERNAME:-}"
  if [ -n "${su}" ] && [ "${su}" != "admin" ]; then
    printf '%s' "${su}"
    return 0
  fi
  printf '%s' "${LITELLM_PROXY_ADMIN_ID:-${PROXY_ADMIN_ID:-admin}}"
}

mint_gateway_jwt() {
  local owner_user="$1"
  LENS_GW_SECRET="${LENS_GATEWAY_SECRET}" LENS_KEY_OWNER="${owner_user}" python3 - <<'PY'
import base64, hashlib, hmac, json, os, time

secret = os.environ["LENS_GW_SECRET"].encode("utf-8")
owner = os.environ["LENS_KEY_OWNER"]
now = int(time.time())

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

header = b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
payload = b64u(json.dumps({
    "iss": "litellm",
    "aud": "litellm-lens",
    "sub": owner,
    "iat": now,
    "exp": now + 30,
    "identity": {
        "user_role": "proxy_admin",
        "user_id": owner,
        "team_id": None,
        "org_id": None,
        "token": None,
        "models": [],
        "log_team_ids": [],
    },
}, separators=(",", ":")).encode("utf-8"))
signing_input = f"{header}.{payload}".encode("ascii")
sig = b64u(hmac.new(secret, signing_input, hashlib.sha256).digest())
print(f"{header}.{payload}.{sig}")
PY
}

validate_existing_tracing_key() {
  local key="${1:-}"
  [ -z "${key}" ] && return 1
  local code="000"
  local lens_port="${LENS_PORT:-4318}"
  if curl -fsS --connect-timeout 1 --max-time 2 "http://127.0.0.1:${lens_port}/health/live" >/dev/null 2>&1; then
    code="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 \
      -X POST "http://127.0.0.1:${lens_port}/v1/traces" \
      -H "Authorization: Bearer ${key}" \
      -H "Content-Type: application/json" \
      -d '{"resourceSpans":[]}' 2>/dev/null || echo "000")"
  else
    code="$(docker exec brainsos-telemetry-lens curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 \
      -X POST "http://127.0.0.1:4318/v1/traces" \
      -H "Authorization: Bearer ${key}" \
      -H "Content-Type: application/json" \
      -d '{"resourceSpans":[]}' 2>/dev/null || echo "000")"
  fi
  [ "${code}" = "200" ]
}

sync_lens_tracing_key() {
  ensure_lens_env_secrets

  if [ "${LENS_ENABLED:-true}" = "false" ]; then
    log_info "LENS_ENABLED=false; skipping Lens tracing key sync."
    return 0
  fi

  if ! docker ps --format '{{.Names}}' | grep -q "^brainsos-telemetry-lens$"; then
    log_warn "Container brainsos-telemetry-lens is not running; skipping tracing key sync."
    return 0
  fi

  log_info "Waiting for LiteLLM Lens readiness (/health/ready)..."
  local ready=false
  for _ in $(seq 1 30); do
    if lens_check_ready; then
      ready=true
      break
    fi
    sleep 2
  done
  if [ "${ready}" != true ]; then
    log_error "LiteLLM Lens failed readiness check (/health/ready)."
    return 1
  fi

  local owner_user
  owner_user="$(resolve_key_owner_user)"

  if [ -n "${LITELLM_TRACING_KEY:-}" ] \
    && [ "${LENS_TRACING_KEY_OWNER:-}" = "${owner_user}" ] \
    && validate_existing_tracing_key "${LITELLM_TRACING_KEY}"; then
    log_success "LiteLLM Lens ready; LITELLM_TRACING_KEY verified for owner '${owner_user}' (redacted)."
    return 0
  fi

  log_info "Minting tenant-matched LITELLM_TRACING_KEY for gateway owner '${owner_user}'..."
  local gw_jwt
  gw_jwt="$(mint_gateway_jwt "${owner_user}")"
  local req_body
  req_body="$(printf '{"name":"brainsos-fleet-%s","team_id":""}' "${owner_user}")"

  local resp
  resp="$(lens_http_request POST "/lens/tracing/keys" "${req_body}" \
    -H "Authorization: Bearer ${gw_jwt}" \
    -H "X-Lens-Contract: 1" \
    -H "Content-Type: application/json" || true)"

  local minted_token
  minted_token="$(LENS_KEY_RESP="${resp}" python3 - <<'PY'
import json, os
raw = os.environ.get("LENS_KEY_RESP", "")
try:
    data = json.loads(raw)
    tok = (data.get("key") or data.get("token") or "").strip()
    if tok.startswith("lens-trace-"):
        print(tok)
except Exception:
    pass
PY
)"

  if [ -z "${minted_token}" ]; then
    log_error "Failed to mint LITELLM_TRACING_KEY from Lens /lens/tracing/keys."
    return 1
  fi

  "${ENV_UPSERT}" --file "${ENV_FILE}" \
    "LITELLM_TRACING_KEY=${minted_token}" \
    "LENS_TRACING_KEY_OWNER=${owner_user}" >/dev/null
  chmod 600 "${ENV_FILE}"
  load_env
  log_success "Minted and stored LITELLM_TRACING_KEY in .env (owner='${owner_user}', redacted)."

  if docker ps --format '{{.Names}}' | grep -q "^brainsos-agent-runner-hermes$"; then
    log_info "Refreshing brainsos-agent-runner-hermes with LITELLM_TRACING_KEY..."
    docker compose up -d runner-hermes >/dev/null
  fi
}

show_status() {
  load_env
  echo -e "${BOLD}LiteLLM Lens Observability Status:${NC}"
  echo -e "  - LENS_ENABLED:         ${LENS_ENABLED:-true}"
  echo -e "  - LANGFUSE_ENABLED:     ${LANGFUSE_ENABLED:-true}"
  echo -e "  - LITELLM_IMAGE_TAG:    ${LITELLM_IMAGE_TAG:-v1.109.1}"
  if [ -n "${LITELLM_TRACING_KEY:-}" ]; then
    echo -e "  - LITELLM_TRACING_KEY:  ${GREEN}configured${NC} (owner=${LENS_TRACING_KEY_OWNER:-unknown}, redacted)"
  else
    echo -e "  - LITELLM_TRACING_KEY:  ${YELLOW}missing${NC}"
  fi

  if lens_check_ready; then
    echo -e "  - Lens /health/ready:   ${GREEN}200 OK${NC}"
  else
    echo -e "  - Lens /health/ready:   ${RED}UNREADY${NC}"
  fi

  local litellm_port="${LITELLM_PORT:-4000}"
  local svc_json=""
  if curl -fsS --connect-timeout 1 --max-time 3 "http://127.0.0.1:${litellm_port}/health/liveness" >/dev/null 2>&1; then
    svc_json="$(curl -sS --connect-timeout 2 --max-time 4 "http://127.0.0.1:${litellm_port}/lens/service" \
      -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" 2>/dev/null || true)"
  elif docker ps --format '{{.Names}}' | grep -q "^brainsos-control-litellm$"; then
    local ip
    ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' brainsos-control-litellm 2>/dev/null | awk '{print $1}' || true)"
    if [ -n "${ip}" ]; then
      svc_json="$(curl -sS --connect-timeout 2 --max-time 4 "http://${ip}:4000/lens/service" \
        -H "Authorization: Bearer ${LITELLM_MASTER_KEY:-}" 2>/dev/null || true)"
    fi
  fi
  if [ -n "${svc_json}" ]; then
    echo -e "  - Gateway /lens/service: ${svc_json}"
  fi
}

case "${ACTION}" in
  --pre-up|pre-up)
    provision_clickhouse_lens
    ;;
  sync)
    sync_lens_tracing_key
    ;;
  status)
    show_status
    ;;
  setup|"")
    provision_clickhouse_lens
    if docker ps --format '{{.Names}}' | grep -q "^brainsos-telemetry-lens$"; then
      sync_lens_tracing_key
    fi
    ;;
  *)
    echo "Usage: $0 [setup|--pre-up|sync|status]" >&2
    exit 1
    ;;
esac
