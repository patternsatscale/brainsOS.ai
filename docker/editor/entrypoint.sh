#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Operator IDE Container Entrypoint Wrapper
# Synchronizes pre-installed extensions, sets default configs, and launches code-server
# ==============================================================================
set -eu

# 1. Sync pre-installed extensions into user extensions directory if missing
mkdir -p /home/coder/.local/share/code-server/extensions
if [ -d "/opt/code-server/extensions" ]; then
  cp -rn /opt/code-server/extensions/* /home/coder/.local/share/code-server/extensions/ 2>/dev/null || true
fi

# 2. Scaffolding default code-server configuration
# When running behind Caddy HTTP Basic Auth gate, auth defaults to 'none' to avoid redundant double-login.
CODE_SERVER_AUTH="${CODE_SERVER_AUTH:-none}"
mkdir -p /home/coder/.config/code-server
cat << EOF > /home/coder/.config/code-server/config.yaml
bind-addr: 0.0.0.0:8443
auth: ${CODE_SERVER_AUTH}
password: ${PASSWORD:-brainsos_operator_secret}
cert: false
disable-telemetry: true
disable-update-check: true
disable-workspace-trust: true
EOF

# 3. Scaffolding default VS Code User settings.json with explicit workspace trust & SSL security bypass
mkdir -p /home/coder/.local/share/code-server/User
SETTINGS_FILE="/home/coder/.local/share/code-server/User/settings.json"
if [ ! -f "${SETTINGS_FILE}" ]; then
  cat << 'EOF' > "${SETTINGS_FILE}"
{
  "security.workspace.trust.enabled": false,
  "security.workspace.trust.startupPrompt": "never",
  "security.workspace.trust.emptyWindow": true,
  "http.proxyStrictSSL": false,
  "telemetry.telemetryLevel": "off",
  "workbench.startupEditor": "none",
  "files.autoSave": "afterDelay",
  "terminal.integrated.defaultProfile.linux": "bash",
  "files.exclude": {
    "**/.git": false,
    "**/.svn": true,
    "**/.hg": true,
    "**/CVS": true,
    "**/.DS_Store": true,
    "**/Thumbs.db": true,
    "**/.vscode": false
  },
  "search.exclude": {
    "**/node_modules": true,
    "**/bower_components": true,
    "**/*.code-search": true,
    "**/data/litellm_db": true,
    "**/data/postgres": true,
    "**/data/langfuse_*": true,
    "**/data/langfuse_clickhouse": true,
    "**/data/langfuse_postgres": true,
    "**/data/telemetry": true,
    "**/data/control_plane/litellm_db": true
  },
  "files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/.cache/**": true,
    "**/data/litellm_db/**": true,
    "**/data/postgres/**": true,
    "**/data/langfuse_*/**": true,
    "**/data/langfuse_clickhouse/**": true,
    "**/data/langfuse_postgres/**": true,
    "**/data/control_plane/**": true,
    "**/data/control_plane/litellm_db/**": true,
    "**/data/workspace/**": true,
    "**/data/agent_workspaces/**": true,
    "**/data/comms/**": true,
    "**/data/telemetry/**": true,
    "**/.venv/**": true,
    "**/dist/**": true,
    "**/build/**": true
  }
}
EOF
else
  # Ensure existing settings have workspace trust disabled, SSL bypass, and file watcher exclusions
  python3 - << 'EOF' || true
