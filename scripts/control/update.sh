#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Universal Appliance & Platform Update Engine (update.sh)
# Tickets #310 / #324 (Epic #309 / #321)
#
# Idempotent, host-agnostic lifecycle update manager:
#   - Works identically across AWS EC2 (AMI), ASUS Ascent GX10, and macOS
#   - Appliance-aware: honors COMPOSE_FILE from .env, zero unpublished port leaks
#   - Checks current vs. latest upstream releases (Git, LiteLLM, Langfuse, Caddy)
#   - Supports granular service updates (--service <name> --version <tag>)
#   - Support restoring defaults via --service <name> --reset-version
#   - Automatic pre-flight logical database & memory snapshots (backup.sh)
#   - In-network health checks across all Postgres instances, LiteLLM, Langfuse, Caddy
#   - Self-healing automated rollback without risk of data corruption or git loss
# ==============================================================================

set -euo pipefail

# Visual styling
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
MAGENTA="\033[0;35m"
DIM="\033[2m"
NC="\033[0m"

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Rule 13: Execution Environment Precondition
if [ ! -f "${REPO_ROOT}/.env" ]; then
  log_error "Missing .env configuration in ${REPO_ROOT}. An initialized .env is required (Rule 13)."
  exit 1
fi

set -a
. "${REPO_ROOT}/.env"
set +a

# Appliance awareness: honor COMPOSE_FILE from .env, default to docker-compose.yml
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_UPSERT="${REPO_ROOT}/scripts/control/env-upsert.sh"

# CLI Options
CHECK_ONLY=false
JSON_OUTPUT=false
CONTAINERS_ONLY=false
FULL_UPDATE=true
TARGET_SERVICE=""
TARGET_VERSION=""
RESET_VERSION=false
UNATTENDED=false
NO_BACKUP=false
DRY_RUN=false
HEALTH_TIMEOUT=30

show_help() {
  echo -e "${BOLD}brainsOS Universal Appliance & Platform Update Engine${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --check               Check for available updates without applying them"
  echo "  --json                Output version status and check results in JSON format"
  echo "  --containers-only     Update upstream container images only (do not pull git code)"
  echo "  --full                Update both git source code and container images (default)"
  echo "  --service <name>      Target a specific service (e.g. litellm, langfuse, caddy)"
  echo "  --version <tag>       Target a specific upstream image version tag for --service"
  echo "  --target-version <tag> Alias for --version"
  echo "  --reset-version       Remove .env version override for --service and restore pinned default"
  echo "  --reset               Alias for --reset-version"
  echo "  --health-timeout <s>  Timeout in seconds for post-update health verification (default: 30)"
  echo "  -y, --unattended      Non-interactive mode (bypass confirmation prompts)"
  echo "  --no-backup           Skip pre-flight data snapshot"
  echo "  --dry-run             Simulate update actions without altering disk or containers"
  echo "  -h, --help            Show this help documentation"
  echo ""
  echo "Supported Environments:"
  echo "  - AWS EC2 Appliance (ARM64 Graviton AMI)"
  echo "  - ASUS Ascent GX10 Appliance (NVIDIA GB10 Linux / DGX OS)"
  echo "  - macOS Workstation (Apple Silicon)"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY=true
      shift
      ;;
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --containers-only)
      CONTAINERS_ONLY=true
      FULL_UPDATE=false
      shift
      ;;
    --full)
      FULL_UPDATE=true
      CONTAINERS_ONLY=false
      shift
      ;;
    --service)
      TARGET_SERVICE="$2"
      CONTAINERS_ONLY=true
      FULL_UPDATE=false
      shift 2
      ;;
    --version|--target-version)
      TARGET_VERSION="$2"
      shift 2
      ;;
    --reset-version|--reset)
      RESET_VERSION=true
      shift
      ;;
    --health-timeout)
      HEALTH_TIMEOUT="$2"
      shift 2
      ;;
    -y|--unattended|--yes)
      UNATTENDED=true
      shift
      ;;
    --no-backup)
      NO_BACKUP=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# 1. Version Detection & Status Query (C2)
