#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Local Source Control (Gitea) & VS Code Git Seeding Script (Ticket #340)
# Scaffolds /data/git, initializes /data as a clean Git repository (main branch)
# tracking prompts, souls, skills, and OKF memories, provisions Gitea operator
# accounts and the default 'agent-box' repository, and syncs origin.
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

DRY_RUN=false
SEED_ONLY=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Provisions the local Gitea Source Control plane and initializes the brainsOS
data directory (/data) as a Git repository wired to Gitea and VS Code SCM.

Options:
  --dry-run      Print planned configuration and actions without modifying state
  --seed-only    Initialize local /data Git repository and seed Gitea only if running
  -h, --help     Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --seed-only)
      SEED_ONLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown argument: $1"
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/docker-compose.yml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
elif [ -f "${REPO_ROOT}/.env.example" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${REPO_ROOT}/.env.example"
  set +a
fi

DATA_ROOT="${BRAINSOS_DATA_DIR:-./data}"
if [[ "${DATA_ROOT}" != /* ]]; then
  DATA_ROOT="${REPO_ROOT}/${DATA_ROOT#./}"
fi

GIT_DATA_DIR="${BRAINSOS_GIT_DIR:-${DATA_ROOT}/git}"
if [[ "${GIT_DATA_DIR}" != /* ]]; then
  GIT_DATA_DIR="${REPO_ROOT}/${GIT_DATA_DIR#./}"
fi

PUBLIC_HOST="${BRAINSOS_URL:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}"
PUBLIC_HOST="${PUBLIC_HOST#https://}"
PUBLIC_HOST="${PUBLIC_HOST#http://}"
PUBLIC_HOST="${PUBLIC_HOST%/}"

LOCAL_DOMAIN="${BRAINSOS_LOCAL_DOMAIN:-${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-local.brainsos.ai}}}"
ADMIN_USER="admin"
ADMIN_PASS="${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_secret}"
ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-admin@${LOCAL_DOMAIN}}"

SUPERUSER_USER="${BRAINSOS_SUPERUSER_USERNAME:-${BRAINSOS_ADMIN_USERNAME:-admin}}"
SUPERUSER_PASS="${BRAINSOS_SUPERUSER_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-${ADMIN_PASS}}}"
SUPERUSER_NAME="${BRAINSOS_SUPERUSER_NAME:-${SUPERUSER_USER}}"
SUPERUSER_EMAIL="${BRAINSOS_SUPERUSER_EMAIL:-${SUPERUSER_USER}@${LOCAL_DOMAIN}}"

PRIMARY_USER="${SUPERUSER_USER}"
PRIMARY_PASS="${SUPERUSER_PASS}"
PRIMARY_EMAIL="${SUPERUSER_EMAIL}"
DEFAULT_REPO="${BRAINSOS_GIT_DEFAULT_REPO:-agent-box}"
REMOTE_URL="http://gitea:3000/${PRIMARY_USER}/${DEFAULT_REPO}.git"

if [ "${DRY_RUN}" = "true" ]; then
  log_info "[DRY-RUN] Preparing brainsOS Source Control (Gitea) & /data Git repository:"
  echo "  BRAINSOS_DATA_DIR=${DATA_ROOT}"
  echo "  BRAINSOS_GIT_DIR=${GIT_DATA_DIR}"
  echo "  GITEA_ROOT_URL=https://${PUBLIC_HOST}/git/"
  echo "  GITEA_ADMIN_USER=${ADMIN_USER}"
  echo "  GITEA_PRIMARY_USER=${PRIMARY_USER}"
  echo "  GITEA_DEFAULT_REPO=${DEFAULT_REPO}"
  echo "  GIT_REMOTE_URL=${REMOTE_URL}"
  echo "  SEED_ONLY=${SEED_ONLY}"
  log_success "Source control dry-run validation complete."
  exit 0
fi

# ------------------------------------------------------------------------------
# 1. Scaffold Gitea Persistence Directory & /data/.gitignore
# ------------------------------------------------------------------------------
log_info "Scaffolding Gitea storage directory at ${GIT_DATA_DIR}..."
mkdir -p "${GIT_DATA_DIR}"
chmod 775 "${GIT_DATA_DIR}" 2>/dev/null || true

mkdir -p "${DATA_ROOT}"

GITIGNORE_PATH="${DATA_ROOT}/.gitignore"
log_info "Ensuring clean .gitignore at ${GITIGNORE_PATH}..."
cat << 'EOF' > "${GITIGNORE_PATH}"
# ==============================================================================
# brainsOS Data Directory Git Ignore Rules (Ticket #340)
# Tracks human-auditable agent souls, prompts, skills, settings, and OKF Markdown
# memories while excluding databases, runtime state, and secrets.
# ==============================================================================

# Platform databases, caches & container volumes
control_plane/
comms/
litellm_db/
postgres/
langfuse_*/
langfuse_clickhouse/
langfuse_postgres/
telemetry/
git/
system_jobs/
workspace/
agent_workspaces/
runners/

# Transient runtime files, databases & binary artifacts
*.db
*.db-shm
*.db-wal
*.sqlite
*.sqlite3
*.log
*.pid
*.sock
*.tar
*.tar.gz
*.tgz
*.zip

# Secrets & TLS private keys (Rule 5)
.env
.env.*
*.key
*.pem
*.crt
*.p12
*.pfx

# OS & editor caches
.DS_Store
Thumbs.db
__pycache__/
*.pyc
node_modules/
.venv/
.cache/
.vscode/caches/
EOF

if [ ! -f "${DATA_ROOT}/README.md" ]; then
  cat << EOF > "${DATA_ROOT}/README.md"
# brainsOS Appliance Workspace (\`agent-box\`)

This repository tracks the live configuration, agent personas (\`souls/\`), fleet settings (\`settings/\`), and Open Knowledge Format (OKF) Markdown memories (\`agents/\`) for your **brainsOS** appliance.

- **Web IDE (VS Code)**: \`https://${PUBLIC_HOST}/editor/\`
- **Source Control (Gitea)**: \`https://${PUBLIC_HOST}/git/${PRIMARY_USER}/${DEFAULT_REPO}\`
EOF
fi

# ------------------------------------------------------------------------------
# 2. Initialize /data as a Git Repository (main branch) & Commit Initial State
# ------------------------------------------------------------------------------
git config --global --add safe.directory "${DATA_ROOT}" 2>/dev/null || true
git config --global --add safe.directory /data 2>/dev/null || true

if [ ! -d "${DATA_ROOT}/.git" ]; then
  log_info "Initializing Git repository in ${DATA_ROOT} (branch: main)..."
  git -C "${DATA_ROOT}" init -b main >/dev/null 2>&1 || {
    git -C "${DATA_ROOT}" init >/dev/null 2>&1
    git -C "${DATA_ROOT}" checkout -B main >/dev/null 2>&1 || true
  }
else
  # Ensure branch is named main if unborn or on master
  current_branch="$(git -C "${DATA_ROOT}" symbolic-ref --short HEAD 2>/dev/null || echo "")"
  if [ "${current_branch}" = "master" ]; then
    git -C "${DATA_ROOT}" branch -M main >/dev/null 2>&1 || true
  fi
fi

git -C "${DATA_ROOT}" config user.name "${SUPERUSER_NAME}"
git -C "${DATA_ROOT}" config user.email "${PRIMARY_EMAIL}"
git -C "${DATA_ROOT}" config init.defaultBranch main

# Stage tracked files and create initial commit if repository has no commits
git -C "${DATA_ROOT}" add -A >/dev/null 2>&1 || true
if ! git -C "${DATA_ROOT}" rev-parse --verify HEAD >/dev/null 2>&1; then
  log_info "Creating initial commit of appliance prompts, souls, and settings..."
  git -C "${DATA_ROOT}" commit -m "chore(appliance): initial brainsOS agent-box workspace seed" >/dev/null 2>&1 || true
  log_success "Created initial commit on branch 'main' in ${DATA_ROOT}."
elif ! git -C "${DATA_ROOT}" diff --cached --quiet >/dev/null 2>&1; then
  git -C "${DATA_ROOT}" commit -m "chore(appliance): sync brainsOS workspace state" >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------------------
# 3. Start Gitea Container (unless --seed-only and container is not running)
# ------------------------------------------------------------------------------
GITEA_CONTAINER="brainsos-app-git"
gitea_running() {
  docker inspect -f '{{.State.Running}}' "${GITEA_CONTAINER}" 2>/dev/null | grep -q "true"
}

if ! command -v docker >/dev/null 2>&1; then
  log_warn "Docker CLI not available; skipping live Gitea container provisioning."
  exit 0
fi

if ! gitea_running; then
  if [ "${SEED_ONLY}" = "true" ]; then
    log_info "Gitea container (${GITEA_CONTAINER}) is not running and --seed-only is set; local Git repo initialized."
    exit 0
  fi
  log_info "Starting Gitea service (${GITEA_CONTAINER})..."
  docker compose up -d gitea
fi

log_info "Waiting for Gitea HTTP API to become ready..."
READY=false
for _ in $(seq 1 30); do
  if docker exec "${GITEA_CONTAINER}" sh -c "curl -sf http://127.0.0.1:3000/api/healthz >/dev/null 2>&1 || wget -qO- http://127.0.0.1:3000/api/healthz >/dev/null 2>&1"; then
    READY=true
    break
  fi
  sleep 2
done

if [ "${READY}" != "true" ]; then
  log_warn "Gitea healthcheck did not become ready within timeout; skipping user/repo seeding."
  exit 0
fi

# ------------------------------------------------------------------------------
# 4. Provision Gitea Admin & Superuser Accounts
# ------------------------------------------------------------------------------
GITEA_EXEC_USER="${PUID:-1000}:${PGID:-1000}"

provision_gitea_user() {
  local username="$1"
  local password="$2"
  local email="$3"
  [ -z "${username}" ] || [ -z "${password}" ] && return 0

  if docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user list 2>/dev/null | awk '{print $2}' | grep -Fxq "${username}"; then
    log_info "Updating password for existing Gitea admin user '${username}'..."
    docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user change-password \
      --username "${username}" \
      --password "${password}" \
      --must-change-password=false >/dev/null 2>&1 || true
  else
    log_info "Creating Gitea admin user '${username}' (${email})..."
    docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user create \
      --username "${username}" \
      --password "${password}" \
      --email "${email}" \
      --admin \
      --must-change-password=false >/dev/null 2>&1 || \
    docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user change-password \
      --username "${username}" \
      --password "${password}" \
      --must-change-password=false >/dev/null 2>&1 || true
  fi
}

provision_gitea_user "${ADMIN_USER}" "${ADMIN_PASS}" "${ADMIN_EMAIL}"
if [ "${PRIMARY_USER}" != "${ADMIN_USER}" ]; then
  provision_gitea_user "${PRIMARY_USER}" "${PRIMARY_PASS}" "${PRIMARY_EMAIL}"
fi

# ------------------------------------------------------------------------------
# 5. Create Default Repository ('agent-box') & Push Initial Commit
# ------------------------------------------------------------------------------
log_info "Ensuring default repository '${PRIMARY_USER}/${DEFAULT_REPO}' exists in Gitea..."
docker exec \
  -e GITEA_USER="${PRIMARY_USER}" \
  -e GITEA_PASS="${PRIMARY_PASS}" \
  -e GITEA_REPO="${DEFAULT_REPO}" \
  "${GITEA_CONTAINER}" sh -c '
    status=$(curl -s -o /dev/null -w "%{http_code}" -u "${GITEA_USER}:${GITEA_PASS}" "http://127.0.0.1:3000/api/v1/repos/${GITEA_USER}/${GITEA_REPO}")
    if [ "${status}" != "200" ]; then
      curl -sf -X POST "http://127.0.0.1:3000/api/v1/user/repos" \
        -u "${GITEA_USER}:${GITEA_PASS}" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${GITEA_REPO}\", \"description\": \"brainsOS Appliance Prompts, Souls, Skills & OKF Memories\", \"private\": false, \"auto_init\": false, \"default_branch\": \"main\"}" >/dev/null 2>&1 || true
    fi
  ' || true

# Configure origin remote and credential store for seamless VS Code Git sync
URL_ENCODED_USER="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["U"], safe=""))' U="${PRIMARY_USER}")"
URL_ENCODED_PASS="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["P"], safe=""))' P="${PRIMARY_PASS}")"

CRED_FILE="${DATA_ROOT}/.git/credentials"
printf "http://%s:%s@gitea:3000\n" "${URL_ENCODED_USER}" "${URL_ENCODED_PASS}" > "${CRED_FILE}"
chmod 600 "${CRED_FILE}" 2>/dev/null || true

git -C "${DATA_ROOT}" config credential.helper "store --file=/data/.git/credentials"
if git -C "${DATA_ROOT}" remote get-url origin >/dev/null 2>&1; then
  git -C "${DATA_ROOT}" remote set-url origin "${REMOTE_URL}"
else
  git -C "${DATA_ROOT}" remote add origin "${REMOTE_URL}"
fi

# Push main branch to Gitea (via code-server container if running, else via Gitea container IP / localhost)
PUSHED=false
if docker inspect -f '{{.State.Running}}' brainsos-app-code-server 2>/dev/null | grep -q "true"; then
  docker exec brainsos-app-code-server sh -c "
    git config --global --add safe.directory /data 2>/dev/null || true
    printf 'http://%s:%s@gitea:3000\n' '${URL_ENCODED_USER}' '${URL_ENCODED_PASS}' > /home/coder/.git-credentials
    chmod 600 /home/coder/.git-credentials 2>/dev/null || true
    git config --global credential.helper store 2>/dev/null || true
    git -C /data push -u http://${URL_ENCODED_USER}:${URL_ENCODED_PASS}@gitea:3000/${PRIMARY_USER}/${DEFAULT_REPO}.git main >/dev/null 2>&1
  " && PUSHED=true || true
fi

if [ "${PUSHED}" != "true" ]; then
  GITEA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${GITEA_CONTAINER}" 2>/dev/null | awk '{print $1}')"
  if [ -n "${GITEA_IP}" ]; then
    git -C "${DATA_ROOT}" push -u "http://${URL_ENCODED_USER}:${URL_ENCODED_PASS}@${GITEA_IP}:3000/${PRIMARY_USER}/${DEFAULT_REPO}.git" main >/dev/null 2>&1 && PUSHED=true || true
  fi
fi

if [ "${PUSHED}" != "true" ]; then
  GITEA_HOST_PORT="${GITEA_HTTP_PORT:-3002}"
  git -C "${DATA_ROOT}" push -u "http://${URL_ENCODED_USER}:${URL_ENCODED_PASS}@127.0.0.1:${GITEA_HOST_PORT}/${PRIMARY_USER}/${DEFAULT_REPO}.git" main >/dev/null 2>&1 && PUSHED=true || true
fi

if [ "${PUSHED}" = "true" ]; then
  log_success "Pushed '${DATA_ROOT}' (branch 'main') to Gitea repository '${PRIMARY_USER}/${DEFAULT_REPO}'."
else
  log_warn "Configured remote '${REMOTE_URL}', but initial push could not reach Gitea endpoint yet."
fi

log_success "brainsOS Source Control (Gitea) & VS Code Git integration ready."
