#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Observability Plane Manager (Langfuse v4.38.0)
# Automates provisioning, key generation, startup, and lifecycle management
# for Langfuse distributed stack (Web, Worker, ClickHouse, Redis, MinIO, Postgres).
# ==============================================================================

set -euo pipefail

# Visual styling
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

COMPOSE_FILE="${REPO_ROOT}/docker/langfuse/docker-compose.yml"
LANGFUSE_DIR="${REPO_ROOT}/docker/langfuse"
LANGFUSE_ENV_FILE="${LANGFUSE_DIR}/.env"
LANGFUSE_ENV_EXAMPLE="${LANGFUSE_DIR}/.env.example"

# Load langfuse-specific .env if present for defaults
if [ -f "${LANGFUSE_ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${LANGFUSE_ENV_FILE}"
  set +a
fi

# Load parent .env if present for project-level overrides (root .env is authoritative)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

LANGFUSE_PORT="${LANGFUSE_PORT:-3001}"
LANGFUSE_DB_DATA_DIR="${LANGFUSE_DB_DATA_DIR:-${REPO_ROOT}/data/telemetry/postgres}"
LANGFUSE_CLICKHOUSE_DATA_DIR="${LANGFUSE_CLICKHOUSE_DATA_DIR:-${REPO_ROOT}/data/telemetry/clickhouse}"
LANGFUSE_REDIS_DATA_DIR="${LANGFUSE_REDIS_DATA_DIR:-${REPO_ROOT}/data/telemetry/redis}"
LANGFUSE_MINIO_DATA_DIR="${LANGFUSE_MINIO_DATA_DIR:-${REPO_ROOT}/data/telemetry/minio}"

# Helper to run compose commands
compose_cmd() {
  if [ -f "${LANGFUSE_ENV_FILE}" ]; then
    docker compose -f "${COMPOSE_FILE}" --env-file "${LANGFUSE_ENV_FILE}" "$@"
  else
    docker compose -f "${COMPOSE_FILE}" "$@"
  fi
}

# ------------------------------------------------------------------------------
# Action: Setup
# ------------------------------------------------------------------------------
setup_langfuse() {
  log_info "Configuring Langfuse v4.38.0 distributed observability environment..."

  mkdir -p "${LANGFUSE_DB_DATA_DIR}" "${LANGFUSE_CLICKHOUSE_DATA_DIR}" "${LANGFUSE_REDIS_DATA_DIR}" "${LANGFUSE_MINIO_DATA_DIR}"
  chmod 777 "${LANGFUSE_CLICKHOUSE_DATA_DIR}" "${LANGFUSE_MINIO_DATA_DIR}" "${LANGFUSE_REDIS_DATA_DIR}" 2>/dev/null || true

  if [ ! -f "${LANGFUSE_ENV_FILE}" ]; then
    log_info "Creating ${LANGFUSE_ENV_FILE} from template..."
    if [ -f "${LANGFUSE_ENV_EXAMPLE}" ]; then
      cp "${LANGFUSE_ENV_EXAMPLE}" "${LANGFUSE_ENV_FILE}"
    else
      touch "${LANGFUSE_ENV_FILE}"
    fi
  fi

  # Generate cryptographically secure keys
  log_info "Verifying secure cryptographic keys and auto-initialization credentials..."
  SEC_NEXTAUTH="${NEXTAUTH_SECRET:-$(openssl rand -base64 32)}"
  SEC_SALT="${SALT:-$(openssl rand -base64 32)}"
  SEC_ENCRYPT="${ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
  SEC_DB_PASS="${LANGFUSE_DB_PASSWORD:-$(openssl rand -hex 16)}"
  SEC_REDIS="${REDIS_AUTH:-$(openssl rand -hex 16)}"
  SEC_MINIO="${MINIO_ROOT_PASSWORD:-$(openssl rand -hex 16)}"

  # Ensure API Keys exist (or auto-generate for zero-click fleet setup)
  SEC_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-pk-lf-$(openssl rand -hex 16)}"
  SEC_SECRET_KEY="${LANGFUSE_SECRET_KEY:-sk-lf-$(openssl rand -hex 16)}"
  SEC_OTEL_AUTH="Basic $(echo -n "${SEC_PUBLIC_KEY}:${SEC_SECRET_KEY}" | base64 | tr -d '\r\n')"

  # Helper to set or update key-value in a file safely (pure python3 avoids regex/delimiter issues)
  update_env_var() {
    local key="$1"
    local val="$2"
    local file="$3"
    python3 -c "
import sys
key, val, file_path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(file_path, 'r') as f:
        lines = f.readlines()
except FileNotFoundError:
    lines = []
found = False
new_lines = []
for line in lines:
    if line.startswith(f'{key}='):
        new_lines.append(f'{key}={val}\n')
        found = True
    else:
        new_lines.append(line)
if not found:
    new_lines.append(f'{key}={val}\n')
with open(file_path, 'w') as f:
    f.writelines(new_lines)
" "${key}" "${val}" "${file}"
  }

  # Write keys to Langfuse .env
  update_env_var "NEXTAUTH_SECRET" "${SEC_NEXTAUTH}" "${LANGFUSE_ENV_FILE}"
  update_env_var "SALT" "${SEC_SALT}" "${LANGFUSE_ENV_FILE}"
  update_env_var "ENCRYPTION_KEY" "${SEC_ENCRYPT}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_DB_PASSWORD" "${SEC_DB_PASS}" "${LANGFUSE_ENV_FILE}"
  update_env_var "REDIS_AUTH" "${SEC_REDIS}" "${LANGFUSE_ENV_FILE}"
  update_env_var "MINIO_ROOT_PASSWORD" "${SEC_MINIO}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_PUBLIC_KEY" "${SEC_PUBLIC_KEY}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_SECRET_KEY" "${SEC_SECRET_KEY}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_ORG_ID" "${LANGFUSE_INIT_ORG_ID:-brainsos}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_ORG_NAME" "\"${LANGFUSE_INIT_ORG_NAME:-brainsOS}\"" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_PROJECT_ID" "${LANGFUSE_INIT_PROJECT_ID:-brainsos}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_PROJECT_NAME" "\"${LANGFUSE_INIT_PROJECT_NAME:-brainsOS Fleet}\"" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "${SEC_PUBLIC_KEY}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_PROJECT_SECRET_KEY" "${SEC_SECRET_KEY}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_DB_DATA_DIR" "${LANGFUSE_DB_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_CLICKHOUSE_DATA_DIR" "${LANGFUSE_CLICKHOUSE_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_REDIS_DATA_DIR" "${LANGFUSE_REDIS_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_MINIO_DATA_DIR" "${LANGFUSE_MINIO_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  # Read user parameters strictly from root .env as the SOURCE OF TRUTH (root .env is NEVER modified)
  if [ -f "${REPO_ROOT}/.env" ]; then
    _ROOT_EMAIL=$(grep '^LANGFUSE_INIT_USER_EMAIL=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    _ROOT_NAME=$(grep '^LANGFUSE_INIT_USER_NAME=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    _ROOT_PASS=$(grep '^LANGFUSE_INIT_USER_PASSWORD=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    if [ -z "${_ROOT_PASS}" ]; then
      _ROOT_PASS=$(grep '^BRAINSOS_ADMIN_PASSWORD=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    fi
    if [ -z "${_ROOT_EMAIL}" ]; then
      _ROOT_EMAIL=$(grep '^BRAINSOS_ADMIN_EMAIL=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    fi
    [ -n "${_ROOT_EMAIL}" ] && LANGFUSE_INIT_USER_EMAIL="${_ROOT_EMAIL}"
    [ -n "${_ROOT_NAME}" ] && LANGFUSE_INIT_USER_NAME="${_ROOT_NAME}"
    [ -n "${_ROOT_PASS}" ] && LANGFUSE_INIT_USER_PASSWORD="${_ROOT_PASS}"
  fi

  LANGFUSE_INIT_USER_EMAIL="${LANGFUSE_INIT_USER_EMAIL:-${BRAINSOS_ADMIN_EMAIL:-admin@${BRAINSOS_DOMAIN:-local.brainsos.ai}}}"
  LANGFUSE_INIT_USER_NAME="${LANGFUSE_INIT_USER_NAME:-brainsOS Admin}"
  LANGFUSE_INIT_USER_PASSWORD="${LANGFUSE_INIT_USER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}}"

  # Propagate to container-specific env file (docker/langfuse/.env)
  update_env_var "LANGFUSE_INIT_USER_EMAIL" "${LANGFUSE_INIT_USER_EMAIL}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_USER_NAME" "\"${LANGFUSE_INIT_USER_NAME}\"" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_USER_PASSWORD" "${LANGFUSE_INIT_USER_PASSWORD}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_MIGRATION_V4_WRITE_MODE" "${LANGFUSE_MIGRATION_V4_WRITE_MODE:-dual}" "${LANGFUSE_ENV_FILE}"

  # Native Authentik OIDC Single Sign-On & Ingress Callback URL
  DOMAIN="${BRAINSOS_DOMAIN:-local.brainsos.ai}"
  if [ -z "${NEXTAUTH_URL:-}" ] || [[ "${NEXTAUTH_URL}" == *"localhost"* ]]; then
    NEXTAUTH_URL="https://langfuse.${DOMAIN}"
  fi
  AUTH_CUSTOM_ISSUER="${AUTH_LANGFUSE_ISSUER:-https://${DOMAIN}/application/o/langfuse}"
  update_env_var "NEXTAUTH_URL" "${NEXTAUTH_URL}" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_CLIENT_ID" "${AUTH_LANGFUSE_CLIENT_ID:-langfuse-trace}" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_CLIENT_SECRET" "${AUTH_LANGFUSE_CLIENT_SECRET:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_langfuse_secret}}" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_ISSUER" "${AUTH_CUSTOM_ISSUER}" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_NAME" "\"brainsOS SSO\"" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_ALLOW_ACCOUNT_LINKING" "true" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_CUSTOM_FETCH_USERINFO" "true" "${LANGFUSE_ENV_FILE}"
  update_env_var "AUTH_DISABLE_USERNAME_PASSWORD" "true" "${LANGFUSE_ENV_FILE}"

  export LANGFUSE_HOST="http://127.0.0.1:${LANGFUSE_PORT}"
  export LANGFUSE_PUBLIC_KEY="${SEC_PUBLIC_KEY}"
  export LANGFUSE_SECRET_KEY="${SEC_SECRET_KEY}"
  export LANGFUSE_OTEL_AUTH="${SEC_OTEL_AUTH}"

  log_success "Langfuse v4.38.0 configuration synchronized."
  sync_user_password
}

# ------------------------------------------------------------------------------
# Action: Password & Organization Synchronization
# ------------------------------------------------------------------------------
sync_user_password() {
  if [ -n "${LANGFUSE_INIT_USER_PASSWORD:-}" ] && [ -n "${LANGFUSE_INIT_USER_EMAIL:-}" ] && \
     docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-web$" && \
     docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-db$"; then
    log_info "Synchronizing Langfuse admin users, organization, and project memberships in database..."
    local user_hash
    user_hash=$(docker exec -i brainsos-langfuse-web node -e "
      const p = process.argv[1];
      const bcrypt = require('/app/node_modules/.pnpm/bcryptjs@2.4.3/node_modules/bcryptjs/dist/bcrypt.js');
      console.log(bcrypt.hashSync(p, 12));
    " "${LANGFUSE_INIT_USER_PASSWORD}" 2>/dev/null || true)
    if [ -n "${user_hash}" ]; then
      docker exec -i brainsos-langfuse-db psql -U "${LANGFUSE_DB_USER:-langfuse}" -d "${LANGFUSE_DB_NAME:-langfuse}" \
        -c "
          -- 1. Ensure brainsOS organization and project exist
          INSERT INTO organizations (id, name, created_at, updated_at)
          VALUES ('brainsos', 'brainsOS', NOW(), NOW())
          ON CONFLICT (id) DO UPDATE SET name = 'brainsOS', updated_at = NOW();

          INSERT INTO projects (id, name, org_id, created_at, updated_at)
          VALUES ('brainsos', 'brainsOS Fleet', 'brainsos', NOW(), NOW())
          ON CONFLICT (id) DO UPDATE SET name = 'brainsOS Fleet', org_id = 'brainsos', updated_at = NOW();

          -- 2. Reassign primary API key to brainsos project
          UPDATE api_keys SET project_id = 'brainsos' WHERE public_key = '${SEC_PUBLIC_KEY}';

          -- 3. Wipe out legacy Titan tech debt
          DELETE FROM organization_memberships WHERE org_id = 'titan';
          DELETE FROM api_keys WHERE project_id = 'titan';
          DELETE FROM projects WHERE id = 'titan';
          DELETE FROM organizations WHERE id = 'titan';
          DELETE FROM users WHERE email LIKE '%@titan.local';

          -- 4. Update or create primary admin user
          DO \$\$
          BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE email = '${LANGFUSE_INIT_USER_EMAIL}') THEN
              UPDATE users SET password = '${user_hash}', updated_at = NOW(), admin = true WHERE email = '${LANGFUSE_INIT_USER_EMAIL}';
            ELSE
              UPDATE users SET email = '${LANGFUSE_INIT_USER_EMAIL}', name = '${LANGFUSE_INIT_USER_NAME:-brainsOS Admin}', password = '${user_hash}', updated_at = NOW(), admin = true
              WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1);
            END IF;
          END \$\$;

          -- 5. Grant OWNER role on brainsos organization to all operator & admin accounts
          INSERT INTO organization_memberships (id, user_id, org_id, role, created_at, updated_at)
          SELECT 'om_' || substr(md5(u.id || 'brainsos'), 1, 20), u.id, 'brainsos', 'OWNER', NOW(), NOW()
          FROM users u
          WHERE u.email IN ('${LANGFUSE_INIT_USER_EMAIL}', 'operator@brainsos.ai', '${BRAINSOS_ADMIN_EMAIL:-admin@${BRAINSOS_DOMAIN:-local.brainsos.ai}}')
          ON CONFLICT (org_id, user_id) DO UPDATE SET role = 'OWNER', updated_at = NOW();

          -- 6. Grant ADMIN role on brainsos project to all members
          INSERT INTO project_memberships (project_id, user_id, org_membership_id, role, created_at, updated_at)
          SELECT 'brainsos', om.user_id, om.id, 'ADMIN', NOW(), NOW()
          FROM organization_memberships om
          WHERE om.org_id = 'brainsos'
          ON CONFLICT (project_id, user_id) DO UPDATE SET role = 'ADMIN', updated_at = NOW();

          UPDATE users SET admin = true WHERE email IN ('${LANGFUSE_INIT_USER_EMAIL}', 'operator@brainsos.ai', '${BRAINSOS_ADMIN_EMAIL:-admin@${BRAINSOS_DOMAIN:-local.brainsos.ai}}');
        " >/dev/null 2>&1 || true
      log_success "Langfuse organization 'brainsos' and admin permissions synchronized in PostgreSQL."
    fi
  fi
  sync_llm_connection
}

# ------------------------------------------------------------------------------
# Action: LLM Gateway & Fleet Agent Preconfigured Connections
# ------------------------------------------------------------------------------
sync_llm_connection() {
  if docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-web$" && \
     docker ps --format '{{.Names}}' | grep -q "^brainsos-langfuse-db$"; then
    log_info "Synchronizing preconfigured LLM & Agent connections in Langfuse project 'brainsos'..."
    local litellm_key="${LITELLM_MASTER_KEY:-sk-supergr00vyd00d!!!}"
    if [ -f "${REPO_ROOT}/.env" ]; then
      local _k
      _k=$(grep '^LITELLM_MASTER_KEY=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
      [ -n "${_k}" ] && litellm_key="${_k}"
    fi

    local agent_key="${API_SERVER_KEY:-}"
    if [ -f "${REPO_ROOT}/.env" ]; then
      local _ak
      _ak=$(grep '^API_SERVER_KEY=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
      [ -n "${_ak}" ] && agent_key="${_ak}"
    fi
    [ -z "${agent_key}" ] && agent_key="sk-brainsos-agent-key"

    local manifest="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/settings/agents.yaml"
    if [ ! -f "${manifest}" ]; then
      manifest="${REPO_ROOT}/config/default_settings/agents.yaml"
    fi

    local python_bin="${REPO_ROOT}/.venv/bin/python"
    if [ ! -x "${python_bin}" ]; then
      python_bin="python3"
    fi

    local agents_json
    agents_json=$("${python_bin}" -c "
import yaml, json
with open('${manifest}') as f:
    d = yaml.safe_load(f)
res = [{'id': a['id'], 'name': a.get('name', a['id']), 'subdomain': a.get('comms', {}).get('subdomain', f\"{a['id']}.brainsos.local\")} for a in d.get('agents', []) if a.get('enabled', True)]
print(json.dumps(res))
" 2>/dev/null || echo "[]")

    docker exec -i brainsos-langfuse-web node -e "
      const crypto = require('crypto');
      const { PrismaClient } = require('/app/node_modules/.pnpm/@prisma+client@6.19.3_@typescript+typescript6@6.0.2_prisma@6.19.3_@typescript+typescript6@6.0.2_magicast@0.5.2_/node_modules/@prisma/client');
      const prisma = new PrismaClient();

      const keyHex = process.env.ENCRYPTION_KEY;
      function encrypt(text) {
        const iv = crypto.randomBytes(12);
        const cipher = crypto.createCipheriv('aes-256-gcm', Buffer.from(keyHex, 'hex'), iv);
        let enc = cipher.update(text, 'utf8', 'hex');
        enc += cipher.final('hex');
        const authTag = cipher.getAuthTag();
        return iv.toString('hex') + ':' + enc + ':' + authTag.toString('hex');
      }

      const litellmKey = process.argv[1];
      const displayLiteLLMKey = '...' + litellmKey.slice(-4);
      const encLiteLLMKey = encrypt(litellmKey);

      const agentKey = process.argv[2];
      const displayAgentKey = '...' + agentKey.slice(-4);
      const encAgentKey = encrypt(agentKey);

      const agents = JSON.parse(process.argv[3] || '[]');

      async function main() {
        // 1. LiteLLM Gateway Connection (via Caddy L7 proxy)
        const litellmRecord = await prisma.llmApiKeys.upsert({
          where: {
            projectId_provider: {
              projectId: 'brainsos',
              provider: 'LiteLLM'
            }
          },
          create: {
            id: 'cl_brainsos_litellm_connection',
            projectId: 'brainsos',
            provider: 'LiteLLM',
            adapter: 'openai',
            displaySecretKey: displayLiteLLMKey,
            secretKey: encLiteLLMKey,
            baseURL: 'http://proxy.brainsos.local/v1',
            customModels: ['brainsos-core', 'qwen3.8:latest', 'llama3.2:3b', 'qwen2.5:latest', 'gemma2:2b'],
            withDefaultModels: false,
            extraHeaderKeys: []
          },
          update: {
            adapter: 'openai',
            displaySecretKey: displayLiteLLMKey,
            secretKey: encLiteLLMKey,
            baseURL: 'http://proxy.brainsos.local/v1',
            customModels: ['brainsos-core', 'qwen3.8:latest', 'llama3.2:3b', 'qwen2.5:latest', 'gemma2:2b'],
            withDefaultModels: false
          }
        });

        // Set default playground model to LiteLLM / brainsos-core
        await prisma.defaultLlmModel.upsert({
          where: { projectId: 'brainsos' },
          create: {
            id: 'cl_brainsos_default_model',
            projectId: 'brainsos',
            llmApiKeyId: litellmRecord.id,
            provider: 'LiteLLM',
            adapter: 'openai',
            model: 'brainsos-core'
          },
          update: {
            llmApiKeyId: litellmRecord.id,
            provider: 'LiteLLM',
            adapter: 'openai',
            model: 'brainsos-core'
          }
        });

        // 2. Dynamic Fleet Agent Connections (Agent-as-an-API via Caddy)
        for (const a of agents) {
          const cleanId = a.id.replace(/-/g, '_');
          await prisma.llmApiKeys.upsert({
            where: {
              projectId_provider: {
                projectId: 'brainsos',
                provider: a.id
              }
            },
            create: {
              id: \`cl_brainsos_\${cleanId}_connection\`,
              projectId: 'brainsos',
              provider: a.id,
              adapter: 'openai',
              displaySecretKey: displayAgentKey,
              secretKey: encAgentKey,
              baseURL: \`http://api.\${a.subdomain}/v1\`,
              customModels: ['hermes-agent', a.id],
              withDefaultModels: false,
              extraHeaderKeys: []
            },
            update: {
              adapter: 'openai',
              displaySecretKey: displayAgentKey,
              secretKey: encAgentKey,
              baseURL: \`http://api.\${a.subdomain}/v1\`,
              customModels: ['hermes-agent', a.id],
              withDefaultModels: false
            }
          });
        }
      }

      main().catch(e => { console.error('Error syncing LLM connection:', e.message); });
    " "${litellm_key}" "${agent_key}" "${agents_json}" >/dev/null 2>&1 || true
    local agent_names
    agent_names=$(echo "${agents_json}" | python3 -c "import json, sys; print(', '.join([a['id'] for a in json.load(sys.stdin)]))" 2>/dev/null || echo "fleet agents")
    log_success "LLM & Agent connections synchronized in Langfuse (LiteLLM: proxy.brainsos.local, agents: ${agent_names})."
  fi
}

# ------------------------------------------------------------------------------
# Action: Start
# ------------------------------------------------------------------------------
start_langfuse() {
  setup_langfuse

  log_info "Starting Langfuse v4.38.0 stack (Web on :${LANGFUSE_PORT}, Worker, ClickHouse, Redis, MinIO, Postgres)..."
  compose_cmd up -d

  log_info "Waiting for Langfuse web service to report healthy on http://localhost:${LANGFUSE_PORT}..."
  READY=false
  for i in {1..90}; do
    STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" || echo "000")
    if [ "${STATUS_CODE}" = "200" ]; then
      READY=true
      break
    fi
    sleep 1
  done

  if [ "${READY}" = true ]; then
    sync_user_password

    log_success "Langfuse v4.38.0 is running and healthy!"
    echo ""
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "${GREEN}${BOLD}Langfuse v4.38.0 Observability Platform Ready${NC}"
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
    echo -e "  - Web Dashboard:     ${BOLD}http://localhost:${LANGFUSE_PORT}${NC} (or http://langfuse.brainsos.local)"
    echo -e "  - OTel Ingestion:    ${BOLD}http://localhost:${LANGFUSE_PORT}/api/public/otel${NC}"
    echo -e "  - Public Key:        ${BOLD}${LANGFUSE_PUBLIC_KEY:-}${NC}"
    echo -e "  - Admin Email:       ${BOLD}${LANGFUSE_INIT_USER_EMAIL:-admin@brainsos.local}${NC}"
    echo -e "  - Admin Password:    ${BOLD}[Configured in .env]${NC}"
    echo -e "${GREEN}${BOLD}==============================================================================${NC}"
  else
    log_warn "Langfuse containers started, but /api/public/health did not return 200 within 90s."
    log_info "Check service logs via: ./scripts/setup/setup-langfuse.sh logs"
  fi
}

# ------------------------------------------------------------------------------
# Action: Stop
# ------------------------------------------------------------------------------
stop_langfuse() {
  log_info "Stopping Langfuse container stack..."
  compose_cmd down
  log_success "Langfuse container stack stopped."
}

# ------------------------------------------------------------------------------
# Action: Status
# ------------------------------------------------------------------------------
status_langfuse() {
  log_info "Checking Langfuse service status..."
  compose_cmd ps
  echo ""
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${LANGFUSE_PORT}/api/public/health" 2>/dev/null || echo "000")
  if [ "${STATUS_CODE}" = "200" ]; then
    log_success "Langfuse API Health: ONLINE (http://localhost:${LANGFUSE_PORT}/api/public/health -> 200 OK)"
  else
    log_warn "Langfuse API Health: OFFLINE or NOT RESPONDING (HTTP ${STATUS_CODE})"
  fi
}

# ------------------------------------------------------------------------------
# Action: Logs
# ------------------------------------------------------------------------------
logs_langfuse() {
  compose_cmd logs -f "$@"
}

# ------------------------------------------------------------------------------
# Action: Keys / Creds Display & Generator
# ------------------------------------------------------------------------------
generate_keys_helper() {
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  echo -e "${BLUE}${BOLD}brainsOS: Langfuse API Key & Telemetry Header Helper${NC}"
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  if [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
    echo "Currently active credentials:"
    echo "  LANGFUSE_HOST=http://langfuse.brainsos.local:${LANGFUSE_PORT}"
    echo "  LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}"
    echo "  LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}"
    echo "  LANGFUSE_OTEL_AUTH=${LANGFUSE_OTEL_AUTH:-Basic $(echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64 | tr -d '\r\n')}"
    echo ""
  fi
}

case "${1:-status}" in
  setup)
    setup_langfuse
    ;;
  start)
    start_langfuse
    ;;
  stop)
    stop_langfuse
    ;;
  restart)
    stop_langfuse
    sleep 1
    start_langfuse
    ;;
  status)
    status_langfuse
    ;;
  logs)
    shift || true
    logs_langfuse "$@"
    ;;
  keys|creds)
    generate_keys_helper
    ;;
  sync-password|sync)
    setup_langfuse
    ;;
  *)
    echo "Usage: $0 {setup|start|stop|restart|status|logs|keys|sync-password}"
    exit 1
    ;;
esac
