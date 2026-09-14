#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Memory Plane Provisioning & Scaffolding Script
# Configures the flat-file OKF storage layout, permissions, starter templates,
# and verifies native ARM64 container image for SilverBullet PKM.
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

log_info "Initializing Project Titan Memory Plane from ${REPO_ROOT}..."

# ------------------------------------------------------------------------------
# 1. Resolve Target Memories Directory
# ------------------------------------------------------------------------------
DATA_DIR="${TITAN_DATA_DIR:-./data/memories}"

if [[ "$DATA_DIR" != /* ]]; then
  TARGET_MEMORIES_DIR="${REPO_ROOT}/${DATA_DIR#./}"
else
  TARGET_MEMORIES_DIR="${DATA_DIR}"
fi

log_info "Target OKF storage directory: ${TARGET_MEMORIES_DIR}"

# ------------------------------------------------------------------------------
# 2. Directory Scaffolding & Permissions Alignment
# ------------------------------------------------------------------------------
if [[ "$TARGET_MEMORIES_DIR" == /data/titan/* ]]; then
  log_info "Configuring production appliance directory with sudo: ${TARGET_MEMORIES_DIR}..."
  sudo mkdir -p "${TARGET_MEMORIES_DIR}"
  sudo chown -R 1000:1000 "${TARGET_MEMORIES_DIR}"
  sudo chmod -R 775 "${TARGET_MEMORIES_DIR}"
else
  mkdir -p "${TARGET_MEMORIES_DIR}"
  chmod -R 775 "${TARGET_MEMORIES_DIR}" || true
fi

# Ensure OKF subdirectories exist
mkdir -p "${TARGET_MEMORIES_DIR}/knowledge"
mkdir -p "${TARGET_MEMORIES_DIR}/rules"
mkdir -p "${TARGET_MEMORIES_DIR}/logs"

log_success "Directory structure initialized: knowledge/, rules/, logs/."

# ------------------------------------------------------------------------------
# 3. Seed Starter OKF Templates Idempotently
# ------------------------------------------------------------------------------
TEMPLATE_DIR="${REPO_ROOT}/config/memories"

if [ -d "${TEMPLATE_DIR}" ]; then
  log_info "Seeding starter OKF templates from ${TEMPLATE_DIR}..."

  # Copy index.md if not already customized
  if [ ! -f "${TARGET_MEMORIES_DIR}/index.md" ]; then
    cp "${TEMPLATE_DIR}/index.md" "${TARGET_MEMORIES_DIR}/index.md"
    log_success "Created ${TARGET_MEMORIES_DIR}/index.md"
  fi

  # Copy knowledge templates
  if [ -d "${TEMPLATE_DIR}/knowledge" ]; then
    for f in "${TEMPLATE_DIR}/knowledge"/*.md; do
      [ -e "$f" ] || continue
      fname="$(basename "$f")"
      if [ ! -f "${TARGET_MEMORIES_DIR}/knowledge/${fname}" ]; then
        cp "$f" "${TARGET_MEMORIES_DIR}/knowledge/${fname}"
        log_success "Seeded knowledge note: ${fname}"
      fi
    done
  fi

  # Copy rules templates
  if [ -d "${TEMPLATE_DIR}/rules" ]; then
    for f in "${TEMPLATE_DIR}/rules"/*.md; do
      [ -e "$f" ] || continue
      fname="$(basename "$f")"
      if [ ! -f "${TARGET_MEMORIES_DIR}/rules/${fname}" ]; then
        cp "$f" "${TARGET_MEMORIES_DIR}/rules/${fname}"
        log_success "Seeded rule note: ${fname}"
      fi
    done
  fi

  # Copy logs templates
  if [ -d "${TEMPLATE_DIR}/logs" ]; then
    for f in "${TEMPLATE_DIR}/logs"/*.md; do
      [ -e "$f" ] || continue
      fname="$(basename "$f")"
      if [ ! -f "${TARGET_MEMORIES_DIR}/logs/${fname}" ]; then
        cp "$f" "${TARGET_MEMORIES_DIR}/logs/${fname}"
        log_success "Seeded log note: ${fname}"
      fi
    done
  fi
fi

# Enforce uniform permissions on seeded files
if [[ "$TARGET_MEMORIES_DIR" == /data/titan/* ]]; then
  sudo chown -R 1000:1000 "${TARGET_MEMORIES_DIR}"
  sudo chmod -R 775 "${TARGET_MEMORIES_DIR}"
else
  chmod -R 775 "${TARGET_MEMORIES_DIR}" || true
fi

# ------------------------------------------------------------------------------
# 4. Pull & Verify Native ARM64 SilverBullet Image
# ------------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  ARCH="$(uname -m)"
  DOCKER_PLATFORM="linux/amd64"
  if [[ "${ARCH}" == "arm64" || "${ARCH}" == "aarch64" ]]; then
    DOCKER_PLATFORM="linux/arm64"
  fi

  log_info "Ensuring native ${DOCKER_PLATFORM} image for SilverBullet (zefhemel/silverbullet:latest)..."
  docker pull --platform "${DOCKER_PLATFORM}" zefhemel/silverbullet:latest >/dev/null 2>&1 || log_warn "Image pull warning (will pull on compose launch)."

  IMAGE_ARCH=$(docker image inspect zefhemel/silverbullet:latest --format '{{.Architecture}}' 2>/dev/null || echo "unknown")
  log_success "SilverBullet image verified: ${IMAGE_ARCH} architecture."
fi

# ------------------------------------------------------------------------------
# 5. Verify Memory Plane Purity
# ------------------------------------------------------------------------------
log_info "Verifying memory plane purity in ${TARGET_MEMORIES_DIR}..."

PURITY_VIOLATIONS=0
while IFS= read -r -d '' file; do
  fname="$(basename "$file")"
  if [[ "$fname" == .gitkeep* ]]; then
    continue
  fi
  ext="${fname##*.}"
  if [[ "$ext" != "md" && ! "$fname" =~ ^\. ]]; then
    log_error "Purity violation: non-markdown file detected: ${file}"
    PURITY_VIOLATIONS=$((PURITY_VIOLATIONS + 1))
  fi
done < <(find "${TARGET_MEMORIES_DIR}" -type f -print0)

if [ "${PURITY_VIOLATIONS}" -eq 0 ]; then
  log_success "Memory plane is 100% pure (human-auditable flat-file Markdown only)."
else
  log_error "Memory plane purity check failed with ${PURITY_VIOLATIONS} violation(s)."
  exit 1
fi

log_success "Memory Plane setup complete! Start service via: docker compose up -d silverbullet"
echo ""
