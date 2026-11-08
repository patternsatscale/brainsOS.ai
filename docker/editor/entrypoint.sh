#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Operator IDE Container Entrypoint Wrapper
# Synchronizes pre-installed extensions, sets default configs, and launches code-server
# ==============================================================================
set -eu

# 1. Sync pre-installed extensions into user extensions directory
mkdir -p /home/coder/.local/share/code-server/extensions
if [ -d "/opt/code-server/extensions" ]; then
  # Remove stale older versions of bundled extensions before copying from /opt/code-server/extensions
  for opt_ext in /opt/code-server/extensions/*; do
    [ -d "${opt_ext}" ] || continue
    ext_base="$(basename "${opt_ext}")"
    ext_prefix="$(echo "${ext_base}" | sed -E 's/-[0-9]+\.[0-9]+\.[0-9]+.*$//')"
    for usr_ext in /home/coder/.local/share/code-server/extensions/${ext_prefix}-*; do
      [ -d "${usr_ext}" ] || continue
      if [ "$(basename "${usr_ext}")" != "${ext_base}" ]; then
        rm -rf "${usr_ext}" 2>/dev/null || true
      fi
    done
  done
  cp -rn /opt/code-server/extensions/* /home/coder/.local/share/code-server/extensions/ 2>/dev/null || true
  if [ -f "/opt/code-server/extensions/extensions.json" ]; then
    cp -f /opt/code-server/extensions/extensions.json /home/coder/.local/share/code-server/extensions/extensions.json 2>/dev/null || true
  fi
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
import glob, json
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

for cp in glob.glob('/usr/lib/code-server/lib/vscode/extensions/copilot/package.json') + \
          glob.glob('/home/coder/.local/share/code-server/extensions/github.copilot*/package.json') + \
          glob.glob('/opt/code-server/extensions/github.copilot*/package.json'):
    try:
        with open(cp, 'r') as f:
            cd = json.load(f)
        contrib = cd.get('contributes', {})
        if 'chatViewsWelcome' in contrib or 'chatSessions' in contrib:
            contrib['chatViewsWelcome'] = []
            contrib['chatSessions'] = []
            with open(cp, 'w') as f:
                json.dump(cd, f, indent=2)
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
cat << 'PYEOF' > /tmp/brainsos_sync_byok.py
import json
import os
import sqlite3
import sys
import time
import urllib.request

settings_path = "/home/coder/.local/share/code-server/User/settings.json"
lm_json_path = "/home/coder/.local/share/code-server/User/chatLanguageModels.json"
vscdb_path = "/home/coder/.local/share/code-server/User/globalStorage/state.vscdb"
ws_settings_path = "/data/.vscode/settings.json"
aider_path = "/home/coder/.aider.conf.yml"

timeout_sec = 15
is_background = "--background" in sys.argv
for i, arg in enumerate(sys.argv):
    if arg == "--timeout" and i + 1 < len(sys.argv):
        try:
            timeout_sec = int(sys.argv[i + 1])
        except Exception:
            pass

def wait_for_litellm(wait_sec=15):
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        try:
            req = urllib.request.Request("http://litellm:4000/health/liveness")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False

