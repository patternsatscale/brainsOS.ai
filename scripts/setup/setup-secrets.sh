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

INIT_TLS_ONLY=false
SYNC_OIDC_ONLY=false
while [ $# -gt 0 ]; do
  case "$1" in
    --init-tls)
      INIT_TLS_ONLY=true
      shift
      ;;
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
OPENBAO_TLS_DIR="${BRAINSOS_OPENBAO_TLS_DIR:-${CONTROL_DIR}/openbao_tls}"
APPROLE_DIR="${BRAINSOS_OPENBAO_APPROLE_DIR:-${CONTROL_DIR}/openbao_approle}"
LEGACY_SEAL_FILE="${OPENBAO_DIR}/.seal.json"

if [ "$(id -u)" -eq 0 ] || [ -w "/etc/brainsos" ]; then
  SEAL_FILE="${BRAINSOS_OPENBAO_SEAL_FILE:-/etc/brainsos/openbao-seal.json}"
  WRITER_TOKEN_FILE="${BRAINSOS_OPENBAO_WRITER_TOKEN_FILE:-/etc/brainsos/openbao-system-api.token}"
  OIDC_SYNC_TOKEN_FILE="${BRAINSOS_OPENBAO_OIDC_SYNC_TOKEN_FILE:-/etc/brainsos/openbao-oidc-sync.token}"
else
  SEAL_FILE="${BRAINSOS_OPENBAO_SEAL_FILE:-${HOME}/.config/brainsos/openbao-seal.json}"
  WRITER_TOKEN_FILE="${BRAINSOS_OPENBAO_WRITER_TOKEN_FILE:-${HOME}/.config/brainsos/openbao-system-api.token}"
  OIDC_SYNC_TOKEN_FILE="${BRAINSOS_OPENBAO_OIDC_SYNC_TOKEN_FILE:-${HOME}/.config/brainsos/openbao-oidc-sync.token}"
fi
APPROLE_ENV="${APPROLE_DIR}/egress-approle.env"
CONTAINER_NAME="brainsos-control-secrets"

# Ensure externalized seal/token files never reside inside BRAINSOS_DATA_DIR
DATA_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${DATA_DIR}")"
for ext_path in "${SEAL_FILE}" "${WRITER_TOKEN_FILE}" "${OIDC_SYNC_TOKEN_FILE}"; do
  EXT_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${ext_path}")"
  if python3 -c 'import os,sys; p,r=sys.argv[1],sys.argv[2]; sys.exit(0 if os.path.commonpath([p,r])==r else 1)' "${EXT_REAL}" "${DATA_REAL}" 2>/dev/null; then
    log_error "Externalized OpenBao artifact path (${ext_path}) must not reside inside BRAINSOS_DATA_DIR (${DATA_DIR})."
    exit 1
  fi
done

mkdir -p "$(dirname "${SEAL_FILE}")" "$(dirname "${WRITER_TOKEN_FILE}")" "$(dirname "${OIDC_SYNC_TOKEN_FILE}")"
chmod 700 "$(dirname "${SEAL_FILE}")" 2>/dev/null || true

mkdir -p "${OPENBAO_DIR}" "${OPENBAO_TLS_DIR}" "${APPROLE_DIR}"
chmod 700 "${OPENBAO_DIR}"
chmod 750 "${OPENBAO_TLS_DIR}" "${APPROLE_DIR}"
if [ "$(uname -s)" = "Linux" ] && [ "$(id -u)" -eq 0 ]; then
  chown -R 100:1000 "${OPENBAO_DIR}" 2>/dev/null || true
fi

