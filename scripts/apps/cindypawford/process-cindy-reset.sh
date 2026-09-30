#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Cindy Pawford 'Seal & Reset' Execution Engine
# Ticket #88 (CW-0B): Host-Side Weekly Archive, Git Tagging & Model Rotation
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

# Load environment
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  . ./.env.example
  set +a
fi

CINDY_ROOT="${REPO_ROOT}/data/agent_apps/cindypawford"
SITE_DIR="${CINDY_ROOT}/site"
ARCHIVE_DIR="${CINDY_ROOT}/archive"
TRIGGER_FILE="${SITE_DIR}/.archive-ready"
RECAP_FILE="${SITE_DIR}/recap.json"
ERAS_FILE="${ARCHIVE_DIR}/eras.json"
if [ -f "${REPO_ROOT}/data/runners/hermes/model_pool.json" ]; then
  MODEL_POOL_FILE="${REPO_ROOT}/data/runners/hermes/model_pool.json"
else
  MODEL_POOL_FILE="${REPO_ROOT}/config/default_runners/hermes/model_pool.json"
fi
LITELLM_CONFIG="${REPO_ROOT}/config/litellm/config.yaml"
CLEAN_SLATE_DIR="${CINDY_ROOT}/clean-slate"

# Detect Python binary
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  PYTHON_BIN="python"
fi

FORCE=0
CUSTOM_SLUG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --week-slug)
      CUSTOM_SLUG="$2"
      shift 2
      ;;
    *)
      log_error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# ------------------------------------------------------------------------------
# 1. Trigger Check
# ------------------------------------------------------------------------------
if [ "${FORCE}" -eq 0 ] && [ ! -f "${TRIGGER_FILE}" ]; then
  log_info "No archive trigger detected (${TRIGGER_FILE} not found). Nothing to seal."
  exit 0
fi

WEEK_SLUG="${CUSTOM_SLUG:-$(date +%Y-w%U)}"
SNAPSHOT_DIR="${ARCHIVE_DIR}/${WEEK_SLUG}"

log_info "================================================================="
log_info "  Executing Cindy Pawford 'Seal & Reset' Pipeline: ${WEEK_SLUG}  "
log_info "================================================================="

# ------------------------------------------------------------------------------
# 2. Freeze and Snapshot /app/html BEFORE Wiping
# ------------------------------------------------------------------------------
log_info "Phase 1: Freezing live canvas into immutable vault at ${SNAPSHOT_DIR}..."

if [ -d "${SNAPSHOT_DIR}" ]; then
  log_warn "Snapshot destination '${SNAPSHOT_DIR}' already exists. Overwriting with clean freeze..."
  rm -rf "${SNAPSHOT_DIR}"
fi

mkdir -p "${SNAPSHOT_DIR}"

# Copy all site files into archive, strictly excluding .git repository metadata and trigger files
if [ -d "${SITE_DIR}" ]; then
  # Use rsync or tar for clean exclusion
  tar -C "${SITE_DIR}" \
      --exclude=".git" \
      --exclude=".git/*" \
      --exclude=".archive-ready" \
      -cf - . | tar -C "${SNAPSHOT_DIR}" -xf -
fi

log_success "Canvas frozen successfully at ${SNAPSHOT_DIR}."

# ------------------------------------------------------------------------------
# 3. Parse Cindy's recap.json & Update Historical Ledger (eras.json)
# ------------------------------------------------------------------------------
log_info "Phase 2: Ingesting era recap metadata and updating historical ledger..."

THEME_NAME="Atelier Collection ${WEEK_SLUG}"
DATE_RANGE="$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d '7 days ago' +%Y-%m-%d 2>/dev/null || echo "Past Week") to $(date +%Y-%m-%d)"
CLOSING_QUOTE="A true supermodel never looks back, unless there is warm bacon behind her."
CURRENT_CODING_MODEL="brainsos-core"