def key_returns_models(k, require_nonempty=False):
    if not k:
        return False
    for endpoint in ("http://litellm:4000/v1/models", "http://litellm:4000/model/info"):
        try:
            req = urllib.request.Request(
                endpoint,
                headers={"Authorization": f"Bearer {k}"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    if not require_nonempty:
                        return True
                    data_list = body.get("data") if isinstance(body, dict) else None
                    if isinstance(data_list, list) and len(data_list) > 0:
                        return True
        except Exception:
            pass
    return False

def provision_operator_key(op_k, master_k):
    if not master_k:
        return op_k
    try:
        for del_payload in (
            {"keys": [op_k]},
            {"key_aliases": ["brainsOs.console", "brainsOS.console", "brainsos-operator"]},
        ):
            req_del = urllib.request.Request(
                "http://litellm:4000/key/delete",
                data=json.dumps(del_payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {master_k}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                urllib.request.urlopen(req_del, timeout=3).read()
            except Exception:
                pass

        gen_payload = {
            "key": op_k,
            "key_alias": "brainsOs.console",
            "user_id": "admin",
            "max_budget": 100.0,
            "models": [],
        }
        req_gen = urllib.request.Request(
            "http://litellm:4000/key/generate",
            data=json.dumps(gen_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {master_k}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req_gen, timeout=4) as resp:
            gen_data = json.loads(resp.read().decode("utf-8"))
            if gen_data.get("key"):
                return str(gen_data["key"])
    except Exception:
        pass
    return op_k

def write_configs(active_key):
    try:
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                d = json.load(f)
        else:
            d = {}
    except Exception:
        d = {}

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
    d["chat.allowAnonymousAccess"] = True
    d["github.copilot.chat.backgroundAgent.enabled"] = False
    d["github.copilot.chat.cloudAgent.enabled"] = False
    d["chat.defaultToCopilotHarness"] = False
    d["chat.editor.preferCopilotHarness"] = False
    d["chat.editor.localAgent.enabled"] = True
    d["chat.titleBar.signIn.enabled"] = False
    d["chat.growthNotification.enabled"] = False
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
        "brainsos-core": "toolCalling",
        "cindy-active-coding-model": "toolCalling",
        "claude-sonnet-4-5": "toolCalling",
        "claude-haiku-4-5": "toolCalling",
        "claude-3-5-haiku": "toolCalling",
        "amazon-nova-pro": "toolCalling",
        "amazon-nova-lite": "toolCalling",
        "qwen3.8": "toolCalling",
        "qwen3.8:latest": "toolCalling",
        "qwen2.5": "toolCalling",
        "qwen2.5:latest": "toolCalling",
        "llama3.2:3b": "toolCalling",
        "muse-glimmer": "toolCalling",
        "gemma4-MOE": "toolCalling"
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

    # Git & Source Control integration (#340)
    d["github.gitAuthentication"] = False
    d["git.terminalAuthentication"] = False
    d["git.enabled"] = True
    d["git.path"] = "/usr/bin/git"
    d["git.autofetch"] = True
    d["git.confirmSync"] = False
    d["git.enableSmartCommit"] = True
    d["scm.alwaysShowRepositories"] = True

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
        "**/control_plane": True,
        "**/comms": True,
        "**/telemetry": True,
        "**/backups": True,
        "**/litellm_db": True,
        "**/postgres": True,
        "**/langfuse_*": True,
        "**/data/litellm_db": True,
        "**/data/postgres": True,
        "**/data/langfuse_*": True,
        "**/data/langfuse_clickhouse": True,
        "**/data/langfuse_postgres": True,
        "**/data/telemetry": True,
        "**/data/git": True,
        "**/git": True,
        "**/data/control_plane/litellm_db": True
    }
    d["files.watcherExclude"] = {
        "**/.git/objects/**": True,
        "**/.git/subtree-cache/**": True,
        "**/node_modules/**": True,
        "**/.cache/**": True,
        "**/control_plane/**": True,
        "**/comms/**": True,
        "**/telemetry/**": True,
        "**/backups/**": True,
        "**/litellm_db/**": True,
        "**/postgres/**": True,
        "**/langfuse_*/**": True,
        "**/workspace/**": True,
        "**/agent_workspaces/**": True,
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
        "**/data/git/**": True,
        "**/git/**": True,
        "**/.venv/**": True,
        "**/dist/**": True,
        "**/build/**": True
    }

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)

    if os.path.exists(ws_settings_path):
        try:
            with open(ws_settings_path, "r", encoding="utf-8") as f:
                ws_d = json.load(f)
            if isinstance(ws_d, dict):
                ws_d["chat.allowAnonymousAccess"] = True
                ws_d["github.copilot.chat.backgroundAgent.enabled"] = False
                ws_d["github.copilot.chat.cloudAgent.enabled"] = False
                ws_d["chat.defaultToCopilotHarness"] = False
                ws_d["chat.editor.preferCopilotHarness"] = False
                ws_d["chat.editor.localAgent.enabled"] = True
                ws_d["chat.titleBar.signIn.enabled"] = False
                ws_d["chat.growthNotification.enabled"] = False
                ws_d["github.gitAuthentication"] = False
                ws_d["git.terminalAuthentication"] = False
                ws_d["git.enabled"] = True
                ws_d["git.path"] = "/usr/bin/git"
                ws_d["git.autofetch"] = True
                ws_d["git.confirmSync"] = False
                ws_d["git.enableSmartCommit"] = True
                ws_d["scm.alwaysShowRepositories"] = True
                ws_d["files.watcherExclude"] = d["files.watcherExclude"]
                ws_d["search.exclude"] = d["search.exclude"]
                ws_d["litellm-connector.modelCapabilitiesOverrides"] = d["litellm-connector.modelCapabilitiesOverrides"]
                with open(ws_settings_path, "w", encoding="utf-8") as f:
                    json.dump(ws_d, f, indent=2)
        except Exception:
            pass

    domain = os.environ.get("BRAINSOS_DOMAIN", "local.brainsos.ai")
    key_alias = f"{domain}/editor/"
    chat_lm = [
        {
            "name": f"LiteLLM ({key_alias})",
            "vendor": "litellm-connector",
            "baseUrl": "http://litellm:4000",
            "apiKey": active_key
        }
    ]
    with open(lm_json_path, "w", encoding="utf-8") as f:
        json.dump(chat_lm, f, indent=2)

    try:
        with open(aider_path, "w", encoding="utf-8") as f:
            f.write(f"openai-api-base: http://litellm:4000/v1\nopenai-api-key: {active_key}\nmodel: openai/brainsos-core\n")
    except Exception:
        pass

    try:
        os.makedirs(os.path.dirname(vscdb_path), exist_ok=True)
        conn = sqlite3.connect(vscdb_path, timeout=5)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            ("chat.setupContext", json.dumps({"chatSetupCompleted": True, "chatSetupHidden": True})),
        )
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            ("github.copilot.hasByokModels", "true"),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

op_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPERATOR_LITELLM_KEY") or "sk-brainsos-operator-virtual-key"
master_key = os.environ.get("LITELLM_MASTER_KEY") or ""

existing_key = ""
if os.path.exists(lm_json_path):
    try:
        with open(lm_json_path, "r", encoding="utf-8") as f:
            existing_lm = json.load(f)
        if isinstance(existing_lm, list) and existing_lm and isinstance(existing_lm[0], dict):
            existing_key = str(existing_lm[0].get("apiKey") or "").strip()
    except Exception:
        pass

if not is_background:
    # Write initial baseline immediately, then do fast check up to timeout_sec (15s)
    write_configs(existing_key or op_key)
    if wait_for_litellm(timeout_sec):
        if existing_key and key_returns_models(existing_key):
            op_key = existing_key
        elif not key_returns_models(op_key) and master_key:
            op_key = provision_operator_key(op_key, master_key)
            if not key_returns_models(op_key) and key_returns_models(master_key):
                op_key = master_key
        write_configs(op_key)
else:
    # Background loop: wait up to timeout_sec (180s) for LiteLLM liveness and valid /v1/models
    deadline = time.time() + timeout_sec
    synced_with_models = False
    while time.time() < deadline:
        if wait_for_litellm(5):
            candidate = op_key
            if existing_key and key_returns_models(existing_key):
                candidate = existing_key
            elif not key_returns_models(candidate) and master_key:
                candidate = provision_operator_key(op_key, master_key)
                if not key_returns_models(candidate) and key_returns_models(master_key):
                    candidate = master_key
            if key_returns_models(candidate):
                op_key = candidate
                write_configs(op_key)
                if key_returns_models(op_key, require_nonempty=True):
                    if synced_with_models:
                        break
                    synced_with_models = True
                    time.sleep(10)
                    continue
        time.sleep(3)
PYEOF

python3 /tmp/brainsos_sync_byok.py --timeout 15 || true

if command -v jq >/dev/null 2>&1 && [ -f /home/coder/.local/share/code-server/User/settings.json ]; then
  jq '. + {
    "chat.allowAnonymousAccess": true,
    "github.copilot.chat.backgroundAgent.enabled": false,
    "github.copilot.chat.cloudAgent.enabled": false,
    "chat.defaultToCopilotHarness": false,
    "chat.editor.preferCopilotHarness": false,
    "chat.editor.localAgent.enabled": true,
    "chat.titleBar.signIn.enabled": false,
    "chat.growthNotification.enabled": false
  }' /home/coder/.local/share/code-server/User/settings.json > /tmp/user_settings_merged.json \
    && mv /tmp/user_settings_merged.json /home/coder/.local/share/code-server/User/settings.json || true
fi

sync_litellm_byok_loop() {
  python3 /tmp/brainsos_sync_byok.py --timeout 180 --background >/dev/null 2>&1 || true
}

# 3c. Seed workspace settings to /data/.vscode/settings.json if missing
mkdir -p /data/.vscode 2>/dev/null || true
if [ -d /data/.vscode ] && [ ! -f /data/.vscode/settings.json ]; then
  cp /home/coder/.local/share/code-server/User/settings.json /data/.vscode/settings.json 2>/dev/null || true
fi

# 3d. Ensure /etc/brainsos/system.mk exists for the make wrapper
if [ ! -f /etc/brainsos/system.mk ] && [ -f /etc/brainsos/editor/system.mk ]; then
  mkdir -p /etc/brainsos
  cp /etc/brainsos/editor/system.mk /etc/brainsos/system.mk 2>/dev/null || true
fi

# 3e. Configure global Git identity & safe workspace directory for VS Code SCM (#340)
if command -v git >/dev/null 2>&1; then
  git config --global --add safe.directory /data 2>/dev/null || true
  git config --global init.defaultBranch main 2>/dev/null || true
  git config --global user.name "${BRAINSOS_SUPERUSER_NAME:-${BRAINSOS_ADMIN_USERNAME:-brainsOS Operator}}" 2>/dev/null || true
  git config --global user.email "${BRAINSOS_ADMIN_EMAIL:-operator@${BRAINSOS_LOCAL_DOMAIN:-local.brainsos.ai}}" 2>/dev/null || true
  git config --global credential.helper "store --file=/data/.git/credentials" 2>/dev/null || true
  git config --global push.default simple 2>/dev/null || true
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
if [ -s "${CADDY_ROOT_CA}" ]; then
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

# Spawn background helper to re-sync BYOK key and settings once LiteLLM finishes migrations
sync_litellm_byok_loop &

# Launch upstream entrypoint opening /data as the single workspace root
TARGET_DIR="${1:-/data}"
if [ $# -gt 0 ] && [ -n "${1:-}" ] && [[ "${1}" != -* ]]; then
  TARGET_DIR="$1"
  shift
fi

exec /usr/bin/entrypoint.sh --bind-addr 0.0.0.0:8443 --auth "${CODE_SERVER_AUTH}" --disable-telemetry --disable-workspace-trust "${TARGET_DIR}" "$@"
