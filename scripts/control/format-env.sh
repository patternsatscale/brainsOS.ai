#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Environment File Organizer & Formatter (format-env.sh)
#
# Formats and organizes .env to mirror the canonical structure, section
# headings, and comments of .env.example while preserving all secret values,
# creating a safety backup, and appending any unmapped variables safely at the end.
# ==============================================================================

set -euo pipefail

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

ENV_FILE="${REPO_ROOT}/.env"
EXAMPLE_FILE="${REPO_ROOT}/.env.example"

# Terminal formatting
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

if [ ! -f "${ENV_FILE}" ]; then
  log_error ".env file not found at ${ENV_FILE}."
  exit 1
fi

if [ ! -f "${EXAMPLE_FILE}" ]; then
  log_error ".env.example template not found at ${EXAMPLE_FILE}."
  exit 1
fi

# Create timestamped safety backup
BACKUP_FILE="${ENV_FILE}.bak-$(date +%Y%m%d%H%M%S)"
cp -p "${ENV_FILE}" "${BACKUP_FILE}"
cp -p "${ENV_FILE}" "${ENV_FILE}.bak"
log_info "Created backup of current .env at ${BACKUP_FILE}"

# Format .env using python3
python3 - << EOF
import os
import sys

env_file = "${ENV_FILE}"
example_file = "${EXAMPLE_FILE}"
temp_file = "${ENV_FILE}.tmp"

current_vars = {}
with open(env_file, "r", encoding="utf-8") as f:
    for line in f:
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            current_vars[k.strip()] = v.rstrip("\r\n")

formatted_lines = []
handled_keys = set()

with open(example_file, "r", encoding="utf-8") as f:
    for line in f:
        line_rstrip = line.rstrip("\r\n")
        line_s = line_rstrip.strip()
        if not line_s or line_s.startswith("#"):
            formatted_lines.append(line_rstrip)
            continue
        if "=" in line_s:
            k, default_v = line_rstrip.split("=", 1)
            k = k.strip()
            handled_keys.add(k)
            if k in current_vars:
                formatted_lines.append(f"{k}={current_vars[k]}")
            else:
                formatted_lines.append(f"{k}={default_v}")
        else:
            formatted_lines.append(line_rstrip)

unmapped_keys = [k for k in current_vars if k not in handled_keys]
if unmapped_keys:
    formatted_lines.append("")
    formatted_lines.append("# ==============================================================================")
    formatted_lines.append("# Custom & Unmapped Overrides")
    formatted_lines.append("# ==============================================================================")
    for k in sorted(unmapped_keys):
        formatted_lines.append(f"{k}={current_vars[k]}")

formatted_content = "\n".join(formatted_lines) + "\n"

with open(temp_file, "w", encoding="utf-8") as f:
    f.write(formatted_content)

os.replace(temp_file, env_file)
EOF

chmod 600 "${ENV_FILE}"
log_success "Successfully organized .env to match .env.example architecture."
