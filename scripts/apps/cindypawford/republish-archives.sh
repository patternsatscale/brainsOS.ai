#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Out-of-Band Cindy Pawford Digital Museum Republishing Tool
# Ticket #88 (CW-0B): Rebuild & Restore Archives Directly from Git Tags
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

SITE_DIR="${REPO_ROOT}/data/agent_apps/cindypawford/site"
ARCHIVE_DIR="${REPO_ROOT}/data/agent_apps/cindypawford/archive"
ERAS_FILE="${ARCHIVE_DIR}/eras.json"

DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      log_error "Unknown option: $1"
      exit 1
      ;;
  esac
done

log_info "================================================================="
log_info "  Running Cindy Pawford Digital Museum Republishing Tool        "
log_info "================================================================="

if [ "${DRY_RUN}" -eq 1 ]; then
  log_info "[DRY-RUN MODE ACTIVATED] No files will be modified."
fi

mkdir -p "${ARCHIVE_DIR}"

# ------------------------------------------------------------------------------
# 1. Verify / Restore 2024 Genesis Archive
# ------------------------------------------------------------------------------
GENESIS_DIR="${ARCHIVE_DIR}/2024-genesis"
GENESIS_SRC="/Users/pats/Development/pas-webapps/packages/pawford-pet-company/dist"

if [ ! -d "${GENESIS_DIR}" ] || [ ! -f "${GENESIS_DIR}/index.html" ]; then
  log_warn "2024 Genesis archive missing or incomplete in ${GENESIS_DIR}."
  if [ -d "${GENESIS_SRC}" ]; then
    log_info "Restoring Genesis era from source distribution: ${GENESIS_SRC}..."
    if [ "${DRY_RUN}" -eq 0 ]; then
      mkdir -p "${GENESIS_DIR}"
      cp -r "${GENESIS_SRC}/"* "${GENESIS_DIR}/"
      sed -i.bak -e 's|src="/assets/|src="./assets/|g' -e 's|href="/assets/|href="./assets/|g' -e 's|href="/vite.svg"|href="./vite.svg"|g' "${GENESIS_DIR}/index.html" 2>/dev/null && rm -f "${GENESIS_DIR}/index.html.bak" || true
      cat << 'EOF' > "${GENESIS_DIR}/recap.json"
{
  "era": 1,
  "slug": "2024-genesis",
  "theme_name": "The Genesis Atelier",
  "date_range": "2024-03-15 to 2024-06-19",
  "closing_quote": "Luxury canine couture isn't just an aesthetic, darling—it's a corporate imperative.",
  "founding_quote": "Luxury canine couture isn't just an aesthetic, darling—it's a corporate imperative.",
  "coding_model": "gpt-4-turbo",
  "stats": {
    "models_featured": 5,
    "bacon_strips_demanded": 1000,
    "mailmen_barked_at": 42
  }
}
EOF
      log_success "Restored 2024 Genesis era."
    fi
  else
    log_warn "Genesis source distribution not found at ${GENESIS_SRC}."
  fi
else
  log_success "Verified 2024 Genesis era present in archive vault."
fi

# ------------------------------------------------------------------------------
# 2. Ingest Archives from Git Tags in CindyPawford-Online
# ------------------------------------------------------------------------------
log_info "Scanning Git repository tags for archive snapshots..."

if [ -d "${SITE_DIR}/.git" ]; then
  # Fetch latest tags from origin if remote exists
  if [ "${DRY_RUN}" -eq 0 ] && git -C "${SITE_DIR}" remote get-url origin >/dev/null 2>&1; then
    git -C "${SITE_DIR}" fetch --tags >/dev/null 2>&1 || true
  fi

  TAGS=$(git -C "${SITE_DIR}" tag -l "archive/cindy-*" 2>/dev/null || true)
  if [ -n "${TAGS}" ]; then
    for tag in ${TAGS}; do
      SLUG=$(echo "${tag}" | sed 's|archive/cindy-||')
      TARGET_DIR="${ARCHIVE_DIR}/${SLUG}"
      log_info "Processing Git archive tag: '${tag}' -> '${SLUG}'"
      if [ ! -d "${TARGET_DIR}" ] || [ "${FORCE}" -eq 1 ]; then
        log_info "Extracting tag '${tag}' tree into '${TARGET_DIR}'..."
        if [ "${DRY_RUN}" -eq 0 ]; then
          mkdir -p "${TARGET_DIR}"
          git -C "${SITE_DIR}" archive --format=tar "${tag}" | tar -x -C "${TARGET_DIR}"
          log_success "Restored snapshot for '${SLUG}' from Git tag."
        fi
      else
        log_info "Snapshot '${SLUG}' already present; skipping extraction."
      fi
    done
  else
    log_info "No archive Git tags matching 'archive/cindy-*' found in ${SITE_DIR}."
  fi
fi

# ------------------------------------------------------------------------------
# 3. Regenerate Ledger (eras.json)
# ------------------------------------------------------------------------------
log_info "Reconciling historical ledger (eras.json)..."

if [ "${DRY_RUN}" -eq 0 ]; then
  python3 - << EOF
import os, json, datetime

archive_dir = "${ARCHIVE_DIR}"
eras_file = "${ERAS_FILE}"

existing_eras = []
if os.path.exists(eras_file):
    try:
        with open(eras_file, "r", encoding="utf-8") as f:
            existing_eras = json.load(f).get("eras", [])
    except Exception:
        existing_eras = []

existing_map = {e.get("slug"): e for e in existing_eras}

# Discover all era directories
subdirs = [d for d in os.listdir(archive_dir) if os.path.isdir(os.path.join(archive_dir, d)) and not d.startswith(".")]

# Sort with 2024-genesis always first, then chronologically
def sort_key(item):
    if item == "2024-genesis":
        return "0000"
    return item

subdirs.sort(key=sort_key)

reconciled = []
for idx, slug in enumerate(subdirs, start=1):
    rec_path = os.path.join(archive_dir, slug, "recap.json")
    recap = {}
    if os.path.exists(rec_path):
        try:
            with open(rec_path, "r", encoding="utf-8") as rf:
                recap = json.load(rf)
        except Exception:
            pass
    
    prev = existing_map.get(slug, {})
    entry = {
        "era": idx,
        "slug": slug,
        "theme_name": recap.get("theme_name") or prev.get("theme_name") or f"Era {idx} ({slug})",
        "date_range": recap.get("date_range") or prev.get("date_range") or "Historic Period",
        "quote": recap.get("closing_quote") or recap.get("founding_quote") or prev.get("quote") or "The runway never sleeps.",
        "coding_model": recap.get("coding_model") or prev.get("coding_model") or "brainsos-core",
        "archived_at": prev.get("archived_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    reconciled.append(entry)

ledger = {
    "total_eras": len(reconciled),
    "active_era": len(reconciled),
    "eras": reconciled
}

with open(eras_file, "w", encoding="utf-8") as f:
    json.dump(ledger, f, indent=2)

print(f"[SUCCESS] Reconciled {len(reconciled)} eras in {eras_file}.")
EOF
fi

# ------------------------------------------------------------------------------
# 4. Rebuild Museum Gallery Wall
# ------------------------------------------------------------------------------
log_info "Rebuilding digital museum gallery wall..."
if [ "${DRY_RUN}" -eq 0 ]; then
  python3 "${REPO_ROOT}/scripts/apps/cindypawford/build-archive-portal.py"
fi

log_info "================================================================="
log_success "  Republishing and Archive Rebuilding Complete!                 "
log_info "================================================================="
