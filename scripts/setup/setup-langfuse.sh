#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Observability Plane Manager (Langfuse v4.38.0)
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
LANGFUSE_DB_DATA_DIR="${LANGFUSE_DB_DATA_DIR:-${REPO_ROOT}/data/langfuse_db}"
LANGFUSE_CLICKHOUSE_DATA_DIR="${LANGFUSE_CLICKHOUSE_DATA_DIR:-${REPO_ROOT}/data/langfuse_clickhouse}"
LANGFUSE_REDIS_DATA_DIR="${LANGFUSE_REDIS_DATA_DIR:-${REPO_ROOT}/data/langfuse_redis}"
LANGFUSE_MINIO_DATA_DIR="${LANGFUSE_MINIO_DATA_DIR:-${REPO_ROOT}/data/langfuse_minio}"

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
  update_env_var "LANGFUSE_DB_DATA_DIR" "${LANGFUSE_DB_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_CLICKHOUSE_DATA_DIR" "${LANGFUSE_CLICKHOUSE_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_REDIS_DATA_DIR" "${LANGFUSE_REDIS_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_MINIO_DATA_DIR" "${LANGFUSE_MINIO_DATA_DIR}" "${LANGFUSE_ENV_FILE}"
  # Read user parameters strictly from root .env as the SOURCE OF TRUTH (root .env is NEVER modified)
  if [ -f "${REPO_ROOT}/.env" ]; then
    _ROOT_EMAIL=$(grep '^LANGFUSE_INIT_USER_EMAIL=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    _ROOT_NAME=$(grep '^LANGFUSE_INIT_USER_NAME=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    _ROOT_PASS=$(grep '^LANGFUSE_INIT_USER_PASSWORD=' "${REPO_ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\"' || true)
    [ -n "${_ROOT_EMAIL}" ] && LANGFUSE_INIT_USER_EMAIL="${_ROOT_EMAIL}"
    [ -n "${_ROOT_NAME}" ] && LANGFUSE_INIT_USER_NAME="${_ROOT_NAME}"
    [ -n "${_ROOT_PASS}" ] && LANGFUSE_INIT_USER_PASSWORD="${_ROOT_PASS}"
  fi

  LANGFUSE_INIT_USER_EMAIL="${LANGFUSE_INIT_USER_EMAIL:-admin@titan.local}"
  LANGFUSE_INIT_USER_NAME="${LANGFUSE_INIT_USER_NAME:-Titan Admin}"
  LANGFUSE_INIT_USER_PASSWORD="${LANGFUSE_INIT_USER_PASSWORD:-titan_admin_secret}"

  # Propagate to container-specific env file (docker/langfuse/.env)
  update_env_var "LANGFUSE_INIT_USER_EMAIL" "${LANGFUSE_INIT_USER_EMAIL}" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_USER_NAME" "\"${LANGFUSE_INIT_USER_NAME}\"" "${LANGFUSE_ENV_FILE}"
  update_env_var "LANGFUSE_INIT_USER_PASSWORD" "${LANGFUSE_INIT_USER_PASSWORD}" "${LANGFUSE_ENV_FILE}"

  export LANGFUSE_HOST="http://langfuse.titan.local:${LANGFUSE_PORT}"
  export LANGFUSE_PUBLIC_KEY="${SEC_PUBLIC_KEY}"
  export LANGFUSE_SECRET_KEY="${SEC_SECRET_KEY}"
  export LANGFUSE_OTEL_AUTH="${SEC_OTEL_AUTH}"

  log_success "Langfuse v4.38.0 configuration synchronized."
  sync_user_password
}

# ------------------------------------------------------------------------------
# Action: Password Synchronization
# ------------------------------------------------------------------------------
sync_user_password() {
  if [ -n "${LANGFUSE_INIT_USER_PASSWORD:-}" ] && [ -n "${LANGFUSE_INIT_USER_EMAIL:-}" ] && \
     docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-web$" && \
     docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-db$"; then
    log_info "Synchronizing Langfuse admin password in database from root .env..."
    local user_hash
    user_hash=$(docker exec -i titan-langfuse-web node -e "
      const p = process.argv[1];
      const bcrypt = require('/app/node_modules/.pnpm/bcryptjs@2.4.3/node_modules/bcryptjs/dist/bcrypt.js');
      console.log(bcrypt.hashSync(p, 12));
    " "${LANGFUSE_INIT_USER_PASSWORD}" 2>/dev/null || true)
    if [ -n "${user_hash}" ]; then
      docker exec -i titan-langfuse-db psql -U "${LANGFUSE_DB_USER:-langfuse}" -d "${LANGFUSE_DB_NAME:-langfuse}" \
        -c "UPDATE users SET password = '${user_hash}', updated_at = NOW() WHERE email = '${LANGFUSE_INIT_USER_EMAIL}';" >/dev/null 2>&1 || true
      log_success "Langfuse admin user password synchronized in PostgreSQL."
    fi
  fi
  sync_llm_connection
}

# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Action: LLM Gateway & Fleet Agent Preconfigured Connections
# ------------------------------------------------------------------------------
sync_llm_connection() {
  if docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-web$" && \
     docker ps --format '{{.Names}}' | grep -q "^titan-langfuse-db$"; then
    log_info "Synchronizing preconfigured LLM & Agent connections in Langfuse project 'titan'..."
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
    [ -z "${agent_key}" ] && agent_key="sk-titan-agent-key"

    docker exec -i titan-langfuse-web node -e "
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

      async function main() {
        // 1. LiteLLM Gateway Connection (via Caddy L7 proxy)
        const litellmRecord = await prisma.llmApiKeys.upsert({
          where: {
            projectId_provider: {
              projectId: 'titan',
              provider: 'LiteLLM'
            }
          },
          create: {
            id: 'cl_titan_litellm_connection',
            projectId: 'titan',
            provider: 'LiteLLM',
            adapter: 'openai',
            displaySecretKey: displayLiteLLMKey,
            secretKey: encLiteLLMKey,
            baseURL: 'http://proxy.titan.local/v1',
            customModels: ['titan-core', 'qwen3.8:latest', 'llama3.2:3b', 'qwen2.5:latest', 'gemma2:2b'],
            withDefaultModels: false,
            extraHeaderKeys: []
          },
          update: {
            adapter: 'openai',
            displaySecretKey: displayLiteLLMKey,
            secretKey: encLiteLLMKey,
            baseURL: 'http://proxy.titan.local/v1',
            customModels: ['titan-core', 'qwen3.8:latest', 'llama3.2:3b', 'qwen2.5:latest', 'gemma2:2b'],
            withDefaultModels: false
          }
        });

        // Set default playground model to LiteLLM / titan-core
        await prisma.defaultLlmModel.upsert({
          where: { projectId: 'titan' },
          create: {
            id: 'cl_titan_default_model',
            projectId: 'titan',
            llmApiKeyId: litellmRecord.id,
            provider: 'LiteLLM',
            adapter: 'openai',
            model: 'titan-core'
          },
          update: {
            llmApiKeyId: litellmRecord.id,
            provider: 'LiteLLM',
            adapter: 'openai',
            model: 'titan-core'
          }
        });

        // 2. Cindy Pawford Agent Connection (Agent-as-an-API via Caddy)
        await prisma.llmApiKeys.upsert({
          where: {
            projectId_provider: {
              projectId: 'titan',
              provider: 'Cindy-Pawford'
            }
          },
          create: {
            id: 'cl_titan_cindy_connection',
            projectId: 'titan',
            provider: 'Cindy-Pawford',
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.cindypawford.titan.local/v1',
            customModels: ['hermes-agent', 'cindy-pawford'],
            withDefaultModels: false,
            extraHeaderKeys: []
          },
          update: {
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.cindypawford.titan.local/v1',
            customModels: ['hermes-agent', 'cindy-pawford'],
            withDefaultModels: false
          }
        });

        // 3. Terrastella Agent Connection
        await prisma.llmApiKeys.upsert({
          where: {
            projectId_provider: {
              projectId: 'titan',
              provider: 'Terrastella'
            }
          },
          create: {
            id: 'cl_titan_terrastella_connection',
            projectId: 'titan',
            provider: 'Terrastella',
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.terrastella.titan.local/v1',
            customModels: ['hermes-agent', 'terrastella'],
            withDefaultModels: false,
            extraHeaderKeys: []
          },
          update: {
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.terrastella.titan.local/v1',
            customModels: ['hermes-agent', 'terrastella'],
            withDefaultModels: false
          }
        });

        // 4. Football Dan Agent Connection
        await prisma.llmApiKeys.upsert({
          where: {
            projectId_provider: {
              projectId: 'titan',
              provider: 'Football-Dan'
            }
          },
          create: {
            id: 'cl_titan_football_dan_connection',
            projectId: 'titan',
            provider: 'Football-Dan',
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.football-dan.titan.local/v1',
            customModels: ['hermes-agent', 'football-dan'],
            withDefaultModels: false,
            extraHeaderKeys: []
          },
          update: {
            adapter: 'openai',
            displaySecretKey: displayAgentKey,
            secretKey: encAgentKey,
            baseURL: 'http://api.football-dan.titan.local/v1',
            customModels: ['hermes-agent', 'football-dan'],
            withDefaultModels: false
          }
        });
      }

      main().catch(e => { console.error('Error syncing LLM connection:', e.message); });
    " "${litellm_key}" "${agent_key}" >/dev/null 2>&1 || true
    log_success "LLM & Agent connections synchronized in Langfuse (LiteLLM: proxy.titan.local, Cindy: api.cindypawford.titan.local, Terrastella: api.terrastella.titan.local, Football Dan: api.football-dan.titan.local)."
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
    echo -e "  - Web Dashboard:     ${BOLD}http://localhost:${LANGFUSE_PORT}${NC} (or http://langfuse.titan.local)"
    echo -e "  - OTel Ingestion:    ${BOLD}http://localhost:${LANGFUSE_PORT}/api/public/otel${NC}"
    echo -e "  - Public Key:        ${BOLD}${LANGFUSE_PUBLIC_KEY:-}${NC}"
    echo -e "  - Admin Email:       ${BOLD}${LANGFUSE_INIT_USER_EMAIL:-admin@titan.local}${NC}"
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
  echo -e "${BLUE}${BOLD}Project Titan: Langfuse API Key & Telemetry Header Helper${NC}"
  echo -e "${BLUE}${BOLD}==============================================================================${NC}"
  if [ -n "${LANGFUSE_PUBLIC_KEY:-}" ] && [ -n "${LANGFUSE_SECRET_KEY:-}" ]; then
    echo "Currently active credentials:"
    echo "  LANGFUSE_HOST=http://langfuse.titan.local:${LANGFUSE_PORT}"
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
