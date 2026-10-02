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

# Ensure brainsos.system-terminal extension is registered in extensions.json
python3 - << 'EOF' || true
import json, os
ext_json_path = "/home/coder/.local/share/code-server/extensions/extensions.json"
ext_dir = "/home/coder/.local/share/code-server/extensions/brainsos.system-terminal-1.0.0"
if os.path.isdir(ext_dir):
    try:
        data = []
        if os.path.exists(ext_json_path):
            with open(ext_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if not any(e.get("identifier", {}).get("id") == "brainsos.system-terminal" for e in data):
            data.append({
                "identifier": {"id": "brainsos.system-terminal"},
                "version": "1.0.0",
                "location": {
                    "$mid": 1,
                    "fsPath": ext_dir,
                    "path": ext_dir,
                    "scheme": "file"
                },
                "relativeLocation": "brainsos.system-terminal-1.0.0",
                "metadata": {
                    "isApplicationScoped": False,
                    "isMachineScoped": False,
                    "isBuiltin": False,
                    "installedTimestamp": 1790000000000,
                    "pinned": False,
                    "source": "custom",
                    "publisherDisplayName": "brainsOS",
                    "targetPlatform": "universal",
                    "updated": False,
                    "private": True
                }
            })
            with open(ext_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception as err:
        print(f"Warning: could not register extension in extensions.json: {err}")
EOF

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
  "workbench.colorTheme": "Dark Modern",
  "window.autoDetectColorScheme": false,
  "terminal.integrated.cwd": "/data",
  "terminal.integrated.defaultLocation": "editor",
  "terminal.integrated.defaultProfile.linux": "bash",
  "chat.commandCenter.enabled": true,
  "chat.defaultModel": "brainsos-core",
  "chat.byokUtilityModelDefault": "mainAgent",
  "chat.agentFilesLocations": {
    ".github/agents": true,
    ".claude/agents": true,
    ".agents/souls": true,
    "souls": true
  },
  "chat.useAgentSkills": true,
  "chat.agentSkillsLocations": {
    ".agents/skills": true,
    ".github/skills": true,
    ".claude/skills": true
  },
  "github.copilot.chat.customOAIModels": {
    "brainsos-core": {
      "name": "brainsOS Core (Default)",
      "url": "http://litellm:4000/v1",
      "maxInputTokens": 32768,
      "maxOutputTokens": 4096,
      "toolCalling": true,
      "vision": false
    },
    "qwen2.5:latest": {
      "name": "Qwen 2.5",
      "url": "http://litellm:4000/v1",
      "maxInputTokens": 32768,
      "maxOutputTokens": 4096,
      "toolCalling": true,
      "vision": false
    }
  },
  "security.workspace.trust.enabled": false,
  "security.workspace.trust.startupPrompt": "never",
  "security.workspace.trust.emptyWindow": true,
  "http.proxyStrictSSL": false,
  "telemetry.telemetryLevel": "off",
  "workbench.startupEditor": "none",
  "files.autoSave": "afterDelay",
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
  # Ensure existing settings have dark modern theme, terminal front & center, AI settings, and exclusions
  python3 - << 'EOF' || true
import json, os
p = "/home/coder/.local/share/code-server/User/settings.json"
try:
    with open(p, "r", encoding="utf-8") as f:
        d = json.load(f)
except Exception:
    d = {}
d["workbench.colorTheme"] = "Dark Modern"
d["window.autoDetectColorScheme"] = False
d["terminal.integrated.cwd"] = "/data"
d["terminal.integrated.defaultLocation"] = "editor"
d["terminal.integrated.defaultProfile.linux"] = "bash"
d["chat.commandCenter.enabled"] = True
d["chat.defaultModel"] = "brainsos-core"
d["chat.byokUtilityModelDefault"] = "mainAgent"
d["chat.agentFilesLocations"] = {
    ".github/agents": True,
    ".claude/agents": True,
    ".agents/souls": True,
    "souls": True
}
d["chat.useAgentSkills"] = True
d["chat.agentSkillsLocations"] = {
    ".agents/skills": True,
    ".github/skills": True,
    ".claude/skills": True
}
d["github.copilot.chat.customOAIModels"] = {
    "brainsos-core": {
        "name": "brainsOS Core (Default)",
        "url": "http://litellm:4000/v1",
        "maxInputTokens": 32768,
        "maxOutputTokens": 4096,
        "toolCalling": True,
        "vision": False
    },
    "qwen2.5:latest": {
        "name": "Qwen 2.5",
        "url": "http://litellm:4000/v1",
        "maxInputTokens": 32768,
        "maxOutputTokens": 4096,
        "toolCalling": True,
        "vision": False
    }
}
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

# 3b. Scaffolding VS Code built-in Language Models (Custom Endpoint to LiteLLM)
SRC_LM_JSON="/etc/brainsos/editor/chatLanguageModels.json"
TARGET_LM_JSON="/home/coder/.local/share/code-server/User/chatLanguageModels.json"
OP_KEY="${OPENAI_API_KEY:-${OPERATOR_LITELLM_KEY:-sk-brainsos-operator-virtual-key}}"
if [ -f "${SRC_LM_JSON}" ]; then
  sed "s|\${OPENAI_API_KEY}|${OP_KEY}|g" "${SRC_LM_JSON}" > "${TARGET_LM_JSON}"
fi

# 3c. Ensure /etc/brainsos/system.mk exists for the make wrapper
if [ ! -f /etc/brainsos/system.mk ] && [ -f /etc/brainsos/editor/system.mk ]; then
  mkdir -p /etc/brainsos
  cp /etc/brainsos/editor/system.mk /etc/brainsos/system.mk 2>/dev/null || true
fi

# 4. Scaffolding Aider CLI configuration
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

# Add brainsOS System Terminal greeting banner to user interactive shell
grep -q "brainsOS System Terminal" /home/coder/.bashrc 2>/dev/null || cat << 'EOF' >> /home/coder/.bashrc

if [ -t 1 ] && [ -z "${BRAINSOS_BANNER_SHOWN:-}" ]; then
  export BRAINSOS_BANNER_SHOWN=1
  echo -e "\033[1;36m========================================================================\033[0m"
  echo -e "\033[1m  brainsOS System Terminal\033[0m  \033[2m(Workspace: /data)\033[0m"
  echo -e "  Type \033[1;32mmake urls\033[0m     to view all service endpoints & credentials."
  echo -e "  Type \033[1;32mmake status\033[0m   to inspect platform service health."
  echo -e "  Type \033[1;32mmake models\033[0m   to list registered AI models."
  echo -e "  Type \033[1;32mmake chat\033[0m     to start an interactive agent session."
  echo -e "\033[1;36m========================================================================\033[0m\n"
fi
EOF

# 7. Complete initialization and launch code-server

# 7. Configure default folder view in coder.json to open /data as single workspace
CODER_JSON="/home/coder/.local/share/code-server/coder.json"
cat << 'EOF' > "${CODER_JSON}"
{
  "query": {
    "folder": "/data"
  }
}
EOF

# Clear stale cached workspace configurations to ensure clean single-folder view
rm -rf /home/coder/.local/share/code-server/User/caches/CachedConfigurations/workspaces 2>/dev/null || true
rm -rf /home/coder/.local/share/code-server/User/workspaceStorage 2>/dev/null || true

# Launch upstream entrypoint opening /data as the single workspace root
TARGET_DIR="${1:-/data}"
if [ $# -gt 0 ] && [ -n "${1:-}" ] && [[ "${1}" != -* ]]; then
  TARGET_DIR="$1"
  shift
fi

exec /usr/bin/entrypoint.sh --bind-addr 0.0.0.0:8443 --auth "${CODE_SERVER_AUTH}" --disable-telemetry --disable-workspace-trust "${TARGET_DIR}" "$@"
