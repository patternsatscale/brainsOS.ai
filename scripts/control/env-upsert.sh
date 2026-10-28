#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Idempotent .env Key Upsert Helper
# Tickets #322 / #323
#
# Sets KEY=VALUE pairs in an env file without disturbing comments or ordering:
#   - the first occurrence of KEY (assignment or commented template line
#     "# KEY=...") is replaced in place;
#   - later duplicate assignments of KEY are dropped;
#   - keys not present are appended under a labelled section.
# The file is rewritten atomically with 0600 permissions.
#
# Usage:
#   scripts/control/env-upsert.sh [--file PATH] [--section LABEL] KEY=VALUE [KEY=VALUE ...]
#   scripts/control/env-upsert.sh [--file PATH] --from-file OVERRIDES_FILE
#   scripts/control/env-upsert.sh [--file PATH] --unset KEY [--unset KEY ...]
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

ENV_FILE="${REPO_ROOT}/.env"
SECTION="Overrides (written by scripts/control/env-upsert.sh)"
FROM_FILE=""
PAIRS=()
UNSET_KEYS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --file)      ENV_FILE="${2:?--file requires a path}"; shift 2 ;;
    --section)   SECTION="${2:?--section requires a label}"; shift 2 ;;
    --from-file) FROM_FILE="${2:?--from-file requires a path}"; shift 2 ;;
    --unset)     UNSET_KEYS+=("${2:?--unset requires a key}"); shift 2 ;;
    -h|--help)
      sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *=*)         PAIRS+=("$1"); shift ;;
    *)
      echo "[ERROR] Unexpected argument: $1 (expected KEY=VALUE)" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "${ENV_FILE}" ]; then
  echo "[ERROR] Env file not found: ${ENV_FILE}" >&2
  exit 1
fi

PAIRS_TMP="$(mktemp)"
trap 'rm -f "${PAIRS_TMP}"' EXIT
if [ -n "${FROM_FILE}" ]; then
  cat "${FROM_FILE}" > "${PAIRS_TMP}"
fi
if [ "${#PAIRS[@]}" -gt 0 ]; then
  printf '%s\n' "${PAIRS[@]}" >> "${PAIRS_TMP}"
fi

python3 - "${ENV_FILE}" "${PAIRS_TMP}" "${SECTION}" "${UNSET_KEYS[@]+"${UNSET_KEYS[@]}"}" <<'PYEOF'
import os
import re
import sys
import tempfile

env_path, pairs_path, section = sys.argv[1], sys.argv[2], sys.argv[3]
unset_keys = set(sys.argv[4:])
key_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

overrides = {}
with open(pairs_path, encoding="utf-8") as fh:
    for raw in fh:
        raw = raw.rstrip("\n")
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key_re.match(key):
            sys.exit(f"[ERROR] Invalid env key: {key!r}")
        if "\n" in value:
            sys.exit(f"[ERROR] Newline in value for {key}")
        overrides[key] = value

lines, seen = [], set()
with open(env_path, encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        is_comment = line.startswith("#")
        body = line[1:].lstrip() if is_comment else line
        key = body.split("=", 1)[0].strip() if "=" in body else None
        if key and key_re.match(key):
            if not is_comment and key in unset_keys:
                continue
            if key in overrides:
                if key not in seen:
                    lines.append(f"{key}={overrides[key]}")
                    seen.add(key)
                    continue
                if not is_comment:
                    continue
        lines.append(line)

missing = [k for k in overrides if k not in seen]
if missing:
    lines += ["", "# " + "=" * 78, f"# {section}", "# " + "=" * 78]
    lines += [f"{k}={overrides[k]}" for k in missing]

directory = os.path.dirname(os.path.abspath(env_path))
fd, tmp_path = tempfile.mkstemp(prefix=".env.upsert.", dir=directory)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
os.chmod(tmp_path, 0o600)
os.replace(tmp_path, env_path)
PYEOF
