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
  --seed-only    Initialize local /data Git repository only without provisioning or pushing to Gitea
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
ADMIN_USER="operator"
ADMIN_PASS="${BRAINSOS_ADMIN_PASSWORD:-}"
ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:-operator@${LOCAL_DOMAIN}}"

SUPERUSER_USER="${BRAINSOS_SUPERUSER_USERNAME:-}"
if [ -z "${SUPERUSER_USER}" ] || [ "${SUPERUSER_USER}" = "admin" ] || [ "${SUPERUSER_USER}" = "akadmin" ]; then
  SUPERUSER_USER="operator"
fi
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
control_plane/**
backups/**
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
.env*
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
  git -C "${DATA_ROOT}" commit --allow-empty -m "chore(appliance): initial brainsOS agent-box workspace seed" >/dev/null 2>&1 || true
  log_success "Created initial commit on branch 'main' in ${DATA_ROOT}."
elif ! git -C "${DATA_ROOT}" diff --cached --quiet >/dev/null 2>&1; then
  git -C "${DATA_ROOT}" commit -m "chore(appliance): sync brainsOS workspace state" >/dev/null 2>&1 || true
fi

# Ensure 'initial-setup' branch exists pointing to the initial/current main commit
if ! git -C "${DATA_ROOT}" show-ref --verify --quiet refs/heads/initial-setup; then
  git -C "${DATA_ROOT}" branch -f initial-setup main >/dev/null 2>&1 || true
fi

# Configure origin remote, credential store & upstream tracking refs in /data/.git
GIT_CREDENTIALS_FILE="/data/.git/credentials"
CRED_FILE="${DATA_ROOT}/.git/credentials"

if git -C "${DATA_ROOT}" remote get-url origin >/dev/null 2>&1; then
  git -C "${DATA_ROOT}" remote set-url origin "${REMOTE_URL}"
else
  git -C "${DATA_ROOT}" remote add origin "${REMOTE_URL}"
fi

git -C "${DATA_ROOT}" update-ref refs/remotes/origin/main HEAD 2>/dev/null || true
INITIAL_SETUP_SHA="$(git -C "${DATA_ROOT}" rev-parse refs/heads/initial-setup 2>/dev/null || git -C "${DATA_ROOT}" rev-parse HEAD 2>/dev/null || true)"
if [ -n "${INITIAL_SETUP_SHA}" ]; then
  git -C "${DATA_ROOT}" update-ref refs/remotes/origin/initial-setup "${INITIAL_SETUP_SHA}" 2>/dev/null || true
fi
git -C "${DATA_ROOT}" config branch.main.remote origin
git -C "${DATA_ROOT}" config branch.main.merge refs/heads/main
git -C "${DATA_ROOT}" config branch.initial-setup.remote origin
git -C "${DATA_ROOT}" config branch.initial-setup.merge refs/heads/initial-setup
git -C "${DATA_ROOT}" config push.default simple
git -C "${DATA_ROOT}" config credential.helper "store --file=${GIT_CREDENTIALS_FILE}"
chown -R "${PUID:-1000}:${PGID:-1000}" "${DATA_ROOT}/.git" 2>/dev/null || true

# ------------------------------------------------------------------------------
# 3. Start Gitea Container (unless --seed-only)
# ------------------------------------------------------------------------------
if [ "${SEED_ONLY}" = "true" ]; then
  log_success "Local Git repository seeded at ${DATA_ROOT} (--seed-only); skipping live Gitea container provisioning."
  exit 0
fi

if [ -z "${PRIMARY_PASS}" ]; then
  log_error "BRAINSOS_ADMIN_PASSWORD or BRAINSOS_SUPERUSER_PASSWORD must be set for live Gitea provisioning."
  exit 1
fi

GITEA_CONTAINER="brainsos-app-git"
gitea_running() {
  docker inspect -f '{{.State.Running}}' "${GITEA_CONTAINER}" 2>/dev/null | grep -q "true"
}

if ! command -v docker >/dev/null 2>&1; then
  log_warn "Docker CLI not available; skipping live Gitea container provisioning."
  exit 0
fi

if ! gitea_running; then
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
# 4. Provision Gitea Admin & Superuser Accounts + Scoped Repository Token
# ------------------------------------------------------------------------------
GITEA_EXEC_USER="${PUID:-1000}:${PGID:-1000}"

provision_gitea_user() {
  local username="$1"
  local password="$2"
  local email="$3"
  [ -z "${username}" ] || [ -z "${password}" ] && return 0

  if docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user list 2>/dev/null | awk '{print $2}' | grep -Fxq "${username}"; then
    log_info "Updating password for existing Gitea admin user '${username}'..."
    docker exec -i -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user change-password \
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

if [ -n "${ADMIN_PASS}" ]; then
  provision_gitea_user "${ADMIN_USER}" "${ADMIN_PASS}" "${ADMIN_EMAIL}"
fi
if [ "${PRIMARY_USER}" != "${ADMIN_USER}" ] || [ -z "${ADMIN_PASS}" ]; then
  provision_gitea_user "${PRIMARY_USER}" "${PRIMARY_PASS}" "${PRIMARY_EMAIL}"
fi

# Mint least-privilege scoped Gitea PAT (write:repository) for SCM & initial push
GITEA_TOKEN_NAME="brainsos-editor-scm"
BASIC_B64="$(
  GITEA_U="${PRIMARY_USER}" GITEA_P="${PRIMARY_PASS}" python3 - << 'PYEOF'
import base64
import os

creds = f"{os.environ['GITEA_U']}:{os.environ['GITEA_P']}".encode("utf-8")
print(base64.b64encode(creds).decode("ascii"))
PYEOF
)"
URL_ENCODED_USER="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "${PRIMARY_USER}")"

docker exec -i \
  -e GITEA_BASIC_B64="${BASIC_B64}" \
  -e GITEA_USER_ENC="${URL_ENCODED_USER}" \
  -e GITEA_TOKEN_NAME="${GITEA_TOKEN_NAME}" \
  "${GITEA_CONTAINER}" sh -c '
    printf "header = \"Authorization: Basic %s\"\n" "${GITEA_BASIC_B64}" | \
      curl -s -X DELETE -K - "http://127.0.0.1:3000/api/v1/users/${GITEA_USER_ENC}/tokens/${GITEA_TOKEN_NAME}" >/dev/null 2>&1 || true
  ' || true

GITEA_TOKEN="$(docker exec -u "${GITEA_EXEC_USER}" "${GITEA_CONTAINER}" gitea admin user generate-access-token \
  --username "${PRIMARY_USER}" \
  --token-name "${GITEA_TOKEN_NAME}" \
  --scopes "write:repository" \
  --raw 2>/dev/null | tail -n 1 | tr -d '[:space:]' || true)"

if [ -z "${GITEA_TOKEN}" ]; then
  GITEA_TOKEN_JSON="$(GITEA_TOKEN_NAME="${GITEA_TOKEN_NAME}" python3 -c 'import json, os; print(json.dumps({"name": os.environ["GITEA_TOKEN_NAME"], "scopes": ["write:repository"]}))')"
  GITEA_TOKEN="$(docker exec -i \
    -e GITEA_BASIC_B64="${BASIC_B64}" \
    -e GITEA_USER_ENC="${URL_ENCODED_USER}" \
    -e GITEA_TOKEN_JSON="${GITEA_TOKEN_JSON}" \
    "${GITEA_CONTAINER}" sh -c '
      printf "header = \"Authorization: Basic %s\"\n" "${GITEA_BASIC_B64}" | \
        curl -sf -X POST -K - -H "Content-Type: application/json" -d "${GITEA_TOKEN_JSON}" "http://127.0.0.1:3000/api/v1/users/${GITEA_USER_ENC}/tokens"
    ' | python3 -c 'import json, sys; print((json.load(sys.stdin) or {}).get("sha1", ""))' 2>/dev/null || true)"
fi

if [ -z "${GITEA_TOKEN}" ]; then
  log_error "Failed to mint scoped Gitea access token (${GITEA_TOKEN_NAME}) for '${PRIMARY_USER}'."
  exit 1
fi

# Atomically write scoped token (never raw password) to ${DATA_ROOT}/.git/credentials at 0600
CRED_USER="${PRIMARY_USER}" CRED_SECRET="${GITEA_TOKEN}" CRED_DEST="${CRED_FILE}" \
python3 - << 'PYEOF'
import os
import tempfile
import urllib.parse

u = urllib.parse.quote(os.environ["CRED_USER"], safe="")
s = urllib.parse.quote(os.environ["CRED_SECRET"], safe="")
dest = os.environ["CRED_DEST"]
dest_dir = os.path.dirname(os.path.abspath(dest))
os.makedirs(dest_dir, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(prefix=".credentials.", dir=dest_dir)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"http://{u}:{s}@gitea:3000\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, dest)
except Exception:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    raise
PYEOF
chown "${PUID:-1000}:${PGID:-1000}" "${CRED_FILE}" 2>/dev/null || true
chmod 600 "${CRED_FILE}" 2>/dev/null || true

# ------------------------------------------------------------------------------
# 5. Create Default Repository ('agent-box') & Push Initial Commit
# ------------------------------------------------------------------------------
log_info "Ensuring default repository '${PRIMARY_USER}/${DEFAULT_REPO}' exists in Gitea..."
CREATE_REPO_JSON="$(GITEA_REPO_NAME="${DEFAULT_REPO}" python3 -c 'import json, os; print(json.dumps({"name": os.environ["GITEA_REPO_NAME"], "description": "brainsOS Appliance Prompts, Souls, Skills & OKF Memories", "private": True, "auto_init": False, "default_branch": "main"}))')"
docker exec -i \
  -e GITEA_USER_ENC="${URL_ENCODED_USER}" \
  -e GITEA_REPO="${DEFAULT_REPO}" \
  -e GITEA_TOKEN="${GITEA_TOKEN}" \
  -e CREATE_REPO_JSON="${CREATE_REPO_JSON}" \
  "${GITEA_CONTAINER}" sh -c '
    REPO_ENC=$(printf "%s" "${GITEA_REPO}" | sed "s/ /%20/g")
    status=$(printf "header = \"Authorization: token %s\"\n" "${GITEA_TOKEN}" | curl -s -o /dev/null -w "%{http_code}" -K - "http://127.0.0.1:3000/api/v1/repos/${GITEA_USER_ENC}/${REPO_ENC}")
    if [ "${status}" != "200" ]; then
      printf "header = \"Authorization: token %s\"\n" "${GITEA_TOKEN}" | \
        curl -sf -X POST -K - -H "Content-Type: application/json" -d "${CREATE_REPO_JSON}" "http://127.0.0.1:3000/api/v1/user/repos" >/dev/null 2>&1 || true
    fi
  ' || true

# Push main and initial-setup branches using credential helper files (never credentials in CLI URLs)
PUSHED=false
if docker inspect -f '{{.State.Running}}' brainsos-app-code-server 2>/dev/null | grep -q "true"; then
  CLEAN_GITEA_URL="http://gitea:3000/${PRIMARY_USER}/${DEFAULT_REPO}.git"
  docker exec -e CLEAN_GITEA_URL="${CLEAN_GITEA_URL}" brainsos-app-code-server sh -c '
    rm -f /home/coder/.git-credentials
    git config --global --add safe.directory /data 2>/dev/null || true
    git config --global credential.helper "store --file=/data/.git/credentials" 2>/dev/null || true
    git config --global push.default simple 2>/dev/null || true
    git -C /data push -u "${CLEAN_GITEA_URL}" refs/heads/main:refs/heads/main refs/heads/initial-setup:refs/heads/initial-setup >/dev/null 2>&1
  ' && PUSHED=true || true
fi

if [ "${PUSHED}" != "true" ]; then
  TMP_PUSH_CRED="$(mktemp)"
  chmod 600 "${TMP_PUSH_CRED}"
  trap 'rm -f "${TMP_PUSH_CRED}"' EXIT
  GITEA_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${GITEA_CONTAINER}" 2>/dev/null | awk '{print $1}')"
  GITEA_HOST_PORT="${GITEA_HTTP_PORT:-3002}"
  CRED_USER="${PRIMARY_USER}" CRED_SECRET="${GITEA_TOKEN}" CRED_DEST="${TMP_PUSH_CRED}" \
  GITEA_IP_VAL="${GITEA_IP}" GITEA_PORT_VAL="${GITEA_HOST_PORT}" \
  python3 - << 'PYEOF'
import os, urllib.parse
u = urllib.parse.quote(os.environ["CRED_USER"], safe="")
s = urllib.parse.quote(os.environ["CRED_SECRET"], safe="")
lines = [f"http://{u}:{s}@127.0.0.1:{os.environ['GITEA_PORT_VAL']}\n"]
if os.environ.get("GITEA_IP_VAL"):
    lines.append(f"http://{u}:{s}@{os.environ['GITEA_IP_VAL']}:3000\n")
with open(os.environ["CRED_DEST"], "w", encoding="utf-8") as f:
    f.writelines(lines)
PYEOF

  if [ -n "${GITEA_IP}" ]; then
    CLEAN_IP_URL="http://${GITEA_IP}:3000/${PRIMARY_USER}/${DEFAULT_REPO}.git"
    git -C "${DATA_ROOT}" -c "credential.helper=store --file=${TMP_PUSH_CRED}" push -u "${CLEAN_IP_URL}" refs/heads/main:refs/heads/main refs/heads/initial-setup:refs/heads/initial-setup >/dev/null 2>&1 && PUSHED=true || true
  fi
  if [ "${PUSHED}" != "true" ]; then
    CLEAN_LOCAL_URL="http://127.0.0.1:${GITEA_HOST_PORT}/${PRIMARY_USER}/${DEFAULT_REPO}.git"
    git -C "${DATA_ROOT}" -c "credential.helper=store --file=${TMP_PUSH_CRED}" push -u "${CLEAN_LOCAL_URL}" refs/heads/main:refs/heads/main refs/heads/initial-setup:refs/heads/initial-setup >/dev/null 2>&1 && PUSHED=true || true
  fi
  rm -f "${TMP_PUSH_CRED}"
  trap - EXIT
fi

# Refresh remote tracking refs, upstream config, and permissions so VS Code sees main as published
git -C "${DATA_ROOT}" update-ref refs/remotes/origin/main HEAD 2>/dev/null || true
if [ -n "${INITIAL_SETUP_SHA:-}" ]; then
  git -C "${DATA_ROOT}" update-ref refs/remotes/origin/initial-setup "${INITIAL_SETUP_SHA}" 2>/dev/null || true
else
  git -C "${DATA_ROOT}" update-ref refs/remotes/origin/initial-setup HEAD 2>/dev/null || true
fi
git -C "${DATA_ROOT}" config branch.main.remote origin
git -C "${DATA_ROOT}" config branch.main.merge refs/heads/main
git -C "${DATA_ROOT}" config branch.initial-setup.remote origin
git -C "${DATA_ROOT}" config branch.initial-setup.merge refs/heads/initial-setup
git -C "${DATA_ROOT}" config push.default simple
git -C "${DATA_ROOT}" config credential.helper "store --file=${GIT_CREDENTIALS_FILE}"
chown -R "${PUID:-1000}:${PGID:-1000}" "${DATA_ROOT}/.git" 2>/dev/null || true
chmod 600 "${CRED_FILE}" 2>/dev/null || true

if docker inspect -f '{{.State.Running}}' brainsos-app-code-server 2>/dev/null | grep -q "true"; then
  docker exec brainsos-app-code-server git config --global credential.helper "store --file=/data/.git/credentials" 2>/dev/null || true
fi

if [ "${PUSHED}" = "true" ]; then
  log_success "Pushed '${DATA_ROOT}' (branches 'main' and 'initial-setup') to Gitea repository '${PRIMARY_USER}/${DEFAULT_REPO}'."
else
  log_warn "Configured remote '${REMOTE_URL}', but initial push could not reach Gitea endpoint yet."
fi

log_success "brainsOS Source Control (Gitea) & VS Code Git integration ready."