ensure_openbao_tls() {
  local ca_crt="${OPENBAO_TLS_DIR}/ca.crt"
  local srv_crt="${OPENBAO_TLS_DIR}/openbao.crt"
  local srv_key="${OPENBAO_TLS_DIR}/openbao.key"
  if [ -s "${ca_crt}" ] && [ -s "${srv_crt}" ] && [ -s "${srv_key}" ]; then
    return 0
  fi

  local tmp_ca_key
  tmp_ca_key="$(mktemp)"
  trap 'rm -f "${tmp_ca_key}" "${OPENBAO_TLS_DIR}/openbao.csr" "${OPENBAO_TLS_DIR}/openbao.ext" "${OPENBAO_TLS_DIR}/ca.srl"' RETURN

  local san_list="DNS:openbao,DNS:secrets,DNS:brainsos-openbao,DNS:brainsos-control-secrets,DNS:localhost,IP:127.0.0.1"
  for static_ip in "${OPENBAO_CONTROL_IP:-172.28.2.11}" "${OPENBAO_SECRETS_IP:-172.28.4.11}" "${OPENBAO_INGRESS_IP:-172.28.0.13}"; do
    if [ -n "${static_ip}" ]; then
      san_list="${san_list},IP:${static_ip}"
    fi
  done

  if command -v openssl >/dev/null 2>&1; then
    openssl genrsa -out "${tmp_ca_key}" 2048 >/dev/null 2>&1
    openssl req -x509 -new -nodes -key "${tmp_ca_key}" -sha256 -days 3650 \
      -subj "/CN=brainsos-openbao-internal-ca" \
      -addext "basicConstraints=critical,CA:TRUE" \
      -addext "keyUsage=critical,keyCertSign,cRLSign" \
      -out "${ca_crt}" >/dev/null 2>&1

    openssl genrsa -out "${srv_key}" 2048 >/dev/null 2>&1
    openssl req -new -key "${srv_key}" -subj "/CN=openbao" \
      -out "${OPENBAO_TLS_DIR}/openbao.csr" >/dev/null 2>&1

    cat > "${OPENBAO_TLS_DIR}/openbao.ext" << EOF
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${san_list}
EOF
    openssl x509 -req -in "${OPENBAO_TLS_DIR}/openbao.csr" \
      -CA "${ca_crt}" -CAkey "${tmp_ca_key}" -CAcreateserial \
      -out "${srv_crt}" -days 3650 -sha256 \
      -extfile "${OPENBAO_TLS_DIR}/openbao.ext" >/dev/null 2>&1
  else
    log_error "openssl is required to generate OpenBao internal TLS certificates."
    exit 1
  fi

  chmod 644 "${ca_crt}" "${srv_crt}"
  if [ "$(uname -s)" = "Linux" ] && [ "$(id -u)" -eq 0 ]; then
    chown 0:1000 "${ca_crt}" "${srv_crt}" "${srv_key}" 2>/dev/null || true
    chmod 640 "${srv_key}"
  else
    chmod 644 "${srv_key}"
  fi
  rm -f "${tmp_ca_key}" "${OPENBAO_TLS_DIR}/openbao.csr" "${OPENBAO_TLS_DIR}/openbao.ext" "${OPENBAO_TLS_DIR}/ca.srl"
  log_success "Provisioned OpenBao internal TLS certificates in ${OPENBAO_TLS_DIR}."
}

ensure_openbao_tls
if [ "${INIT_TLS_ONLY}" = true ]; then
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  log_warn "Docker CLI unavailable; initialized ${OPENBAO_DIR} and TLS artifacts only."
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

log_info "Waiting for OpenBao API health (HTTPS)..."
READY=false
for _ in $(seq 1 30); do
  code=$(docker exec "${CONTAINER_NAME}" sh -c "SSL_CERT_FILE=/openbao/tls/ca.crt wget -q -S -O /dev/null https://127.0.0.1:8200/v1/sys/health 2>&1 | awk '/^  HTTP\\// {print \$2}' | tail -n1" || true)
  if [[ "${code}" =~ ^(200|429|472|473|501|503)$ ]]; then
    READY=true
    break
  fi
  sleep 1
done

if [ "${READY}" != "true" ]; then
  log_error "OpenBao container failed to answer HTTPS healthcheck."
  exit 1
fi