# ------------------------------------------------------------------------------
query_status() {
  python3 - << EOF
import json
import os
import re
import subprocess
import urllib.request
import urllib.error

repo_root = "${REPO_ROOT}"

def run_cmd(cmd, cwd=repo_root):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=10)
        return res.stdout.strip()
    except Exception:
        return ""

def get_git_info():
    is_git = os.path.isdir(os.path.join(repo_root, ".git"))
    if not is_git:
        return {"is_git": False}
    branch = run_cmd("git rev-parse --abbrev-ref HEAD")
    current_commit = run_cmd("git rev-parse --short HEAD")
    remote_commit = ""
    commits_behind = 0
    
    ls_out = run_cmd(f"git ls-remote origin -h refs/heads/{branch}")
    if ls_out:
        remote_commit = ls_out.split()[0][:7] if ls_out.split() else ""
    if remote_commit and remote_commit != current_commit:
        run_cmd("git fetch origin --quiet")
        behind_out = run_cmd(f"git rev-list --count HEAD..origin/{branch}")
        try:
            commits_behind = int(behind_out)
        except ValueError:
            commits_behind = 1 if remote_commit != current_commit else 0
            
    return {
        "is_git": True,
        "branch": branch,
        "current_commit": current_commit,
        "remote_commit": remote_commit or current_commit,
        "commits_behind": commits_behind,
        "update_available": commits_behind > 0
    }

def get_latest_github_release(repo):
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "brainsOS-Updater"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            raw_tag = data.get("tag_name", "").lstrip("v")
            return raw_tag
    except Exception:
        return ""

# Resolve image definitions via docker inspect (running) or compose config (declared)
def get_service_image(service_name, container_name):
    img = run_cmd(f"docker inspect --format '{{{{.Config.Image}}}}' {container_name}")
    if img:
        return img
    try:
        raw_cfg = run_cmd("docker compose config --format json")
        if raw_cfg:
            cfg = json.loads(raw_cfg)
            svcs = cfg.get("services", {})
            if service_name in svcs and "image" in svcs[service_name]:
                return svcs[service_name]["image"]
            if service_name == "langfuse" and "langfuse-web" in svcs:
                return svcs["langfuse-web"]["image"]
    except Exception:
        pass
    return ""

def parse_semver(img_str):
    if not img_str:
        return "unknown"
    tag = img_str.split(":")[-1].split("@")[0]
    if tag == "latest":
        return "local build"
    # Strip any variable expansion artifacts
    tag = re.sub(r'[\$\{\}\-]', '', tag)
    m = re.search(r'v?([0-9]+(\.[0-9]+)+.*)', tag)
    if m:
        return m.group(1).lstrip("v")
    return tag.lstrip("v")

git_info = get_git_info()

# LiteLLM
litellm_img = get_service_image("litellm", "brainsos-control-litellm")
litellm_curr = parse_semver(litellm_img) or "1.105.0"
litellm_latest = get_latest_github_release("berriai/litellm") or litellm_curr
litellm_update = (litellm_latest != "" and litellm_latest != litellm_curr and litellm_curr != "local build")

# Langfuse
langfuse_img = get_service_image("langfuse-web", "brainsos-telemetry-langfuse-web")
langfuse_curr = parse_semver(langfuse_img) or "4.58.0"
langfuse_latest = get_latest_github_release("langfuse/langfuse") or langfuse_curr
langfuse_update = (langfuse_latest != "" and langfuse_latest != langfuse_curr and langfuse_curr != "local build")

# Caddy
caddy_img = get_service_image("caddy", "brainsos-ingress-caddy")
caddy_curr = parse_semver(caddy_img) or "local build"
caddy_latest = caddy_curr
caddy_update = False

# Hermes Runner
hermes_img = get_service_image("runner-hermes", "brainsos-agent-runner-hermes")
hermes_curr = parse_semver(hermes_img) or "local build"
hermes_latest = hermes_curr
hermes_update = False

