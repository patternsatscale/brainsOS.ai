#!/usr/bin/env bash
# ==============================================================================
# verify-no-private-refs.sh: Prevent Private Fleet Leakage in brainsOS.ai
# ==============================================================================
# Asserts that the open-source platform core (staged commits, packages, config,
# and GitHub issues/PRs) never leaks the private fleet repository name
# ('project_mJ' / 'project-mJ') or private user paths, enforcing Rule 11 and Rule 14.
#
# Flags:
#   --staged-only   Fast audit of staged files only (for git pre-commit hooks)
#   --ticket <NUM>  Audit a specific GitHub issue or PR number
#   --all-issues    Audit all issues and PRs across repository history
#   --scrub         Automatically sanitize prohibited terms in matching issues/PRs
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

PROHIBITED_TERMS=(
  "project_mJ"
  "project-mJ"
)

STAGED_ONLY=false
AUDIT_ALL_ISSUES=false
SPECIFIC_TICKET=""
AUTO_SCRUB=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --staged-only)
      STAGED_ONLY=true
      shift
      ;;
    --all-issues)
      AUDIT_ALL_ISSUES=true
      shift
      ;;
    --ticket)
      SPECIFIC_TICKET="$2"
      shift 2
      ;;
    --scrub)
      AUTO_SCRUB=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--staged-only] [--ticket <NUM>] [--all-issues] [--scrub]"
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      exit 1
      ;;
  esac
done

ERRORS_FOUND=0

echo -e "\n🛡️  ${BOLD}brainsOS Private Fleet Leakage Audit (Rule 11 & Rule 14)${NC}\n"

# ==============================================================================
# 1. Audit Staged Files in Git Index
# ==============================================================================
log_info "Auditing staged changes in git index..."
STAGED_FILES=$(git -C "${REPO_ROOT}" diff --cached --name-only -- ':!scripts/verify/verify-no-private-refs.sh' 2>/dev/null || true)
if [ -n "${STAGED_FILES}" ]; then
  for term in "${PROHIBITED_TERMS[@]}"; do
    MATCHES=$(git -C "${REPO_ROOT}" diff --cached -- ':!scripts/verify/verify-no-private-refs.sh' | grep "^\+[^+]" | grep "${term}" || true)
    if [ -n "${MATCHES}" ]; then
      log_error "Prohibited private fleet reference '${term}' detected in staged git changes!"
      ERRORS_FOUND=$((ERRORS_FOUND + 1))
    fi
  done
else
  log_info "No staged changes to audit."
fi

if [ "${STAGED_ONLY}" = true ]; then
  if [ "${ERRORS_FOUND}" -eq 0 ]; then
    log_success "Staged changes clean. Pre-commit check passed."
    exit 0
  else
    log_error "Staged changes contain prohibited private fleet references! Commit blocked."
    exit 1
  fi
fi

# ==============================================================================
# 2. Audit Core Codebase & Configuration
# ==============================================================================
log_info "Auditing core packages, config, scripts, and root architecture specs..."
CORE_TARGETS=(
  "${REPO_ROOT}/packages"
  "${REPO_ROOT}/config"
  "${REPO_ROOT}/scripts"
  "${REPO_ROOT}/PLAN.md"
  "${REPO_ROOT}/PLANNING.md"
  "${REPO_ROOT}/README.md"
)

for target in "${CORE_TARGETS[@]}"; do
  if [ -e "${target}" ]; then
    for term in "${PROHIBITED_TERMS[@]}"; do
      # Search for prohibited term excluding .git, egg-info, pycache, and the audit script itself
      MATCHES=$(grep -rn --exclude-dir=".git" --exclude-dir="*.egg-info" --exclude-dir="__pycache__" --exclude="$(basename "$0")" "${term}" "${target}" 2>/dev/null || true)
      if [ -n "${MATCHES}" ]; then
        log_error "Prohibited reference '${term}' found in ${target}:\n${MATCHES}"
        ERRORS_FOUND=$((ERRORS_FOUND + 1))
      fi
    done
  fi
done

# ==============================================================================
# 3. Audit GitHub Issues & Pull Requests
# ==============================================================================
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  AUDIT_ALL_ISSUES="${AUDIT_ALL_ISSUES}" \
  SPECIFIC_TICKET="${SPECIFIC_TICKET}" \
  AUTO_SCRUB="${AUTO_SCRUB}" \
  python3 - <<'EOF'