is_initialized() {
  docker exec "${CONTAINER_NAME}" sh -c 'BAO_ADDR="https://127.0.0.1:8200" BAO_CACERT="/openbao/tls/ca.crt" bao status -format=json' 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('initialized', False))" 2>/dev/null | grep -qi "true"
}

is_sealed() {
  docker exec "${CONTAINER_NAME}" sh -c 'BAO_ADDR="https://127.0.0.1:8200" BAO_CACERT="/openbao/tls/ca.crt" bao status -format=json' 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('sealed', True))" 2>/dev/null | grep -qi "true"
}

# Execute `bao` command inside container passing token strictly via stdin (zero docker exec -e argv exposure)
bao_with_token() {
  local tok="$1"
  local cmd="$2"
  printf '%s\n' "${tok}" | docker exec -i "${CONTAINER_NAME}" sh -c "umask 077; IFS= read -r BAO_TOKEN || exit 1; export BAO_TOKEN BAO_ADDR='https://127.0.0.1:8200' BAO_CACERT='/openbao/tls/ca.crt'; ${cmd}"
}

bao_with_token_stdin() {
  local tok="$1"
  local cmd="$2"
  local payload="$3"
  {
    printf '%s\n' "${tok}"
    printf '%s\n' "${payload}"
  } | docker exec -i "${CONTAINER_NAME}" sh -c "umask 077; IFS= read -r BAO_TOKEN || exit 1; export BAO_TOKEN BAO_ADDR='https://127.0.0.1:8200' BAO_CACERT='/openbao/tls/ca.crt'; ${cmd}"
}

write_secret_file_0600() {
  local path="$1"
  local content="$2"
  python3 -c '
import os, sys
path, content = sys.argv[1], sys.stdin.read()
os.makedirs(os.path.dirname(path), exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(content)
os.chmod(path, 0o600)
' "${path}" <<< "${content}"
}

ROOT_TOKEN=""
if [ -f "${LEGACY_SEAL_FILE}" ] && [ ! -f "${SEAL_FILE}" ]; then
  log_info "Migrating legacy OpenBao seal file outside ${DATA_DIR} to ${SEAL_FILE}..."
  ROOT_TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("root_token",""))' "${LEGACY_SEAL_FILE}" 2>/dev/null || true)
  LEGACY_UNSEAL=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("unseal_key",""))' "${LEGACY_SEAL_FILE}" 2>/dev/null || true)
  if [ -n "${LEGACY_UNSEAL}" ]; then
    write_secret_file_0600 "${SEAL_FILE}" "{\"unseal_key\": \"${LEGACY_UNSEAL}\"}"
  fi
  rm -f "${LEGACY_SEAL_FILE}"
fi

if ! is_initialized; then
  log_info "Initializing OpenBao Raft storage..."
  INIT_JSON=$(docker exec "${CONTAINER_NAME}" sh -c 'BAO_ADDR="https://127.0.0.1:8200" BAO_CACERT="/openbao/tls/ca.crt" bao operator init -key-shares=1 -key-threshold=1 -format=json')
  ROOT_TOKEN=$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["root_token"])' <<< "${INIT_JSON}")
  UNSEAL_JSON=$(python3 -c '
import json, sys
raw = json.loads(sys.stdin.read())
print(json.dumps({"unseal_key": raw["unseal_keys_b64"][0]}, indent=2))
' <<< "${INIT_JSON}")
  write_secret_file_0600 "${SEAL_FILE}" "${UNSEAL_JSON}"
  log_success "OpenBao initialized cleanly (external seal protected at ${SEAL_FILE}, mode 0600)."
fi

if is_sealed; then
  if [ ! -f "${SEAL_FILE}" ]; then
    log_error "OpenBao is sealed and ${SEAL_FILE} is missing."
    exit 1
  fi
  UNSEAL_KEY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["unseal_key"])' "${SEAL_FILE}")
  printf '%s\n' "${UNSEAL_KEY}" | docker exec -i "${CONTAINER_NAME}" sh -c 'umask 077; IFS= read -r key || exit 1; BAO_ADDR="https://127.0.0.1:8200" BAO_CACERT="/openbao/tls/ca.crt" bao operator unseal "$key"' >/dev/null
  log_success "OpenBao Raft store unsealed."
