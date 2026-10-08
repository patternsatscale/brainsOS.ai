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
  # Always ensure brainsOS custom system terminal is updated to the latest build
  cp -r /opt/code-server/extensions/brainsos.system-terminal-1.0.0 /home/coder/.local/share/code-server/extensions/ 2>/dev/null || true
fi

# Ensure Foam explorer subviews are hidden by default to preserve a clean, focused explorer view
python3 - << 'EOF' || true
import json, glob
for p in glob.glob('/home/coder/.local/share/code-server/extensions/foam.foam-vscode-*/package.json'):
    try:
        with open(p, 'r') as f:
            d = json.load(f)
        for v in d.get('contributes', {}).get('views', {}).get('explorer', []):
            v['when'] = 'false'
        with open(p, 'w') as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass
EOF

# Patch LiteLLM Connector extension in user and opt extensions directories:
# In headless code-server, VS Code's SecretStorage cannot resolve secrets via GUI prompt.
# Removing "secret": true ensures VS Code passes apiKey from chatLanguageModels.json directly.
python3 - << 'EOF' || true
import glob
for p in glob.glob('/home/coder/.local/share/code-server/extensions/gethnet.litellm-connector-copilot-*/package.json') + \
         glob.glob('/opt/code-server/extensions/gethnet.litellm-connector-copilot-*/package.json'):
    try:
        with open(p, 'r') as f:
            c = f.read()
        if '"secret": true' in c:
            c = c.replace('"secret": true,', '').replace('"secret": true', '')
            with open(p, 'w') as f:
                f.write(c)
    except Exception:
        pass
EOF

# Purge deprecated Continue extension artifacts if present to ensure clean environment
rm -rf /home/coder/.local/share/code-server/extensions/*continue* /home/coder/.continue /opt/code-server/extensions/*continue* 2>/dev/null || true

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

# 3. Dynamic Configuration of VS Code User settings.json and chatLanguageModels.json
mkdir -p /home/coder/.local/share/code-server/User
python3 - << 'PYEOF' || true
import json, os

settings_path = "/home/coder/.local/share/code-server/User/settings.json"
lm_json_path = "/home/coder/.local/share/code-server/User/chatLanguageModels.json"

try:
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {}
except Exception:
    d = {}

op_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPERATOR_LITELLM_KEY") or "sk-brainsos-operator-virtual-key"

# Core workbench and theme
d["workbench.colorTheme"] = "Dark Modern"
d["window.autoDetectColorScheme"] = False
d["terminal.integrated.cwd"] = "/data"
d["terminal.integrated.defaultLocation"] = "editor"
d["terminal.integrated.defaultProfile.linux"] = "bash"

# AI & Copilot settings (LiteLLM handles all models dynamically via virtual key)
d["chat.commandCenter.enabled"] = True
d["chat.defaultModel"] = "brainsos-core"
d["chat.byokUtilityModelDefault"] = "mainAgent"
d["chat.promptFiles"] = True
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
# Remove any legacy hardcoded model dictionaries
d.pop("github.copilot.chat.customOAIModels", None)

d["litellm-connector.discoveryTimeoutMs"] = 5000
d["litellm-connector.enableModelOverrides"] = False
d["litellm-connector.displayPricingInPicker"] = False
d["litellm-connector.modelCapabilitiesOverrides"] = {
    "qwen3.8:latest": "toolCalling",
    "brainsos-core": "toolCalling",
    "qwen2.5:latest": "toolCalling"
}

# Security & telemetry
d["security.workspace.trust.enabled"] = False
d["security.workspace.trust.startupPrompt"] = "never"
d["security.workspace.trust.emptyWindow"] = True
d["extensions.autoUpdate"] = False
d["extensions.autoCheckUpdates"] = False
d["http.proxyStrictSSL"] = False
d["telemetry.telemetryLevel"] = "off"
d["workbench.startupEditor"] = "none"
d["workbench.editor.restoreViewState"] = True

# Pruned Explorer View & Outline / Timeline exclusions
d["explorer.autoReveal"] = True
d["explorer.openEditors.visible"] = 0
d["outline.collapseItems"] = "alwaysCollapse"
d["outline.showProblems"] = False
d["timeline.excludeSources"] = ["*"]
d["npm.exclude"] = ["**"]
d["foam.orphans.exclude"] = ["**/*"]
d["foam.placeholders.exclude"] = ["**/*"]
d["workbench.tree.renderIndentGuides"] = "always"
d["workbench.tree.indent"] = 14
d["files.autoSave"] = "afterDelay"
d["files.exclude"] = {
    "**/.git": False,
    "**/.svn": True,
    "**/.hg": True,
    "**/CVS": True,
    "**/.DS_Store": True,
    "**/Thumbs.db": True,
    "**/.vscode": False
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

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)

# 3b. Dynamic chatLanguageModels.json with LiteLLM Connector (Zero hardcoded models)
chat_lm = [
    {
        "name": "LiteLLM",
        "vendor": "litellm-connector",
        "baseUrl": "http://litellm:4000",
        "apiKey": op_key
    }
]
with open(lm_json_path, "w", encoding="utf-8") as f:
    json.dump(chat_lm, f, indent=2)
PYEOF

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

# Clear stale cached workspace configurations while preserving workspaceStorage for explorer view state
rm -rf /home/coder/.local/share/code-server/User/caches/CachedConfigurations/workspaces 2>/dev/null || true

# Launch upstream entrypoint opening /data as the single workspace root
TARGET_DIR="${1:-/data}"
if [ $# -gt 0 ] && [ -n "${1:-}" ] && [[ "${1}" != -* ]]; then
  TARGET_DIR="$1"
  shift
fi

exec /usr/bin/entrypoint.sh --bind-addr 0.0.0.0:8443 --auth "${CODE_SERVER_AUTH}" --disable-telemetry --disable-workspace-trust "${TARGET_DIR}" "$@"
