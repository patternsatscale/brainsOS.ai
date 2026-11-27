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

PAIRS_TMP="$(umask 077 && mktemp)"
trap 'rm -f "${PAIRS_TMP}"' EXIT
if [ "${#PAIRS[@]}" -gt 0 ]; then
  printf '%s\0' "${PAIRS[@]}" > "${PAIRS_TMP}"
fi

python3 - "${ENV_FILE}" "${PAIRS_TMP}" "${SECTION}" "${FROM_FILE}" "${UNSET_KEYS[@]+"${UNSET_KEYS[@]}"}" <<'PYEOF'
import os
import re
import sys
import tempfile

env_path, pairs_path, section, from_file_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
unset_keys = set(sys.argv[5:])
key_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:@,+=%-]*$")

for uk in unset_keys:
    if not key_re.fullmatch(uk):
        sys.exit(f"[ERROR] Invalid unset env key: {uk!r}")

def render(k: str, val: str) -> str:
    # Strip matching outer quotes so double-quoted $(...) / backticks can never survive
    # into a bash-sourced .env file (#384).
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    if "'" in val:
        sys.exit(f"[ERROR] Value for {k} contains a single quote; refusing to write an unsafe .env line")
    if SAFE_VALUE_RE.fullmatch(val):
        return f"{k}={val}"
    return f"{k}='{val}'"

overrides = {}

def parse_entry(raw: str) -> None:
    if not raw or "=" not in raw:
        if any(ch in raw for ch in ("\n", "\r", "\x00")):
            sys.exit("[ERROR] Control character in env pair")
        return
    raw_key, value = raw.split("=", 1)
    if any(ch in raw_key for ch in ("\n", "\r", "\x00")):
        sys.exit(f"[ERROR] Control character in env key: {raw_key!r}")
    key = raw_key.strip()
    if key.startswith("#"):
        if any(ch in value for ch in ("\n", "\r", "\x00")):
            sys.exit(f"[ERROR] Control character in env pair for {key!r}")
        return
    if not key_re.fullmatch(key):
        sys.exit(f"[ERROR] Invalid env key: {key!r}")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        sys.exit(f"[ERROR] Control character in value for {key}")
    overrides[key] = value

if from_file_path:
    with open(from_file_path, "r", encoding="utf-8", newline="\n") as fh:
        for raw in fh:
            parse_entry(raw.rstrip("\n"))

with open(pairs_path, "r", encoding="utf-8", newline="") as fh:
    pairs_blob = fh.read()
for raw in pairs_blob.split("\0"):
    if not raw:
        continue
    parse_entry(raw)

real_env_path = os.path.realpath(env_path)
lines, seen = [], set()
with open(real_env_path, encoding="utf-8") as fh:
    for raw in fh:
        line = raw.rstrip("\n")
        is_comment = line.startswith("#")
        body = line[1:].lstrip() if is_comment else line
        key = body.split("=", 1)[0].strip() if "=" in body else None
        if key and key_re.fullmatch(key):
            if not is_comment and key in unset_keys:
                continue
            if key in overrides:
                if key not in seen:
                    lines.append(render(key, overrides[key]))
                    seen.add(key)
                    continue
                if not is_comment:
                    continue
        lines.append(line)

missing = [k for k in overrides if k not in seen]
if missing:
    lines += ["", "# " + "=" * 78, f"# {section}", "# " + "=" * 78]
    lines += [render(k, overrides[k]) for k in missing]

directory = os.path.dirname(real_env_path)
os.makedirs(directory, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(prefix=".env.upsert.", dir=directory)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
os.chmod(tmp_path, 0o600)
os.replace(tmp_path, real_env_path)
PYEOF
