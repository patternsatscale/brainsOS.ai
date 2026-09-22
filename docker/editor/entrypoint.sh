#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Operator IDE Container Entrypoint Wrapper
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
password: ${PASSWORD:-titan_operator_secret}
cert: false
EOF

# 3. Scaffolding default VS Code User settings.json
mkdir -p /home/coder/.local/share/code-server/User
if [ ! -f /home/coder/.local/share/code-server/User/settings.json ]; then
  cat << 'EOF' > /home/coder/.local/share/code-server/User/settings.json
{
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
    "**/data/postgres": true
  }
}
EOF
fi

# 4. Scaffolding Continue AI extension configuration
mkdir -p /home/coder/.continue
cat << EOF > /home/coder/.continue/config.yaml
name: Titan Operator IDE
version: 1.0.0
schema: v1
models:
  - name: "Titan Core (LiteLLM)"
    provider: openai
    model: titan-core
    apiBase: http://litellm:4000/v1
    apiKey: "${OPENAI_API_KEY:-sk-titan-operator-virtual-key}"
    roles:
      - chat
      - edit
      - apply

  - name: "Cindy Pawford (Agent API)"
    provider: openai
    model: cindy-pawford
    apiBase: http://api.cindypawford.com/v1
    apiKey: "${API_SERVER_KEY:-}"
    roles:
      - chat

  - name: "Terrastella (Agent API)"
    provider: openai
    model: terrastella
    apiBase: http://api.primary.titan.local/v1
    apiKey: "${API_SERVER_KEY:-}"
    roles:
      - chat

  - name: "Football Dan (Agent API)"
    provider: openai
    model: football-dan
    apiBase: http://api.football-dan.titan.local/v1
    apiKey: "${API_SERVER_KEY:-}"
    roles:
      - chat
EOF

# 5. Scaffolding Aider CLI configuration
if [ ! -f /home/coder/.aider.conf.yml ]; then
  cat << EOF > /home/coder/.aider.conf.yml
openai-api-base: http://litellm:4000/v1
openai-api-key: ${OPENAI_API_KEY:-sk-titan-operator-virtual-key}
model: openai/titan-core
EOF
fi

# Launch upstream entrypoint with multi-root workspace
exec /usr/bin/entrypoint.sh --bind-addr 0.0.0.0:8443 --auth "${CODE_SERVER_AUTH}" /workspace/titan.code-workspace "$@"