if [ -f "${RECAP_FILE}" ]; then
  log_info "Found agent recap at ${RECAP_FILE}."
  # Use Python to safely parse JSON
  PARSED_DATA=$(${PYTHON_BIN} - << EOF
import json, sys
try:
    with open("${RECAP_FILE}", "r", encoding="utf-8") as f:
        d = json.load(f)
    print(d.get("theme_name", "${THEME_NAME}"))
    print(d.get("date_range", "${DATE_RANGE}"))
    print(d.get("closing_quote", d.get("founding_quote", "${CLOSING_QUOTE}")))
except Exception as e:
    print("${THEME_NAME}")
    print("${DATE_RANGE}")
    print("${CLOSING_QUOTE}")
EOF
)
  THEME_NAME=$(echo "${PARSED_DATA}" | sed -n '1p')
  DATE_RANGE=$(echo "${PARSED_DATA}" | sed -n '2p')
  CLOSING_QUOTE=$(echo "${PARSED_DATA}" | sed -n '3p')
fi

# Detect current active coding model from config/litellm/config.yaml or eras.json
if grep -q "cindy-active-coding-model" "${LITELLM_CONFIG}" 2>/dev/null; then
  CURRENT_CODING_MODEL=$(awk '/model_name: cindy-active-coding-model/{getline; getline; print $2}' "${LITELLM_CONFIG}" | sed 's|ollama_chat/||')
fi
CURRENT_CODING_MODEL="${CURRENT_CODING_MODEL:-brainsos-core}"

