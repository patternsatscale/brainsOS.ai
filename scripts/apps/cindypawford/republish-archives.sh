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

DATA_ROOT="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}"

CINDY_ROOT="${DATA_ROOT}/agents/bawtford/apps/cindypawford"
if [ ! -d "${CINDY_ROOT}" ]; then
  if [ -d "${REPO_ROOT}/data/agents/bawtford/apps/cindypawford" ]; then
    CINDY_ROOT="${REPO_ROOT}/data/agents/bawtford/apps/cindypawford"
  elif [ -d "${DATA_ROOT}/agent_apps/cindypawford" ]; then
    CINDY_ROOT="${DATA_ROOT}/agent_apps/cindypawford"
  elif [ -d "${REPO_ROOT}/config/default_agents/bawtford/apps/cindypawford" ]; then
    CINDY_ROOT="${REPO_ROOT}/config/default_agents/bawtford/apps/cindypawford"
  fi
fi

SITE_DIR="${CINDY_ROOT}/site"
ARCHIVE_DIR="${CINDY_ROOT}/archive"
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
      SLUG=$(echo "${tag}" | sed 's|^archive/cindy-||')
      if [[ ! "${SLUG}" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "${SLUG}" == *".."* ]] || [ "${SLUG}" = ".git" ] || [ "${SLUG}" = ".github" ]; then
        log_error "Refused unsafe archive slug '${SLUG}' from tag '${tag}'."
        exit 1
      fi
      TARGET_DIR="${ARCHIVE_DIR}/${SLUG}"
      log_info "Processing Git archive tag: '${tag}' -> '${SLUG}'"
      if [ ! -d "${TARGET_DIR}" ] || [ "${FORCE}" -eq 1 ]; then
        log_info "Extracting tag '${tag}' tree into '${TARGET_DIR}'..."
        if [ "${DRY_RUN}" -eq 0 ]; then
          if ! git -C "${SITE_DIR}" archive --format=tar "${tag}" | \
            ARCHIVE_DIR="${ARCHIVE_DIR}" SLUG="${SLUG}" python3 -c '
import os
import posixpath
import re
import sys
import tarfile

archive_dir = os.environ["ARCHIVE_DIR"]
slug = os.environ["SLUG"]
if not re.match(r"^[A-Za-z0-9._-]+$", slug) or ".." in slug or slug.lower() in {".git", ".github"}:
    raise SystemExit(f"Unsafe archive slug: {slug!r}")

real_archive = os.path.realpath(archive_dir)
target_dir = os.path.realpath(os.path.join(real_archive, slug))
if target_dir == real_archive or os.path.commonpath([real_archive, target_dir]) != real_archive:
    raise SystemExit(f"Archive target escapes ARCHIVE_DIR: {target_dir}")
os.makedirs(target_dir, exist_ok=True)

with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as tf:
    for member in tf:
        raw_name = member.name[2:] if member.name.startswith("./") else member.name
        if not raw_name or raw_name == ".":
            continue
        if member.name.startswith("/") or ".." in raw_name.split("/"):
            raise SystemExit(f"Blocked traversal member in git archive: {member.name!r}")
        norm = posixpath.normpath(raw_name)
        parts = [p for p in norm.split("/") if p and p != "."]
        if any(p.lower() in {".git", ".github"} or p == ".." for p in parts):
            raise SystemExit(f"Blocked forbidden path segment in git archive: {member.name!r}")
        if member.issym() or member.islnk():
            raise SystemExit(f"Blocked symlink/hardlink in git archive: {member.name!r}")
        if not (member.isdir() or member.isreg()):
            continue
        dest = os.path.realpath(os.path.join(target_dir, *parts))
        if os.path.commonpath([target_dir, dest]) != target_dir:
            raise SystemExit(f"Resolved member escapes target directory: {member.name!r}")
        if member.isdir():
            os.makedirs(dest, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src_f = tf.extractfile(member)
            if src_f is not None:
                with src_f, open(dest, "wb") as out_f:
                    out_f.write(src_f.read())
'; then
            log_error "Refused unsafe archive tag '${tag}'."
            exit 1
          fi
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
  ARCHIVE_DIR="${ARCHIVE_DIR}" ERAS_FILE="${ERAS_FILE}" python3 - << 'EOF'
import datetime
import json
import os
import re

archive_dir = os.path.realpath(os.environ["ARCHIVE_DIR"])
eras_file = os.path.realpath(os.environ["ERAS_FILE"])
if os.path.commonpath([archive_dir, eras_file]) != archive_dir:
    raise SystemExit(f"Unsafe ERAS_FILE path outside ARCHIVE_DIR: {eras_file}")

existing_eras = []
if os.path.exists(eras_file) and not os.path.islink(eras_file):
    try:
        with open(eras_file, "r", encoding="utf-8") as f:
            existing_eras = json.load(f).get("eras", [])
    except Exception:
        existing_eras = []

existing_map = {e.get("slug"): e for e in existing_eras}

# Discover all safe era directories inside archive_dir
subdirs = []
for d in os.listdir(archive_dir):
    if d.startswith(".") or d.lower() in {".git", ".github"}:
        continue
    if not re.match(r"^[A-Za-z0-9._-]+$", d) or ".." in d:
        continue
    cand = os.path.join(archive_dir, d)
    if os.path.islink(cand):
        continue
    real_cand = os.path.realpath(cand)
    if os.path.commonpath([archive_dir, real_cand]) != archive_dir or real_cand == archive_dir:
        continue
    if os.path.isdir(real_cand):
        subdirs.append(d)

# Sort with 2024-genesis always first, then chronologically
def sort_key(item):
    if item == "2024-genesis":
        return "0000"
    return item

subdirs.sort(key=sort_key)

reconciled = []
for idx, slug in enumerate(subdirs, start=1):
    era_root = os.path.realpath(os.path.join(archive_dir, slug))
    rec_candidate = os.path.join(era_root, "recap.json")
    rec_path = os.path.realpath(rec_candidate)
    recap = {}
    if (
        not os.path.islink(rec_candidate)
        and os.path.commonpath([era_root, rec_path]) == era_root
        and os.path.exists(rec_path)
    ):
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