import json
import os
import subprocess
import sys

repo = "patternsatscale/brainsOS.ai"
audit_all = os.environ.get("AUDIT_ALL_ISSUES", "false").lower() == "true"
specific_ticket = os.environ.get("SPECIFIC_TICKET", "")
auto_scrub = os.environ.get("AUTO_SCRUB", "false").lower() == "true"
prohibited = ["project_mJ", "project-mJ"]

def log_info(msg): print(f"\033[0;34m[INFO]\033[0m {msg}")
def log_success(msg): print(f"\033[0;32m[SUCCESS]\033[0m {msg}")
def log_warn(msg): print(f"\033[1;33m[WARN]\033[0m {msg}")
def log_error(msg): print(f"\033[0;31m[ERROR]\033[0m {msg}")

tickets_to_check = []

if specific_ticket:
    tickets_to_check.append(("ticket", int(specific_ticket)))
else:
    log_info("Searching GitHub issues and pull requests for prohibited terms...")
    for term in prohibited:
        cmd = ["gh", "search", "issues", term, "--repo", repo, "--limit", "100", "--include-prs", "--json", "number,title,state,isPullRequest"]
        if not audit_all:
            cmd.extend(["--state", "open"])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            try:
                items = json.loads(res.stdout)
                for it in items:
                    kind = "pr" if it.get("isPullRequest") else "issue"
                    tickets_to_check.append((kind, it["number"]))
            except Exception as e:
                log_warn(f"Failed to parse gh search output: {e}")

# Deduplicate
tickets_to_check = list(dict.fromkeys(tickets_to_check))

violations = 0

for kind, num in tickets_to_check:
    # Try viewing as issue first, then pr
    view_cmd = ["gh", "issue", "view", str(num), "--json", "number,title,body"]
    res = subprocess.run(view_cmd, capture_output=True, text=True)
    if res.returncode == 0:
        kind = "issue"
    else:
        view_cmd = ["gh", "pr", "view", str(num), "--json", "number,title,body"]
        res = subprocess.run(view_cmd, capture_output=True, text=True)
        if res.returncode == 0:
            kind = "pr"
        else:
            continue

    data = json.loads(res.stdout)
    body = data.get("body", "")
    title = data.get("title", "")

    found_in_body = any(term in body for term in prohibited)
    found_in_title = any(term in title for term in prohibited)

    if found_in_body or found_in_title:
        violations += 1
        log_error(f"Prohibited private fleet reference detected in {kind.upper()} #{num}: '{title}'")
        if auto_scrub:
            log_info(f"Auto-scrubbing {kind.upper()} #{num}...")
            new_body = body
            # Scrub specific user paths first
            new_body = new_body.replace("/Users/pats/Development/project_mJ", "<path/to/data_dir>")
            new_body = new_body.replace("Development/project_mJ", "Development/$BRAINSOS_DATA_DIR")
            for term in prohibited:
                new_body = new_body.replace(f"patternsatscale/{term}", "patternsatscale/private-fleet")
                new_body = new_body.replace(f"`{term}`", "`$BRAINSOS_DATA_DIR`")
                new_body = new_body.replace(term, "$BRAINSOS_DATA_DIR")

            new_title = title
            for term in prohibited:
                new_title = new_title.replace(term, "$BRAINSOS_DATA_DIR")

            edit_cmd = ["gh", kind, "edit", str(num), "--body", new_body]
            if new_title != title:
                edit_cmd.extend(["--title", new_title])
            edit_res = subprocess.run(edit_cmd, capture_output=True, text=True)
            if edit_res.returncode == 0:
                log_success(f"Successfully sanitized {kind.upper()} #{num}!")
                violations -= 1
            else:
                log_error(f"Failed to edit {kind.upper()} #{num}: {edit_res.stderr}")

if violations > 0:
    sys.exit(violations)
EOF
  GH_EXIT=$?
  ERRORS_FOUND=$((ERRORS_FOUND + GH_EXIT))
else
  log_warn "GitHub CLI ('gh') not available or not logged in; skipping remote issue/PR audit."
fi

echo ""
if [ "${ERRORS_FOUND}" -eq 0 ]; then
  log_success "Zero private fleet references found! Repository and issue tracker are clean."
  exit 0
else
  log_error "${ERRORS_FOUND} private fleet leakage violation(s) detected! Remediate before committing or opening PRs."
  exit 1
fi
