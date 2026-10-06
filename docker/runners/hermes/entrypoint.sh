#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Warm Hermes Runner Container Entrypoint
# Concurrently launches:
# 1. Hermes Runner Universal IPC API (port 8642)
# 2. Hermes WebUI & Configuration Server (port 8787)
# ==============================================================================

set -euo pipefail

echo "[INFO] Initializing Hermes configuration directory..."
mkdir -p /root/.hermes

if [ -f "/config/hermes/config.yaml" ] && [ ! -f "/root/.hermes/config.yaml" ]; then
  cp -r /config/hermes/* /root/.hermes/ 2>/dev/null || true
fi

echo "[INFO] Starting Hermes WebUI on port 8787..."
python3 -m uvicorn webui:app --app-dir /app --host 0.0.0.0 --port 8787 &
WEBUI_PID=$!

echo "[INFO] Starting Hermes Runner IPC on port 8642..."
python3 -m uvicorn server:app --app-dir /app --host 0.0.0.0 --port 8642 &
RUNNER_PID=$!

trap "kill -TERM ${WEBUI_PID} ${RUNNER_PID} 2>/dev/null || true; exit 0" SIGINT SIGTERM

wait -n ${RUNNER_PID} ${WEBUI_PID}