import json, os
p = "/home/coder/.local/share/code-server/User/settings.json"
try:
    with open(p, "r", encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    d = {}
d["security.workspace.trust.enabled"] = False
d["security.workspace.trust.startupPrompt"] = "never"
d["security.workspace.trust.emptyWindow"] = True
d["http.proxyStrictSSL"] = False
d["files.watcherExclude"] = {
    "**/.git/objects/**": True,
    "**/.git/subtree-cache/**": True,
    "**/node_modules/**": True,
    "**/.cache/**": True,
    "**/data/litellm_db/**": True,
    "**/data/postgres/**": True,
    "**/data/langfuse_*/**": True,
    "**/data/langfuse_clickhouse/**": True,
    "**/data/langfuse_postgres/**": True,
    "**/data/control_plane/**": True,
    "**/data/control_plane/litellm_db/**": True,
    "**/data/workspace/**": True,
    "**/data/agent_workspaces/**": True,
    "**/data/comms/**": True,
    "**/data/telemetry/**": True,
    "**/.venv/**": True,
    "**/dist/**": True,
    "**/build/**": True
}
d["search.exclude"] = {
    "**/node_modules": True,
    "**/bower_components": True,
    "**/*.code-search": True,
    "**/data/litellm_db": True,
    "**/data/postgres": True,
    "**/data/langfuse_*": True,
    "**/data/langfuse_clickhouse": True,
    "**/data/langfuse_postgres": True,
    "**/data/telemetry": True,
    "**/data/control_plane/litellm_db": True
}
with open(p, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)
EOF
fi

# 4. Scaffolding Continue AI extension configuration (dynamically synced from fleet manifest)
mkdir -p /home/coder/.continue
OP_KEY="${OPENAI_API_KEY:-${OPERATOR_LITELLM_KEY:-sk-brainsos-operator-virtual-key}}"
API_KEY="${API_SERVER_KEY:-}"

SRC_CONTINUE_YAML="/workspace/brainsos/config/editor/continue_config.yaml"
SRC_CONTINUE_JSON="/workspace/brainsos/config/editor/continue_config.json"

if [ -f "${SRC_CONTINUE_YAML}" ]; then
  sed "s|\${OPERATOR_LITELLM_KEY}|${OP_KEY}|g; \
       s|\${HERMES_API_TERRASTELLA_KEY}|${HERMES_API_TERRASTELLA_KEY:-}|g; \
       s|\${HERMES_API_MARVIN_KEY}|${HERMES_API_MARVIN_KEY:-}|g; \
       s|\${HERMES_API_BAWTFORD_KEY}|${HERMES_API_BAWTFORD_KEY:-}|g; \
       s|\${API_SERVER_KEY}|${API_KEY}|g" "${SRC_CONTINUE_YAML}" > /home/coder/.continue/config.yaml
else
  cat << EOF > /home/coder/.continue/config.yaml
name: brainsOS Operator IDE
version: 1.0.0
schema: v1
models:
  - name: "brainsOS Core (LiteLLM)"
    provider: openai
    model: brainsos-core
    apiBase: http://litellm:4000/v1
    apiKey: "${OP_KEY}"
    roles:
      - chat
      - edit
      - apply
EOF
fi

if [ -f "${SRC_CONTINUE_JSON}" ]; then
  sed "s|\${OPERATOR_LITELLM_KEY}|${OP_KEY}|g; \
       s|\${HERMES_API_TERRASTELLA_KEY}|${HERMES_API_TERRASTELLA_KEY:-}|g; \
       s|\${HERMES_API_MARVIN_KEY}|${HERMES_API_MARVIN_KEY:-}|g; \
       s|\${HERMES_API_BAWTFORD_KEY}|${HERMES_API_BAWTFORD_KEY:-}|g; \
       s|\${API_SERVER_KEY}|${API_KEY}|g" "${SRC_CONTINUE_JSON}" > /home/coder/.continue/config.json
fi

# 5. Scaffolding Aider CLI configuration
if [ ! -f /home/coder/.aider.conf.yml ]; then
  cat << EOF > /home/coder/.aider.conf.yml
openai-api-base: http://litellm:4000/v1
openai-api-key: ${OPENAI_API_KEY:-sk-brainsos-operator-virtual-key}
model: openai/brainsos-core
EOF
fi

# 6. Export CA environment variables into user shell
CADDY_ROOT_CA="/etc/ssl/caddy/root.crt"
if [ -f "${CADDY_ROOT_CA}" ]; then
  grep -q "NODE_EXTRA_CA_CERTS" /home/coder/.bashrc 2>/dev/null || cat << EOF >> /home/coder/.bashrc
export NODE_EXTRA_CA_CERTS="${CADDY_ROOT_CA}"
export NODE_TLS_REJECT_UNAUTHORIZED=0
export SSL_CERT_FILE="${CADDY_ROOT_CA}"
export REQUESTS_CA_BUNDLE="${CADDY_ROOT_CA}"
export CURL_CA_BUNDLE="${CADDY_ROOT_CA}"
EOF
fi

# Launch upstream entrypoint with multi-root workspace
exec /usr/bin/entrypoint.sh --bind-addr 0.0.0.0:8443 --auth "${CODE_SERVER_AUTH}" --disable-telemetry --disable-workspace-trust /workspace/brainsos.code-workspace "$@"