# Update eras.json
ERA_RECORD=$(${PYTHON_BIN} - << EOF
import json, os, datetime

eras_path = "${ERAS_FILE}"
if os.path.exists(eras_path):
    with open(eras_path, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {"total_eras": 0, "active_era": 0, "eras": []}

next_era = data.get("total_eras", 0) + 1
data["total_eras"] = next_era
data["active_era"] = next_era

new_entry = {
    "era": next_era,
    "slug": "${WEEK_SLUG}",
    "theme_name": """${THEME_NAME}""",
    "date_range": """${DATE_RANGE}""",
    "quote": """${CLOSING_QUOTE}""",
    "coding_model": "${CURRENT_CODING_MODEL}",
    "archived_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
}

# Avoid duplicate slugs
data["eras"] = [e for e in data.get("eras", []) if e.get("slug") != "${WEEK_SLUG}"]
data["eras"].append(new_entry)

with open(eras_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

# Ensure snapshot also has recap.json
snapshot_recap = os.path.join("${SNAPSHOT_DIR}", "recap.json")
with open(snapshot_recap, "w", encoding="utf-8") as f:
    json.dump(new_entry, f, indent=2)

print(next_era)
EOF
)

log_success "Historical ledger updated: Era ${ERA_RECORD} (${WEEK_SLUG}) recorded."

# ------------------------------------------------------------------------------
# 4. Cut Git Tag in CindyPawford-Online Repository
# ------------------------------------------------------------------------------
log_info "Phase 3: Cutting Git tag in CindyPawford-Online..."

TAG_NAME="archive/cindy-${WEEK_SLUG}"
if [ -d "${SITE_DIR}/.git" ]; then
  git -C "${SITE_DIR}" tag -f -a "${TAG_NAME}" -m "Release ${WEEK_SLUG}: ${THEME_NAME}"
  log_success "Git tag '${TAG_NAME}' created locally in ${SITE_DIR}."
  
  # Push tag to remote if git remote origin is configured
  if git -C "${SITE_DIR}" remote get-url origin >/dev/null 2>&1; then
    log_info "Pushing tag '${TAG_NAME}' to remote repository..."
    git -C "${SITE_DIR}" push origin "${TAG_NAME}" -f >/dev/null 2>&1 || log_warn "Remote push of tag skipped or requires authentication."
  fi
else
  log_warn "Git directory ${SITE_DIR}/.git not found; skipping git tag creation."
fi

# ------------------------------------------------------------------------------
# 5. Model Rotation (cindy-active-coding-model) & era-info.json Sanitization
# ------------------------------------------------------------------------------
log_info "Phase 4: Rotating active coding engine from model pool..."

NEW_MODEL=$(${PYTHON_BIN} - << EOF
import json, random, os

pool_path = "${MODEL_POOL_FILE}"
current_model = "${CURRENT_CODING_MODEL}"
models = ["qwen2.5:latest", "llama3.2:3b", "brainsos-core"]

if os.path.exists(pool_path):
    try:
        with open(pool_path, "r", encoding="utf-8") as f:
            pool = json.load(f)
        models = pool.get("coding_models", models)
    except Exception:
        pass

# Pick next model distinct from current if pool > 1
candidates = [m for m in models if m != current_model]
if not candidates:
    candidates = models
chosen = random.choice(candidates)
print(chosen)
EOF
)

log_info "Selected next autonomous coding engine: '${NEW_MODEL}'."

# Update LiteLLM config alias for cindy-active-coding-model
${PYTHON_BIN} - << EOF
import os, re

cfg_path = "${LITELLM_CONFIG}"
new_model = "${NEW_MODEL}"
backend_target = f"ollama_chat/{new_model}" if not new_model.startswith("ollama_chat/") else new_model

with open(cfg_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = r"(- model_name:\s*cindy-active-coding-model\s*\n\s*litellm_params:\s*\n\s*model:\s*)[^\n]+"
if re.search(pattern, content):
    new_content = re.sub(pattern, rf"\g<1>{backend_target}", content)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(new_content)
else:
    # Append if not found
    entry = f"""
  - model_name: cindy-active-coding-model
    litellm_params:
      model: {backend_target}
      api_base: http://127.0.0.1:11434
      max_parallel_requests: 1
      timeout: 300
      num_ctx: os.environ/INFERENCE_NUM_CTX
"""
    with open(cfg_path, "a", encoding="utf-8") as f:
        f.write(entry)
EOF

log_success "Updated LiteLLM routing alias 'cindy-active-coding-model' -> '${NEW_MODEL}'."

# ------------------------------------------------------------------------------
# 6. Wipe ONLY /app/html & Seed Clean Slate (Never touch /workspace or /memories)
# ------------------------------------------------------------------------------
log_info "Phase 5: Resetting /app/html to pristine clean-slate canvas..."

# Remove files in SITE_DIR except .git
find "${SITE_DIR}" -mindepth 1 -maxdepth 1 ! -name ".git" -exec rm -rf {} +

# Copy clean slate templates into site
if [ -d "${CLEAN_SLATE_DIR}" ]; then
  cp -r "${CLEAN_SLATE_DIR}/"* "${SITE_DIR}/"
else
  # Minimal fallback
  cat << 'EOF' > "${SITE_DIR}/index.html"
<!DOCTYPE html>
<html><head><title>Cindy Pawford Atelier</title></head><body><h1>Atelier Reset Complete</h1></body></html>
EOF
fi

# Write sanitized era-info.json (Rule 7: model engine name strictly hidden)
NEXT_ERA_NUM=$((ERA_RECORD + 1))
NEXT_WEEK_SLUG="$(date +%Y-w%U)"

cat << EOF > "${SITE_DIR}/era-info.json"
{
  "era": ${NEXT_ERA_NUM},
  "week": "${NEXT_WEEK_SLUG}"
}
EOF

# Ensure .archive-ready trigger is removed
rm -f "${TRIGGER_FILE}"

# Re-apply safe permissions to site
find "${SITE_DIR}" -type d -exec chmod 775 {} + 2>/dev/null || true
find "${SITE_DIR}" -type f -exec chmod 664 {} + 2>/dev/null || true

log_success "Clean slate seeded. Cindy Pawford primed for Era ${NEXT_ERA_NUM}."

# ------------------------------------------------------------------------------
# 7. Rebuild Static Digital Museum Portal
# ------------------------------------------------------------------------------
log_info "Phase 6: Rebuilding digital museum gallery wall..."
${PYTHON_BIN} "${REPO_ROOT}/scripts/apps/cindypawford/build-archive-portal.py"

log_info "================================================================="
log_success "  'Seal & Reset' Pipeline Completed Successfully for ${WEEK_SLUG}!  "
log_info "================================================================="
