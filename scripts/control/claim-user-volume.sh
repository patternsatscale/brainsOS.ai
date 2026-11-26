#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
exec "${REPO_ROOT}/packages/brainsOS-appliance/scripts/claim-user-volume.sh" "$@"