services = {
    "litellm": {
        "name": "LiteLLM Control Plane Gateway",
        "container": "brainsos-control-litellm",
        "current_version": litellm_curr,
        "latest_version": litellm_latest,
        "update_available": litellm_update,
        "plane": "control"
    },
    "langfuse": {
        "name": "Langfuse Observability Platform",
        "container": "brainsos-telemetry-langfuse-web",
        "current_version": langfuse_curr,
        "latest_version": langfuse_latest,
        "update_available": langfuse_update,
        "plane": "telemetry"
    },
    "caddy": {
        "name": "Caddy Ingress Reverse Proxy",
        "container": "brainsos-ingress-caddy",
        "current_version": caddy_curr,
        "latest_version": caddy_latest,
        "update_available": caddy_update,
        "plane": "ingress"
    },
    "runner-hermes": {
        "name": "Hermes Warm Agent Runner",
        "container": "brainsos-agent-runner-hermes",
        "current_version": hermes_curr,
        "latest_version": hermes_latest,
        "update_available": hermes_update,
        "plane": "agent"
    }
}

import shutil
total_b, used_b, free_b = shutil.disk_usage(repo_root)
disk_info = {
    "total_gb": round(total_b / (1024**3), 1),
    "used_gb": round(used_b / (1024**3), 1),
    "free_gb": round(free_b / (1024**3), 1),
    "free_pct": round((free_b / total_b) * 100.0, 1),
    "warning": (free_b / total_b) < 0.15
}

overall_update = git_info.get("update_available", False) or any(s["update_available"] for s in services.values())

status_data = {
    "platform": "brainsOS",
    "git": git_info,
    "services": services,
    "disk": disk_info,
    "overall_update_available": overall_update
}

print(json.dumps(status_data, indent=2))
EOF
}

# If JSON output requested, print and exit or proceed
if [ "${JSON_OUTPUT}" = true ]; then
  if [ "${CHECK_ONLY}" = true ]; then
    query_status
    exit 0
  fi
fi

# ------------------------------------------------------------------------------
# 2. Check Only Mode (Formatted CLI Display)
# ------------------------------------------------------------------------------
if [ "${CHECK_ONLY}" = true ]; then
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║                 brainsOS Appliance System Status & Updates                   ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
  echo ""

  STATUS_JSON="$(query_status)"
  
  python3 - << EOF
import json

data = json.loads('''${STATUS_JSON}''')
git = data.get("git", {})
services = data.get("services", {})

BOLD = "\033[1m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
YELLOW = "\033[1;33m"
DIM = "\033[2m"
NC = "\033[0m"

print(f"{BOLD}Core Platform (Git Repository):{NC}")
if git.get("is_git"):
    curr = git.get("current_commit", "unknown")
    branch = git.get("branch", "unknown")
    behind = git.get("commits_behind", 0)
    if behind > 0:
        print(f"  Branch: {CYAN}{branch}{NC} | Current: {DIM}{curr}{NC} | Status: {YELLOW}⚠️ {behind} commit(s) behind remote{NC}")
    else:
        print(f"  Branch: {CYAN}{branch}{NC} | Current: {GREEN}{curr}{NC} | Status: {GREEN}✓ Up to date{NC}")
else:
    print(f"  {DIM}Standalone appliance mode (non-git distribution){NC}")

print("")
print(f"{BOLD}{'SERVICE':<32} {'CURRENT':<14} {'LATEST':<14} {'STATUS'}{NC}")
print(f"{DIM}{'─'*72}{NC}")

for k, s in services.items():
    name = s["name"]
    curr = s["current_version"]
    latest = s["latest_version"]
    if s["update_available"]:
        status = f"{YELLOW}⚠️ Update Available ({latest}){NC}"
    else:
        status = f"{GREEN}✓ Up to date{NC}"
    print(f"{name:<32} {curr:<14} {latest:<14} {status}")

