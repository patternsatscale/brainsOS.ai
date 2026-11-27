#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Segregated OpenBao Secret Manager Initialization & AppRole Seeding
# Ticket #387: Unifies Local (DGX Spark / macOS) & AWS AMI secret management
# using integrated Raft storage under ${BRAINSOS_CONTROL_PLANE_DIR}/openbao.
# ==============================================================================

set -euo pipefail

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
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

SYNC_OIDC_ONLY=false
while [ $# -gt 0 ]; do
  case "$1" in
    --sync-oidc)
      SYNC_OIDC_ONLY=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

DATA_DIR="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}"
CONTROL_DIR="${BRAINSOS_CONTROL_PLANE_DIR:-${DATA_DIR}/control_plane}"
OPENBAO_DIR="${BRAINSOS_OPENBAO_DATA_DIR:-${CONTROL_DIR}/openbao}"
APPROLE_DIR="${BRAINSOS_OPENBAO_APPROLE_DIR:-${CONTROL_DIR}/openbao_approle}"
SEAL_FILE="${OPENBAO_DIR}/.seal.json"
APPROLE_ENV="${APPROLE_DIR}/egress-approle.env"
CONTAINER_NAME="brainsos-control-secrets"

mkdir -p "${OPENBAO_DIR}" "${APPROLE_DIR}"
chmod 700 "${OPENBAO_DIR}"
chmod 750 "${APPROLE_DIR}"
if [ "$(uname -s)" = "Linux" ]; then
  chown -R 100:1000 "${OPENBAO_DIR}" 2>/dev/null || true
fi

if ! command -v docker >/dev/null 2>&1; then
  log_warn "Docker CLI unavailable; initialized ${OPENBAO_DIR} directory only."
  exit 0
fi

if [ "${SYNC_OIDC_ONLY}" = true ]; then
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qw "${CONTAINER_NAME}"; then
    log_warn "OpenBao container (${CONTAINER_NAME}) is not running; skipping OIDC sync until stack start."
    exit 0
  fi
else
  log_info "Starting segregated OpenBao secret manager container (${CONTAINER_NAME})..."
  docker compose up -d openbao >/dev/null 2>&1 || true
fi

log_info "Waiting for OpenBao API health..."
READY=false
for _ in $(seq 1 30); do
  code=$(docker exec "${CONTAINER_NAME}" sh -c "wget -q -S -O /dev/null http://127.0.0.1:8200/v1/sys/health 2>&1 | awk '/^  HTTP\\// {print \$2}' | tail -n1" || true)
  if [[ "${code}" =~ ^(200|429|472|473|501|503)$ ]]; then
    READY=true
    break
  fi
  sleep 1
done

if [ "${READY}" != "true" ]; then
  log_error "OpenBao container failed to answer healthcheck."
  exit 1
fi

is_initialized() {
  docker exec "${CONTAINER_NAME}" bao status -address=http://127.0.0.1:8200 -format=json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('initialized', False))" 2>/dev/null | grep -qi "true"
}

is_sealed() {
  docker exec "${CONTAINER_NAME}" bao status -address=http://127.0.0.1:8200 -format=json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('sealed', True))" 2>/dev/null | grep -qi "true"
}

