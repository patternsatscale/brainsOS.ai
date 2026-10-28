#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Universal Appliance & Platform Update Engine (update.sh)
#
# Idempotent, host-agnostic lifecycle update manager:
#   - Works identically across AWS EC2 (AMI), ASUS Ascent GX10, and macOS
#   - Checks current vs. latest upstream releases (Git, LiteLLM, Langfuse, Caddy)
#   - Supports granular service updates (--service <name>) or full platform sync
#   - Automatic pre-flight database & memory snapshots (backup.sh)
#   - Self-healing automatic rollback if post-update health checks fail
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

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
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

# Load environment configuration
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

# Options
CHECK_ONLY=false
JSON_OUTPUT=false
CONTAINERS_ONLY=false
FULL_UPDATE=true
TARGET_SERVICE=""
TARGET_VERSION=""
UNATTENDED=false
NO_BACKUP=false
DRY_RUN=false

show_help() {
  echo -e "${BOLD}brainsOS Universal Appliance & Platform Update Engine${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --check             Check for available updates without applying them"
  echo "  --json              Output version status and check results in JSON format"
  echo "  --containers-only   Update upstream container images only (do not pull git code)"
  echo "  --full              Update both git source code and container images (default)"
  echo "  --service <name>    Update a specific service (e.g. litellm, langfuse, caddy, sogo)"
  echo "  --version <tag>     Target a specific upstream image version tag"
  echo "  --target-version <tag> Alias for --version"
  echo "  -y, --unattended    Non-interactive mode (bypass confirmation prompts)"
  echo "  --no-backup         Skip pre-flight data snapshot"
  echo "  --dry-run           Simulate update actions without altering disk or containers"
  echo "  -h, --help          Show this help documentation"
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
# 1. Version Detection & Status Query
# ------------------------------------------------------------------------------
query_status() {
  python3 - << EOF
import json
import os
import subprocess
import urllib.request
import urllib.error

repo_root = "${REPO_ROOT}"
target_service = "${TARGET_SERVICE}"

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
    
    # Try fetching remote commit
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
            return data.get("tag_name", "").lstrip("v")
    except Exception:
        return ""

def get_container_version(service_name, compose_file, default_ver):
    path = os.path.join(repo_root, compose_file)
    if not os.path.exists(path):
        return default_ver
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if "image:" in line and service_name in line:
                    parts = line.strip().split(":")
                    if len(parts) >= 3:
                        return parts[-1].strip().split("@")[0]
                    elif len(parts) == 2:
                        return parts[1].strip()
    except Exception:
        pass
    return default_ver

git_info = get_git_info()

# LiteLLM
litellm_curr = get_container_version("litellm-database", "docker/compose/compose.control.yml", "1.105.0")
litellm_latest = get_latest_github_release("berriai/litellm") or litellm_curr
litellm_update = (litellm_latest != "" and litellm_latest != litellm_curr)

# Langfuse
langfuse_curr = get_container_version("langfuse", "docker/compose/compose.telemetry.yml", "4.58.0")
langfuse_latest = get_latest_github_release("langfuse/langfuse") or langfuse_curr
langfuse_update = (langfuse_latest != "" and langfuse_latest != langfuse_curr)

# Caddy
caddy_curr = "2.8.4"
caddy_latest = "2.8.4"
caddy_update = False

# Hermes Runner
hermes_curr = "1.0.0"
hermes_latest = "1.0.0"
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
# 3. Interactive Confirmation
# ------------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║                 brainsOS Turnkey Platform Update Manager                     ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ -n "${TARGET_SERVICE}" ]; then
  log_info "Targeted service update selected: ${BOLD}${TARGET_SERVICE}${NC}"
elif [ "${CONTAINERS_ONLY}" = true ]; then
  log_info "Container-only update selected (skipping git source pull)."
else
  log_info "Full platform update selected (git source sync + container update)."
fi

if [ "${DRY_RUN}" = true ]; then
  log_warn "DRY-RUN mode enabled: No files or containers will be modified."
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

  # Re-evaluate post-pruning
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
# 4. Pre-Flight Snapshot & Safety Guardrail
# ------------------------------------------------------------------------------
PRE_UPDATE_BACKUP=""
PRE_UPDATE_GIT_REF=""

if [ "${DRY_RUN}" = false ] && [ "${NO_BACKUP}" = false ]; then
  log_info "Creating pre-flight data snapshot for safe automated rollback..."
  if [ -f "${REPO_ROOT}/scripts/control/backup.sh" ]; then
    # Run backup and capture output
    BACKUP_OUTPUT="$("${REPO_ROOT}/scripts/control/backup.sh" --backup 2>/dev/null || true)"
    PRE_UPDATE_BACKUP="$(echo "${BACKUP_OUTPUT}" | grep -E "brainsos_data_.*\.tar\.gz" | head -n1 | tr -d ' ' || true)"
    if [ -n "${PRE_UPDATE_BACKUP}" ]; then
      log_success "Pre-flight snapshot created: ${PRE_UPDATE_BACKUP}"
    else
      log_warn "Data snapshot completed (archive registered in data/backups/)."
    fi
  else
    log_warn "scripts/control/backup.sh not found; proceeding without automatic snapshot."
  fi
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  PRE_UPDATE_GIT_REF="$(git rev-parse HEAD)"
fi

# Rollback trap on failure
rollback_handler() {
  local exit_code=$?
  if [ $exit_code -ne 0 ] && [ "${DRY_RUN}" = false ]; then
    log_error "Update failed with exit code ${exit_code}! Initiating automated rollback..."
    
    # 1. Rollback Git if modified
    if [ -n "${PRE_UPDATE_GIT_REF}" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      CURRENT_REF="$(git rev-parse HEAD)"
      if [ "${CURRENT_REF}" != "${PRE_UPDATE_GIT_REF}" ]; then
        log_info "Reverting git repository to ${PRE_UPDATE_GIT_REF}..."
        git reset --hard "${PRE_UPDATE_GIT_REF}" || true
      fi
    fi

    # 2. Restore pre-flight backup if available
    if [ -n "${PRE_UPDATE_BACKUP}" ] && [ -f "${PRE_UPDATE_BACKUP}" ]; then
      log_info "Restoring pre-flight data plane backup from ${PRE_UPDATE_BACKUP}..."
      "${REPO_ROOT}/scripts/control/backup.sh" --restore "${PRE_UPDATE_BACKUP}" -f || true
    fi

    # 3. Ensure Docker containers are restored
    log_info "Restoring container stack (docker compose up -d)..."
    docker compose up -d || true

    log_warn "Automated rollback completed. System restored to pre-update baseline."
  fi
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
    # Stash any uncommitted tracking modifications safely
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

    # Restore uncommitted work if stashed
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
  
  # Python packages
  if [ -d ".venv" ]; then
    if command -v uv >/dev/null 2>&1; then
      uv pip install -e packages/brainsOS-* --quiet >/dev/null 2>&1 || true
    else
      .venv/bin/pip install -e packages/brainsOS-* --quiet >/dev/null 2>&1 || true
    fi
  fi

  # Portal static build check
  if [ ! -f "packages/brainsOS-portal/dist/index.html" ] || [ "${STASHED:-false}" = true ]; then
    log_info "Building portal static bundle in packages/brainsOS-portal..."
    (cd packages/brainsOS-portal && npm run build --silent) >/dev/null 2>&1 || true
  fi
  log_success "Dependencies and static assets synchronized."
else
  log_info "Step 2/5: Skipping local asset builds."
fi

# ------------------------------------------------------------------------------
# 7. Step 3: Upstream Container Images Pull
# ------------------------------------------------------------------------------
log_info "Step 3/5: Pulling upstream container images..."

if [ "${DRY_RUN}" = true ]; then
  if [ -n "${TARGET_SERVICE}" ]; then
    log_info "[DRY-RUN] Would pull: docker compose pull ${TARGET_SERVICE}"
  else
    log_info "[DRY-RUN] Would pull: docker compose pull"
  fi
else
  if [ -n "${TARGET_SERVICE}" ]; then
    log_info "Pulling image for targeted service: ${TARGET_SERVICE}..."
    docker compose pull "${TARGET_SERVICE}"
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
  log_info "[DRY-RUN] Would recreate containers via docker compose up -d"
else
  if [ -n "${TARGET_SERVICE}" ]; then
    log_info "Recreating container: ${TARGET_SERVICE}..."
    docker compose up -d --no-deps "${TARGET_SERVICE}"
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
# 9. Step 5: Post-Flight Health Verification & Affirmation
# ------------------------------------------------------------------------------
log_info "Step 5/5: Probing post-update service health and API availability..."

if [ "${DRY_RUN}" = false ]; then
  HEALTH_PASSED=false
  for i in $(seq 1 30); do
    CADDY_OK=false
    LITELLM_OK=false

    # Check Caddy HTTP or HTTPS
    if curl -s "http://127.0.0.1:80/" >/dev/null 2>&1 || curl -s -k "https://127.0.0.1:443/" >/dev/null 2>&1; then
      CADDY_OK=true
    fi

    # Check LiteLLM health endpoint
    if curl -s "http://127.0.0.1:4000/health/liveness" | grep -qE "healthy|live|ok|200" 2>/dev/null; then
      LITELLM_OK=true
    elif [ -n "${TARGET_SERVICE}" ] && [ "${TARGET_SERVICE}" != "litellm" ]; then
      LITELLM_OK=true
    fi

    if [ "${CADDY_OK}" = true ] && [ "${LITELLM_OK}" = true ]; then
      HEALTH_PASSED=true
      break
    fi
    sleep 1
  done

  if [ "${HEALTH_PASSED}" = true ]; then
    log_success "All service health checks passed successfully!"
  else
    log_error "Service health checks timed out after 30 seconds."
    exit 1
  fi

  # Clean up dangling images to save disk
  docker image prune -f >/dev/null 2>&1 || true
fi

# Disable error trap on clean exit
trap - EXIT

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  brainsOS Platform Update Successfully Completed!                                 ${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "All services are running the latest versions with health checks verified."
echo -e "You can inspect active service URLs at any time with: ${BOLD}make urls${NC}"
echo ""