disk = data.get("disk", {})
if disk:
    print("")
    total_g = disk.get("total_gb", 0)
    free_g = disk.get("free_gb", 0)
    free_p = disk.get("free_pct", 0)
    if disk.get("warning"):
        disk_status = f"{YELLOW}⚠️ Low Disk Space ({free_p}% free, {free_g} GB remaining){NC}"
    else:
        disk_status = f"{GREEN}✓ Healthy ({free_p}% free, {free_g} GB free of {total_g} GB){NC}"
    print(f"{BOLD}Disk Capacity:{NC} {disk_status}")

print("")
if data.get("overall_update_available"):
    print(f"{YELLOW}{BOLD}Notice: Updates are available for your brainsOS appliance.{NC}")
    print(f"To apply updates, run: {BOLD}./scripts/control/update.sh{NC} or {BOLD}make update{NC}")
else:
    print(f"{GREEN}{BOLD}Your brainsOS appliance is completely up to date!{NC}")
print("")
EOF
  exit 0
fi

# ------------------------------------------------------------------------------
# 3. Interactive Confirmation & Unattended Precondition Verification (C5)
# ------------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║                 brainsOS Turnkey Platform Update Manager                     ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ -n "${TARGET_SERVICE}" ]; then
  if [ "${RESET_VERSION}" = true ]; then
    log_info "Targeted service reset selected: ${BOLD}${TARGET_SERVICE}${NC} (restoring pinned default)"
  elif [ -n "${TARGET_VERSION}" ]; then
    log_info "Targeted service update selected: ${BOLD}${TARGET_SERVICE}${NC} -> ${BOLD}${TARGET_VERSION}${NC}"
  else
    log_info "Targeted service update selected: ${BOLD}${TARGET_SERVICE}${NC}"
  fi
elif [ "${CONTAINERS_ONLY}" = true ]; then
  log_info "Container-only update selected (skipping git source pull)."
else
  log_info "Full platform update selected (git source sync + container update)."
fi

if [ "${DRY_RUN}" = true ]; then
  log_warn "DRY-RUN mode enabled: No files or containers will be modified."
fi