if ! is_initialized; then
  log_info "Initializing OpenBao Raft storage..."
  INIT_JSON=$(docker exec "${CONTAINER_NAME}" bao operator init -address=http://127.0.0.1:8200 -key-shares=1 -key-threshold=1 -format=json)
  python3 -c '
import json, os, sys
raw = json.loads(sys.stdin.read())
payload = {
    "unseal_key": raw["unseal_keys_b64"][0],
    "root_token": raw["root_token"],
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
os.chmod(sys.argv[1], 0o600)
' "${SEAL_FILE}" <<< "${INIT_JSON}"
  log_success "OpenBao initialized cleanly (recovery artifacts protected at 0600)."
fi

if is_sealed; then
  if [ ! -f "${SEAL_FILE}" ]; then
    log_error "OpenBao is sealed and ${SEAL_FILE} is missing."
    exit 1
  fi
  UNSEAL_KEY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["unseal_key"])' "${SEAL_FILE}")
  docker exec -e BAO_UNSEAL="${UNSEAL_KEY}" "${CONTAINER_NAME}" sh -c 'bao operator unseal -address=http://127.0.0.1:8200 "${BAO_UNSEAL}"' >/dev/null
  log_success "OpenBao Raft store unsealed."
fi

if [ -f "${SEAL_FILE}" ]; then
  ROOT_TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "${SEAL_FILE}")

  # Configure Authentik OIDC auth backend & openbao-admin policy (#393)
  sync_openbao_oidc() {
    local root_tok="$1"
    local raw_url="${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}"
    local eff_dom
    eff_dom="$(printf '%s' "${raw_url}" | sed -E 's|^https?://||; s|/.*$||; s|:[0-9]+$||')"
    [ -n "${eff_dom}" ] || eff_dom="local.brainsos.ai"
    local oidc_client_secret="${AUTH_OPENBAO_CLIENT_SECRET:-brainsos_openbao_secret}"
    local discovery_url="https://${eff_dom}/application/o/openbao-vault/"
    local redirect_uris="https://${eff_dom}/ui/vault/auth/oidc/oidc/callback,https://secrets.${eff_dom}/ui/vault/auth/oidc/oidc/callback,https://local.brainsos.ai/ui/vault/auth/oidc/oidc/callback,http://localhost:8200/ui/vault/auth/oidc/oidc/callback"

    local admin_policy='path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}'
    printf '%s\n' "${admin_policy}" | docker exec -i -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${root_tok}" "${CONTAINER_NAME}" \
      bao policy write openbao-admin - >/dev/null

    docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${root_tok}" "${CONTAINER_NAME}" \
      bao auth list -format=json 2>/dev/null | grep -q '"oidc/"' || \
      docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${root_tok}" "${CONTAINER_NAME}" \
        bao auth enable -listing-visibility=unauth oidc >/dev/null

    # Combine system CAs + mounted Caddy Root CA so internal & ACME HTTPS discovery both validate.
    docker exec "${CONTAINER_NAME}" sh -c '
      : > /tmp/openbao_ca.pem
      [ -r /etc/ssl/cert.pem ] && cat /etc/ssl/cert.pem >> /tmp/openbao_ca.pem || true
      if [ -r /etc/ssl/caddy/root.crt ] && grep -q "BEGIN CERTIFICATE" /etc/ssl/caddy/root.crt 2>/dev/null; then
        printf "\n" >> /tmp/openbao_ca.pem
        cat /etc/ssl/caddy/root.crt >> /tmp/openbao_ca.pem
      fi
    ' >/dev/null 2>&1 || true

    if docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${root_tok}" "${CONTAINER_NAME}" \
      bao write auth/oidc/config \
        oidc_discovery_url="${discovery_url}" \
        oidc_discovery_ca_pem=@/tmp/openbao_ca.pem \
        oidc_client_id="openbao-vault" \
        oidc_client_secret="${oidc_client_secret}" \
        default_role="admin" >/dev/null 2>&1; then
      docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${root_tok}" "${CONTAINER_NAME}" \
        bao write auth/oidc/role/admin \
          bound_audiences="openbao-vault" \
          allowed_redirect_uris="${redirect_uris}" \
          user_claim="email" \
          groups_claim="groups" \
          oidc_scopes="openid,email,profile,groups" \
          'bound_claims={"groups":["authentik Admins","admins","admin","appliance-admins"]}' \
          token_policies="openbao-admin" \
          token_ttl="1h" \
          token_max_ttl="24h" >/dev/null 2>&1 || true
      log_success "Configured OpenBao Authentik OIDC login (${discovery_url}, default_role=admin)."
    else
      log_warn "Authentik OIDC discovery (${discovery_url}) unreachable right now; run './scripts/setup/setup-secrets.sh --sync-oidc' after Caddy + Authentik are healthy."
    fi
    docker exec "${CONTAINER_NAME}" rm -f /tmp/openbao_ca.pem >/dev/null 2>&1 || true
  }

  if [ "${SYNC_OIDC_ONLY}" = true ]; then
    sync_openbao_oidc "${ROOT_TOKEN}"
    exit 0
  fi

  # Ensure KV v2 engine at secret/
  docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao secrets list -format=json 2>/dev/null | grep -q '"secret/"' || \
    docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
      bao secrets enable -path=secret kv-v2 >/dev/null

  # Install least-privilege read-only policy for tool-egress-proxy
  POLICY_HCL='path "secret/data/tools" { capabilities = ["read"] }
path "secret/data/tools/*" { capabilities = ["read"] }'
  printf '%s\n' "${POLICY_HCL}" | docker exec -i -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao policy write egress-proxy-ro - >/dev/null

  # Enable AppRole auth and configure egress-proxy role
  docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao auth list -format=json 2>/dev/null | grep -q '"approle/"' || \
    docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
      bao auth enable approle >/dev/null

  docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao write auth/approle/role/egress-proxy token_policies="egress-proxy-ro" token_ttl="1h" token_max_ttl="24h" >/dev/null

  ROLE_ID=$(docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao read -field=role_id auth/approle/role/egress-proxy/role-id)
  SECRET_ID=$(docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
    bao write -f -field=secret_id auth/approle/role/egress-proxy/secret-id)

  python3 -c '
import os, sys
path, role_id, secret_id = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "w", encoding="utf-8") as f:
    f.write(f"OPENBAO_ROLE_ID={role_id}\nOPENBAO_SECRET_ID={secret_id}\n")
os.chmod(path, 0o600)
' "${APPROLE_ENV}" "${ROLE_ID}" "${SECRET_ID}"

  # Seed any existing non-placeholder tool keys from .env into OpenBao KV v2 (stdin JSON)
  python3 -c '
import json, os
keys = ["FIRECRAWL_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "BRAVE_SEARCH_API_KEY", "GITHUB_TOKEN"]
payload = {}
for k in keys:
    v = os.environ.get(k, "").strip()
    if v and v != "in-transit-openbao-managed":
        payload[k] = v
if payload:
    print(json.dumps(payload))
' | {
    read -r TOOLS_JSON || true
    if [ -n "${TOOLS_JSON:-}" ]; then
      printf '%s\n' "${TOOLS_JSON}" | docker exec -i -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="${ROOT_TOKEN}" "${CONTAINER_NAME}" \
        bao kv put secret/tools - >/dev/null
      log_success "Seeded tool secrets into OpenBao KV v2 (secret/tools)."
    fi
  }

  sync_openbao_oidc "${ROOT_TOKEN}"
fi

log_success "OpenBao secret manager ready and egress-proxy AppRole provisioned."
