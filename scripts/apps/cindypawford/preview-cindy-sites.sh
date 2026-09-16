#!/usr/bin/env bash
# ==============================================================================
# scripts/apps/cindypawford/preview-cindy-sites.sh
# Start local preview server for all Cindy Pawford web surfaces
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8088}"

exec python3 "${SCRIPT_DIR}/preview-server.py" "${PORT}"