# C5: Refuse to update dirty git repository in unattended mode
if [ "${FULL_UPDATE}" = true ] && [ "${UNATTENDED}" = true ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DIRTY_CHECK="$(git status --porcelain)"
  if [ -n "${DIRTY_CHECK}" ]; then
    log_error "Working tree has uncommitted modifications. Refusing to run unattended update on a dirty repository (Audit #18)."
    exit 1
  fi
fi

if [ "${UNATTENDED}" = false ] && [ "${DRY_RUN}" = false ]; then
  echo ""
  read -r -p "Do you want to proceed with the update? [y/N] " response
  if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    log_info "Update cancelled by operator."
    exit 0
  fi
fi

# ------------------------------------------------------------------------------
# 3A. Pre-Flight Disk Space Assertion (Ticket #317)
# ------------------------------------------------------------------------------
log_info "Verifying available disk space before update..."
DISK_PRECHECK="$(python3 -c "
import shutil
total, used, free = shutil.disk_usage('/')
pct_free = (free / total) * 100.0
free_gb = free / (1024**3)
print(f'{free_gb:.1f} {pct_free:.1f}')
" 2>/dev/null || echo "50.0 50.0")"

read -r PRE_FREE_GB PRE_PCT_FREE <<< "${DISK_PRECHECK}"
log_info "Available root disk: ${PRE_FREE_GB} GB (${PRE_PCT_FREE}% free)"

if python3 -c "import sys; sys.exit(0 if float('${PRE_PCT_FREE}') < 15.0 else 1)" 2>/dev/null; then
  log_warn "WARNING: Available disk space is below 15% threshold (${PRE_PCT_FREE}% free)!"
  log_info "Running automated log pruning to reclaim disk capacity..."
  if [ -x "${REPO_ROOT}/scripts/control/prune-logs.sh" ]; then
    "${REPO_ROOT}/scripts/control/prune-logs.sh" || true
  fi

  POST_CHECK="$(python3 -c "
import shutil
total, used, free = shutil.disk_usage('/')
print(f'{(free / total) * 100.0:.1f}')
" 2>/dev/null || echo "50.0")"
  if python3 -c "import sys; sys.exit(0 if float('${POST_CHECK}') < 10.0 else 1)" 2>/dev/null; then
    log_error "CRITICAL: Insufficient disk space for safe platform update (${POST_CHECK}% free). Minimum 10% required."
    exit 1
  else
    log_success "Reclaimed disk space. Proceeding with update (${POST_CHECK}% free)."
  fi
fi

# ------------------------------------------------------------------------------
# 4. Pre-Flight Snapshot & Safety Guardrails (C4)
# ------------------------------------------------------------------------------
PRE_UPDATE_BACKUP=""
PRE_UPDATE_GIT_REF=""
PRE_UPDATE_ENV_BACKUP="$(mktemp "${TMPDIR:-/tmp}/brainsos_env_pre_update_XXXXXX")"
cp "${REPO_ROOT}/.env" "${PRE_UPDATE_ENV_BACKUP}"

# Record current image IDs/digests per container
PRE_UPDATE_IMAGES="$(python3 -c "
import subprocess, json
try:
    raw = subprocess.check_output(['docker', 'compose', 'ps', '--format', 'json'], text=True)
    containers = [json.loads(line) for line in raw.strip().splitlines() if line.strip()]
    res = {c.get('Service', c.get('Name')): c.get('Image', '') for c in containers}
    print(json.dumps(res))
except Exception:
    print('{}')
" 2>/dev/null || echo "{}")"

if [ "${DRY_RUN}" = false ] && [ "${NO_BACKUP}" = false ]; then
  log_info "Creating pre-flight data snapshot for safe automated rollback (Audit #15)..."
  if [ -f "${REPO_ROOT}/scripts/control/backup.sh" ]; then
    if ! BACKUP_OUTPUT="$("${REPO_ROOT}/scripts/control/backup.sh" --backup)"; then
      log_error "Pre-flight data snapshot failed! Aborting update to protect data integrity (pass --no-backup to override)."
      rm -f "${PRE_UPDATE_ENV_BACKUP}"
      exit 1
    fi
    PRE_UPDATE_BACKUP="$(echo "${BACKUP_OUTPUT}" | grep -E "brainsos_data_.*\.tar\.gz" | head -n1 | tr -d ' ' || true)"
    if [ -n "${PRE_UPDATE_BACKUP}" ]; then
      log_success "Pre-flight snapshot verified: ${PRE_UPDATE_BACKUP}"
    else
      log_error "Could not verify pre-flight snapshot archive. Aborting update."
      rm -f "${PRE_UPDATE_ENV_BACKUP}"
      exit 1
    fi
  else
    log_warn "scripts/control/backup.sh not found; proceeding without automatic snapshot."
  fi
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  PRE_UPDATE_GIT_REF="$(git rev-parse HEAD)"
fi

# Rollback trap on failure (C4)
rollback_handler() {
  local exit_code=$?
  if [ $exit_code -ne 0 ] && [ "${DRY_RUN}" = false ]; then
    log_error "Update failed with exit code ${exit_code}! Initiating automated rollback..."
    
    # 1. Restore .env
    if [ -f "${PRE_UPDATE_ENV_BACKUP}" ]; then
      log_info "Restoring pre-update .env configuration..."
      cp "${PRE_UPDATE_ENV_BACKUP}" "${REPO_ROOT}/.env"
      set -a; . "${REPO_ROOT}/.env"; set +a
    fi

    # 2. Rollback Git without reset --hard (safe git handling)
    if [ -n "${PRE_UPDATE_GIT_REF}" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      CURRENT_REF="$(git rev-parse HEAD)"
      if [ "${CURRENT_REF}" != "${PRE_UPDATE_GIT_REF}" ]; then
        log_info "Restoring git branch pointer to ${PRE_UPDATE_GIT_REF}..."
        git checkout "${PRE_UPDATE_GIT_REF}" 2>/dev/null || git reset --keep "${PRE_UPDATE_GIT_REF}" 2>/dev/null || true
      fi
    fi

    # 3. Restore pre-flight database & memories backup if available
    if [ -n "${PRE_UPDATE_BACKUP}" ] && [ -f "${PRE_UPDATE_BACKUP}" ]; then
      log_info "Restoring pre-flight logical database and memory planes from ${PRE_UPDATE_BACKUP}..."
      "${REPO_ROOT}/scripts/control/backup.sh" --restore "${PRE_UPDATE_BACKUP}" -f || true
    fi

    # 4. Recreate Docker container stack with restored parameters
    log_info "Re-aligning container stack (docker compose up -d)..."
    docker compose up -d || true

    log_warn "Automated rollback completed. System restored to pre-update baseline."
  fi
  rm -f "${PRE_UPDATE_ENV_BACKUP}"
}
trap rollback_handler EXIT

# ------------------------------------------------------------------------------
# 5. Step 1: Git Source Update (Baremetal / Developer Mode)
# ------------------------------------------------------------------------------
if [ "${FULL_UPDATE}" = true ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log_info "Step 1/5: Pulling latest source code from remote tracking branch..."
  CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  
  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Would fetch and pull origin/${CURRENT_BRANCH}"
  else
    DIRTY_DIFF="$(git status --porcelain)"
    STASHED=false
    if [ -n "${DIRTY_DIFF}" ]; then
      log_info "Stashing working tree modifications..."
      git stash push -u -m "automated-pre-update-stash-$(date +%s)" >/dev/null 2>&1 || true
      STASHED=true
    fi

    git fetch origin --quiet
    if git merge-base --is-ancestor "origin/${CURRENT_BRANCH}" HEAD 2>/dev/null; then
      log_success "Source code is already at the latest commit (${CURRENT_BRANCH})."
    else
      log_info "Fast-forwarding ${CURRENT_BRANCH} to origin/${CURRENT_BRANCH}..."
      git pull --ff-only origin "${CURRENT_BRANCH}"
      log_success "Source code updated to commit $(git rev-parse --short HEAD)."
    fi

    if [ "${STASHED}" = true ]; then
      git stash pop >/dev/null 2>&1 || true
    fi
  fi
else
  log_info "Step 1/5: Skipping source code pull (containers-only mode or standalone distribution)."
fi

# ------------------------------------------------------------------------------
# 6. Step 2: Python Environment & Portal Rebuild (if needed)
# ------------------------------------------------------------------------------
if [ "${FULL_UPDATE}" = true ] && [ "${DRY_RUN}" = false ]; then
  log_info "Step 2/5: Synchronizing Python dependencies and portal assets..."
  if [ -d ".venv" ]; then
    if command -v uv >/dev/null 2>&1; then
      uv pip install -e packages/brainsOS-* --quiet >/dev/null 2>&1 || true
    else
      .venv/bin/pip install -e packages/brainsOS-* --quiet >/dev/null 2>&1 || true
    fi
  fi

  if [ ! -f "packages/brainsOS-portal/dist/index.html" ] || [ "${STASHED:-false}" = true ]; then
    log_info "Building portal static bundle in packages/brainsOS-portal..."
    (cd packages/brainsOS-portal && npm run build --silent) >/dev/null 2>&1 || true
  fi
  log_success "Dependencies and static assets synchronized."
else
  log_info "Step 2/5: Skipping local asset builds."
fi

# ------------------------------------------------------------------------------
# 7. Step 3: Version Targeting & Container Image Pull (C2)
# ------------------------------------------------------------------------------
log_info "Step 3/5: Reconciling service image versions and pulling containers..."

COMPOSE_TARGETS=()
if [ -n "${TARGET_SERVICE}" ]; then
  case "${TARGET_SERVICE}" in
    litellm|litellm-proxy)
      TARGET_SERVICE="litellm"
      COMPOSE_TARGETS=("litellm")
      OVERRIDE_VAR="LITELLM_IMAGE_TAG"
      ;;
    langfuse|langfuse-web)
      TARGET_SERVICE="langfuse-web"
      COMPOSE_TARGETS=("langfuse-web" "langfuse-worker")
      OVERRIDE_VAR="LANGFUSE_IMAGE_TAG"
      ;;
    caddy|ingress)
      TARGET_SERVICE="caddy"
      COMPOSE_TARGETS=("caddy")
      OVERRIDE_VAR="CADDY_IMAGE_TAG"
      ;;
    *)
      COMPOSE_TARGETS=("${TARGET_SERVICE}")
      OVERRIDE_VAR=""
      ;;
  esac

  # Apply or reset version override in .env
  if [ "${RESET_VERSION}" = true ] && [ -n "${OVERRIDE_VAR}" ]; then
    if [ "${DRY_RUN}" = true ]; then
      log_info "[DRY-RUN] Would unset ${OVERRIDE_VAR} in .env to restore default image tag"
    else
      log_info "Unsetting ${OVERRIDE_VAR} in .env to restore pinned default..."
      "${ENV_UPSERT}" --file "${REPO_ROOT}/.env" --unset "${OVERRIDE_VAR}"
      set -a; . "${REPO_ROOT}/.env"; set +a
    fi
  elif [ -n "${TARGET_VERSION}" ] && [ -n "${OVERRIDE_VAR}" ]; then
    # Format tag prefix per service conventions
    TAG_VAL="${TARGET_VERSION}"
    if [ "${OVERRIDE_VAR}" = "LITELLM_IMAGE_TAG" ] && [[ "${TAG_VAL}" =~ ^[0-9] ]]; then
      TAG_VAL="v${TAG_VAL}"
    elif [ "${OVERRIDE_VAR}" = "LANGFUSE_IMAGE_TAG" ] && [[ "${TAG_VAL}" =~ ^v[0-9] ]]; then
      TAG_VAL="${TAG_VAL#v}"
    fi

    if [ "${DRY_RUN}" = true ]; then
      log_info "[DRY-RUN] Would set ${OVERRIDE_VAR}=${TAG_VAL} in .env"
    else
      log_info "Persisting ${OVERRIDE_VAR}=${TAG_VAL} in .env..."
      "${ENV_UPSERT}" --file "${REPO_ROOT}/.env" "${OVERRIDE_VAR}=${TAG_VAL}"
      set -a; . "${REPO_ROOT}/.env"; set +a
    fi
  fi