fi

# Configure Authentik OIDC auth backend & openbao-admin policy (#393)
sync_openbao_oidc() {
  local tok="$1"
  local raw_url="${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}"
  local eff_dom
  eff_dom="$(printf '%s' "${raw_url}" | sed -E 's|^https?://||; s|/.*$||; s|:[0-9]+$||')"
  [ -n "${eff_dom}" ] || eff_dom="local.brainsos.ai"
  local oidc_client_secret="${AUTH_OPENBAO_CLIENT_SECRET:-brainsos_openbao_secret}"
  local discovery_url="https://${eff_dom}/application/o/openbao-vault/"
  local redirect_uris="https://${eff_dom}/ui/vault/auth/oidc/oidc/callback,https://secrets.${eff_dom}/ui/vault/auth/oidc/oidc/callback,https://local.brainsos.ai/ui/vault/auth/oidc/oidc/callback,http://localhost:8200/ui/vault/auth/oidc/oidc/callback"

  # Combine system CAs + mounted Caddy Root CA so internal & ACME HTTPS discovery both validate.
  docker exec "${CONTAINER_NAME}" sh -c '
    : > /tmp/openbao_ca.pem
    [ -r /etc/ssl/cert.pem ] && cat /etc/ssl/cert.pem >> /tmp/openbao_ca.pem || true
    if [ -r /etc/ssl/caddy/root.crt ] && grep -q "BEGIN CERTIFICATE" /etc/ssl/caddy/root.crt 2>/dev/null; then
      printf "\n" >> /tmp/openbao_ca.pem
      cat /etc/ssl/caddy/root.crt >> /tmp/openbao_ca.pem
    fi
  ' >/dev/null 2>&1 || true

  local cfg_json
  cfg_json=$(python3 -c '
import json, sys
print(json.dumps({
    "oidc_discovery_url": sys.argv[1],
    "oidc_client_id": "openbao-vault",
    "oidc_client_secret": sys.argv[2],
    "default_role": "admin",
}))
' "${discovery_url}" "${oidc_client_secret}")

  if bao_with_token_stdin "${tok}" '
    ca_pem="$(cat /tmp/openbao_ca.pem 2>/dev/null || true)"
    python3 -c "import json,sys; d=json.load(sys.stdin); d[\"oidc_discovery_ca_pem\"]=sys.argv[1]; print(json.dumps(d))" "$ca_pem" 2>/dev/null | bao write auth/oidc/config - >/dev/null 2>&1 \
    || bao write auth/oidc/config oidc_discovery_url="'"${discovery_url}"'" oidc_discovery_ca_pem=@/tmp/openbao_ca.pem oidc_client_id="openbao-vault" oidc_client_secret="'"${oidc_client_secret}"'" default_role="admin" >/dev/null 2>&1
  ' "${cfg_json}"; then
    local role_json
    role_json=$(python3 -c '
import json, sys
print(json.dumps({
    "bound_audiences": ["openbao-vault"],
    "allowed_redirect_uris": sys.argv[1].split(","),
    "user_claim": "email",
    "groups_claim": "groups",
    "oidc_scopes": ["openid", "email", "profile", "groups"],
    "bound_claims": {"groups": ["authentik Admins", "admins", "admin", "appliance-admins"]},
    "token_policies": ["openbao-admin"],
    "token_ttl": "1h",
    "token_max_ttl": "24h",
}))
' "${redirect_uris}")
    bao_with_token_stdin "${tok}" 'bao write auth/oidc/role/admin - >/dev/null 2>&1' "${role_json}" || true
    log_success "Configured OpenBao Authentik OIDC login (${discovery_url}, default_role=admin)."
  else
    log_warn "Authentik OIDC discovery (${discovery_url}) unreachable right now; run './scripts/setup/setup-secrets.sh --sync-oidc' after Caddy + Authentik are healthy."
  fi
  docker exec "${CONTAINER_NAME}" rm -f /tmp/openbao_ca.pem >/dev/null 2>&1 || true
}

if [ "${SYNC_OIDC_ONLY}" = true ]; then
  SYNC_TOK="${ROOT_TOKEN:-}"
  if [ -z "${SYNC_TOK}" ] && [ -f "${OIDC_SYNC_TOKEN_FILE}" ]; then
    SYNC_TOK="$(tr -d '[:space:]' < "${OIDC_SYNC_TOKEN_FILE}")"
  fi
  if [ -z "${SYNC_TOK}" ] && [ -f "${SEAL_FILE}" ]; then
    SYNC_TOK="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("root_token",""))' "${SEAL_FILE}" 2>/dev/null || true)"
  fi
  if [ -z "${SYNC_TOK}" ]; then
    log_warn "No OpenBao OIDC sync token available; skipping OIDC sync."
    exit 0
  fi
  bao_with_token "${SYNC_TOK}" 'bao token renew -self >/dev/null 2>&1 || true' || true
  sync_openbao_oidc "${SYNC_TOK}"
  exit 0
fi

# Fallback if root_token was still present in SEAL_FILE from an unrevoked legacy setup
if [ -z "${ROOT_TOKEN}" ] && [ -f "${SEAL_FILE}" ]; then
  ROOT_TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("root_token",""))' "${SEAL_FILE}" 2>/dev/null || true)
fi

if [ -n "${ROOT_TOKEN}" ]; then
  # 1. Ensure KV v2 engine at secret/, AppRole auth, and OIDC auth are enabled
  bao_with_token "${ROOT_TOKEN}" 'bao secrets list -format=json 2>/dev/null | grep -q "\"secret/\"" || bao secrets enable -path=secret kv-v2 >/dev/null'
  bao_with_token "${ROOT_TOKEN}" 'bao auth list -format=json 2>/dev/null | grep -q "\"approle/\"" || bao auth enable approle >/dev/null'
  bao_with_token "${ROOT_TOKEN}" 'bao auth list -format=json 2>/dev/null | grep -q "\"oidc/\"" || bao auth enable -listing-visibility=unauth oidc >/dev/null'

  # 2. Policies: openbao-admin, egress-proxy-ro, system-api-kv-writer, oidc-sync
  ADMIN_POLICY='path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}'
  bao_with_token_stdin "${ROOT_TOKEN}" 'bao policy write openbao-admin - >/dev/null' "${ADMIN_POLICY}"

  EGRESS_POLICY='path "secret/data/tools" { capabilities = ["read"] }
path "secret/data/tools/*" { capabilities = ["read"] }'
  bao_with_token_stdin "${ROOT_TOKEN}" 'bao policy write egress-proxy-ro - >/dev/null' "${EGRESS_POLICY}"

  WRITER_POLICY='path "secret/data/tools" { capabilities = ["create", "read", "update", "delete"] }
path "secret/data/tools/*" { capabilities = ["create", "read", "update", "delete"] }
path "secret/metadata/tools" { capabilities = ["list", "read"] }'
  bao_with_token_stdin "${ROOT_TOKEN}" 'bao policy write system-api-kv-writer - >/dev/null' "${WRITER_POLICY}"

  OIDC_SYNC_POLICY='path "auth/oidc/config" { capabilities = ["create", "read", "update"] }
path "auth/oidc/role/admin" { capabilities = ["create", "read", "update"] }'
  bao_with_token_stdin "${ROOT_TOKEN}" 'bao policy write oidc-sync - >/dev/null' "${OIDC_SYNC_POLICY}"

  # 3. Provision AppRole for tool-egress-proxy
  bao_with_token "${ROOT_TOKEN}" 'bao write auth/approle/role/egress-proxy token_policies="egress-proxy-ro" token_ttl="1h" token_max_ttl="24h" >/dev/null'
  ROLE_ID=$(bao_with_token "${ROOT_TOKEN}" 'bao read -field=role_id auth/approle/role/egress-proxy/role-id')
  SECRET_ID=$(bao_with_token "${ROOT_TOKEN}" 'bao write -f -field=secret_id auth/approle/role/egress-proxy/secret-id')
  write_secret_file_0600 "${APPROLE_ENV}" "OPENBAO_ROLE_ID=${ROLE_ID}
OPENBAO_SECRET_ID=${SECRET_ID}
"

  # 4. Provision least-privilege periodic orphan tokens (system-api-kv-writer & oidc-sync)
  WRITER_TOKEN=$(bao_with_token "${ROOT_TOKEN}" 'bao token create -policy=system-api-kv-writer -orphan -no-default-policy -period=720h -field=token')
  write_secret_file_0600 "${WRITER_TOKEN_FILE}" "${WRITER_TOKEN}
"

  OIDC_SYNC_TOKEN=$(bao_with_token "${ROOT_TOKEN}" 'bao token create -policy=oidc-sync -orphan -no-default-policy -period=720h -field=token')
  write_secret_file_0600 "${OIDC_SYNC_TOKEN_FILE}" "${OIDC_SYNC_TOKEN}
"

  # 5. Seed any existing non-placeholder tool keys from .env into OpenBao KV v2 (stdin JSON)
  TOOLS_JSON=$(python3 -c '
import json, os
keys = ["FIRECRAWL_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "BRAVE_SEARCH_API_KEY", "GITHUB_TOKEN"]
payload = {}
for k in keys:
    v = os.environ.get(k, "").strip()
    if v and v != "in-transit-openbao-managed":
        payload[k] = v
if payload:
    print(json.dumps(payload))
')
  if [ -n "${TOOLS_JSON:-}" ]; then
    bao_with_token_stdin "${WRITER_TOKEN}" 'bao kv put secret/tools - >/dev/null' "${TOOLS_JSON}"
    log_success "Seeded tool secrets into OpenBao KV v2 (secret/tools)."
  fi

  sync_openbao_oidc "${OIDC_SYNC_TOKEN}"

  # 6. Revoke initial root token and strip any root_token from SEAL_FILE
  bao_with_token "${ROOT_TOKEN}" 'bao token revoke -self >/dev/null' || true
  ROOT_TOKEN=""
  if [ -f "${SEAL_FILE}" ]; then
    CLEAN_SEAL=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); d.pop("root_token", None); print(json.dumps(d, indent=2))' "${SEAL_FILE}")
    write_secret_file_0600 "${SEAL_FILE}" "${CLEAN_SEAL}"
  fi
  log_success "Revoked initial OpenBao root token; least-privilege writer & OIDC-sync tokens active."
else
  # Post-bootstrap steady state: renew least-privilege tokens and sync OIDC
  if [ -f "${WRITER_TOKEN_FILE}" ]; then
    WRITER_TOKEN="$(tr -d '[:space:]' < "${WRITER_TOKEN_FILE}")"
    [ -n "${WRITER_TOKEN}" ] && bao_with_token "${WRITER_TOKEN}" 'bao token renew -self >/dev/null 2>&1 || true' || true
  fi
  if [ -f "${OIDC_SYNC_TOKEN_FILE}" ]; then
    OIDC_SYNC_TOKEN="$(tr -d '[:space:]' < "${OIDC_SYNC_TOKEN_FILE}")"
    if [ -n "${OIDC_SYNC_TOKEN}" ]; then
      bao_with_token "${OIDC_SYNC_TOKEN}" 'bao token renew -self >/dev/null 2>&1 || true' || true
      sync_openbao_oidc "${OIDC_SYNC_TOKEN}"
    fi
  fi
fi

log_success "OpenBao secret manager ready and least-privilege tokens provisioned."