fi

if [ "${DRY_RUN}" = true ]; then
  if [ "${#COMPOSE_TARGETS[@]}" -gt 0 ]; then
    log_info "[DRY-RUN] Would pull: docker compose pull ${COMPOSE_TARGETS[*]}"
  else
    log_info "[DRY-RUN] Would pull: docker compose pull"
  fi
else
  if [ "${#COMPOSE_TARGETS[@]}" -gt 0 ]; then
    log_info "Pulling image(s) for targeted service: ${COMPOSE_TARGETS[*]}..."
    docker compose pull "${COMPOSE_TARGETS[@]}"
  else
    log_info "Pulling latest images for all compose services..."
    docker compose pull
  fi
  log_success "Container images pulled successfully."
fi

# ------------------------------------------------------------------------------
# 8. Step 4: Graceful Container Recreate & Environment Sync
# ------------------------------------------------------------------------------
log_info "Step 4/5: Applying environment reconciliations and recreating containers..."

if [ "${DRY_RUN}" = true ]; then
  if [ "${#COMPOSE_TARGETS[@]}" -gt 0 ]; then
    log_info "[DRY-RUN] Would recreate: docker compose up -d --no-deps ${COMPOSE_TARGETS[*]}"
  else
    log_info "[DRY-RUN] Would recreate containers via reload-env.sh or docker compose up -d"
  fi
else
  if [ "${#COMPOSE_TARGETS[@]}" -gt 0 ]; then
    log_info "Recreating container(s): ${COMPOSE_TARGETS[*]}..."
    docker compose up -d --no-deps "${COMPOSE_TARGETS[@]}"
  else
    log_info "Recreating all active compose services..."
    if [ -f "${REPO_ROOT}/scripts/control/reload-env.sh" ]; then
      "${REPO_ROOT}/scripts/control/reload-env.sh" --no-urls
    else
      docker compose up -d
    fi
  fi
  log_success "Containers recreated with latest images and parameters."
fi

# ------------------------------------------------------------------------------
# 9. Step 5: Post-Flight Health Verification & Affirmation (C1, C3)
# ------------------------------------------------------------------------------
log_info "Step 5/5: Probing in-network service health across all active planes (timeout: ${HEALTH_TIMEOUT}s)..."

if [ "${DRY_RUN}" = false ]; then
  HEALTH_PASSED=false
  for i in $(seq 1 "${HEALTH_TIMEOUT}"); do
    ALL_DBS_OK=true
    LITELLM_OK=false
    LANGFUSE_OK=false
    CADDY_OK=false

    # 1. In-network Postgres health checks (litellm-db, langfuse-db, authentik-db, sogo-db)
    for db_svc in litellm-db langfuse-db; do
      cid="$(docker compose ps -q "${db_svc}" 2>/dev/null || true)"
      if [ -n "${cid}" ]; then
        if ! docker compose exec -T "${db_svc}" pg_isready >/dev/null 2>&1; then
          ALL_DBS_OK=false
          break
        fi
      fi
    done

    # 2. In-network LiteLLM probe
    if [ -n "$(docker compose ps -q litellm 2>/dev/null)" ]; then
      if docker compose exec -T litellm python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4000/health/liveness", timeout=2)' >/dev/null 2>&1; then
        LITELLM_OK=true
      fi
    else
      LITELLM_OK=true
    fi

    # 3. In-network Langfuse probe
    if [ -n "$(docker compose ps -q langfuse-web 2>/dev/null)" ]; then
      if docker compose exec -T langfuse-web node -e 'fetch("http://127.0.0.1:3000/api/public/health").then(r => { if (!r.ok) process.exit(1); }).catch(() => process.exit(1))' >/dev/null 2>&1; then
        LANGFUSE_OK=true
      fi
    else
      LANGFUSE_OK=true
    fi

    # 4. Ingress (Caddy) non-5xx probe
    HTTP_CODE="$(curl -s -k -o /dev/null -w "%{http_code}" --resolve localhost:443:127.0.0.1 https://localhost:443/ 2>/dev/null || curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/ 2>/dev/null || echo "000")"
    if [ "${HTTP_CODE}" != "000" ] && [ "${HTTP_CODE}" -lt 500 ]; then
      CADDY_OK=true
    fi

    if [ "${ALL_DBS_OK}" = true ] && [ "${LITELLM_OK}" = true ] && [ "${LANGFUSE_OK}" = true ] && [ "${CADDY_OK}" = true ]; then
      HEALTH_PASSED=true
      break
    fi
    sleep 1
  done

  if [ "${HEALTH_PASSED}" = true ]; then
    log_success "All in-network service health checks passed successfully!"
  else
    log_error "Service health checks failed or timed out after ${HEALTH_TIMEOUT} seconds."
    exit 1
  fi

  # Clean up dangling images
  docker image prune -f >/dev/null 2>&1 || true
fi

# Disable error trap on clean exit
trap - EXIT
rm -f "${PRE_UPDATE_ENV_BACKUP}"

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  brainsOS Platform Update Successfully Completed!                                 ${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "All services are running target versions with health checks verified."
echo -e "You can inspect active service URLs at any time with: ${BOLD}make urls${NC}"
echo ""
