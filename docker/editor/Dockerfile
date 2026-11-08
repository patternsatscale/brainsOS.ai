# ==============================================================================
# brainsOS: Operator IDE Container Image
# Built on codercom/code-server:latest (native ARM64 / AMD64 parity)
# Pre-configured with Multi-Root Workspace, Aider, Goose, and PKM extensions
# ==============================================================================

ARG CODE_SERVER_IMAGE_TAG=latest
FROM codercom/code-server:${CODE_SERVER_IMAGE_TAG}
ARG CODE_SERVER_IMAGE_TAG=latest
LABEL org.opencontainers.image.version="${CODE_SERVER_IMAGE_TAG}"

USER root

# Install Python 3, pip, venv, bzip2, curl, git, jq, and dependencies
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-yaml \
      python3-venv \
      bzip2 \
      curl \
      git \
      ca-certificates \
      jq \
      make && \
    rm -rf /var/lib/apt/lists/*

# Install Astral uv package manager and Aider CLI with Python 3.12 into /opt/uv-tools
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV UV_TOOL_DIR=/opt/uv-tools
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh && \
    uv tool install --python 3.12 aider-chat && \
    chmod -R a+rx /opt/uv-python /opt/uv-tools

# Install brainsOS Terminal CLI package and smart make interceptor
COPY packages/brainsOS-terminal /tmp/packages/brainsOS-terminal
RUN uv pip install --system --break-system-packages /tmp/packages/brainsOS-terminal && rm -rf /tmp/packages

# Pre-create extensions directory with coder ownership
RUN mkdir -p /opt/code-server/extensions && chown -R coder:coder /opt/code-server

# Install custom brainsOS extensions
COPY --chown=coder:coder config/editor/extensions/brainsos-system-terminal /opt/code-server/extensions/brainsos.system-terminal-1.0.0

# Pre-install VS Code extensions into /opt/code-server/extensions
USER coder
RUN code-server --extensions-dir /opt/code-server/extensions --install-extension yzhang.markdown-all-in-one && \
    code-server --extensions-dir /opt/code-server/extensions --install-extension foam.foam-vscode && \
    code-server --extensions-dir /opt/code-server/extensions --install-extension Gethnet.litellm-connector-copilot

# Patch LiteLLM Connector extension, Foam views, and VS Code Workbench Chat / GitHub Auth:
# 1. Remove "secret": true from Gethnet.litellm-connector-copilot apiKey field so code-server
#    passes apiKey from chatLanguageModels.json directly without a GUI SecretStorage prompt.
# 2. Hide Foam explorer subviews by default.
# 3. Disable startup auto-activation ("*") on built-in vscode.github extension so it never
#    requests a GitHub session on workspace load.
# 4. Patch VS Code workbench.web.main.internal.js and product.json so DefaultAccountService,
#    ChatEntitlementContext, and ChatSetupAgent operate locally against brainsOS LiteLLM
#    without ever prompting to sign into GitHub.
USER root
RUN LITELLM_PKG=$(find /opt/code-server/extensions -path "*/gethnet.litellm-connector-copilot-*/package.json" | head -1) && \
    python3 -c "import json, sys; f_path = sys.argv[1]; c = open(f_path).read().replace('\"secret\": true,', '').replace('\"secret\": true', ''); open(f_path, 'w').write(c); print('Patched:', f_path)" "${LITELLM_PKG}" && \
    FOAM_PKG=$(find /opt/code-server/extensions -path "*/foam.foam-vscode-*/package.json" | head -1) && \
    python3 -c "import json, sys; p = sys.argv[1]; d = json.load(open(p)); [v.update({'when': 'false'}) for v in d.get('contributes', {}).get('views', {}).get('explorer', [])]; json.dump(d, open(p, 'w'), indent=2); print('Patched foam views:', p)" "${FOAM_PKG}" && \
    python3 - << 'PYEOF'
import json
import os
import subprocess

gh_pkg = "/usr/lib/code-server/lib/vscode/extensions/github/package.json"
if os.path.exists(gh_pkg):
    with open(gh_pkg, "r", encoding="utf-8") as f:
        gh_data = json.load(f)
    gh_data["activationEvents"] = ["onCommand:github.publish"]
    with open(gh_pkg, "w", encoding="utf-8") as f:
        json.dump(gh_data, f, indent=2)
    print("Patched github extension activationEvents:", gh_pkg)

prod_json = "/usr/lib/code-server/lib/vscode/product.json"
if os.path.exists(prod_json):
    with open(prod_json, "r", encoding="utf-8") as f:
        prod_data = json.load(f)
    dca = prod_data.get("defaultChatAgent")
    if isinstance(dca, dict):
        dca["extensionId"] = "Gethnet.litellm-connector-copilot"
        dca["chatExtensionId"] = "Gethnet.litellm-connector-copilot"
        if isinstance(dca.get("provider"), dict) and isinstance(dca["provider"].get("default"), dict):
            dca["provider"]["default"]["name"] = "brainsOS"
    with open(prod_json, "w", encoding="utf-8") as f:
        json.dump(prod_data, f, indent=2)
    print("Patched defaultChatAgent in:", prod_json)

wb_candidates = [
    "/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js",
    "/usr/lib/code-server/lib/vscode/out/vs/workbench/workbench.web.main.internal.js",
]
wb = next((p for p in wb_candidates if os.path.exists(p)), None)
assert wb, f"No workbench JS found in {wb_candidates}"
with open(wb, "r", encoding="utf-8") as f:
    s = f.read()

import re

if "async whenDefaultAccountAuthenticationProviderAvailable(){" in s:
    s, cnt = re.subn(
        r"async whenDefaultAccountAuthenticationProviderAvailable\(\)\{",
        "async whenDefaultAccountAuthenticationProviderAvailable(){if(!0)return;",
        s,
        count=1,
    )
    assert cnt == 1

regex_patches = [
    (
        r"async fetchDefaultAccount\([a-zA-Z0-9_]*\)\{",
        r'\g<0>if(!0)return{defaultAccount:{authenticationProvider:{id:"github",name:"brainsOS",enterprise:!0},accountName:"brainsOS Operator",sessionId:"brainsos-local",enterprise:!0,entitlementsData:{access_type_sku:"free_limited_copilot",copilot_plan:"enterprise",chat_enabled:!0,can_signup_for_limited:!1}},accountId:"brainsos-local",policyData:{accountId:"brainsos-local",policyData:{chat_agent_enabled:!0,chat_preview_features_enabled:!0,mcp:!0}},copilotTokenInfo:{}};',
    ),
    (
        r"this\._state=this\.storageService\.getObject\([A-Za-z0-9_$]+\.CHAT_ENTITLEMENT_CONTEXT_STORAGE_KEY,0\)\?\?\{entitlement:1,[^}]+\}",
        r'this._state={...(\g<0>),entitlement:9,installed:!0,completed:!0,registered:!0,hidden:!1,disabled:!1,untrusted:!1,sku:"enterprise"}',
    ),
    (
        r"this\.signedOutContextKey\.set\(e\.entitlement===1\)",
        r"this.signedOutContextKey.set(!1)",
    ),
    (
        r"this\.completedContext\.set\(!!e\.completed\)",
        r"this.completedContext.set(!0)",
    ),
    (
        r"this\.installedContext\.set\(!!e\.installed\)",
        r"this.installedContext.set(!0)",
    ),
    (
        r"async checkExtensionInstallation\(e\)\{",
        r"async checkExtensionInstallation(e){if(!0){e.update({installed:!0,disabled:!1,untrusted:!1,disabledInWorkspace:!1,completed:!0});return}",
    ),
    (
        r"async doRun\([a-zA-Z0-9_]+\)\{this\.context\.update\(\{later:!1\}\);",
        r"\g<0>if(!0)return this.context.update({later:!1,completed:!0,installed:!0,disabled:!1,untrusted:!1,hidden:!1}),{success:!0,dialogSkipped:!0};",
    ),
    (
        r"return ([A-Za-z0-9_$]+)\.doRegisterAgent\(([^`]+)`\$\{[A-Za-z0-9_$]+\.provider\.default\.name\} Copilot`",
        r'return \1.doRegisterAgent(\2"brainsOS LiteLLM"',
    ),
    (
        r"metadata:\{helpTextPrefix:[A-Za-z0-9_$]+\.SETUP_NEEDED_MESSAGE\}",
        r"metadata:{}",
    ),
    (
        r"async doInvoke\(e,t,[a-zA-Z0-9_]+,n,r,[a-zA-Z0-9_]+,[a-zA-Z0-9_]+,[a-zA-Z0-9_]+\)\{",
        r'\g<0>if(!0){try{const MS=this.constructor.SETUP_NEEDED_MESSAGE.constructor,ct={isCancellationRequested:!1,onCancellationRequested:()=>({dispose(){}})};let u=r.getWidgetBySessionResource(e.sessionResource),m=e.userSelectedModelId||u?.input?.currentLanguageModel;if(!m||!n.lookupLanguageModel(m)){let ids=await n.selectLanguageModels({});m=ids.find(x=>x.includes("litellm")||x.includes("brainsos"))||ids[0]}if(!m){t({kind:"markdownContent",content:new MS("No language model registered yet. Waiting for LiteLLM gateway...")});return{}}let reqs=u?.viewModel?.model?.getRequests()||[],msgs=[];for(let rq of reqs){let txt=rq.message?.text||"";if(txt)msgs.push({role:1,content:[{type:"text",value:txt}]});if(rq!==reqs.at(-1)&&rq.response?.response){let rt=rq.response.response.toString();if(rt)msgs.push({role:2,content:[{type:"text",value:rt}]})}}if(!msgs.length)msgs.push({role:1,content:[{type:"text",value:e.message||""}]});let resp=await n.sendChatRequest(m,void 0,msgs,{},ct);for await(let part of resp.stream){let pts=Array.isArray(part)?part:[part];for(let p of pts){if(p?.type==="text"&&p.value)t({kind:"markdownContent",content:new MS(p.value)})}}await resp.result;return{}}catch(err){this.logService.error("[brainsOS chat]",err);const MS=this.constructor.SETUP_NEEDED_MESSAGE.constructor;t({kind:"markdownContent",content:new MS("Error communicating with LiteLLM: "+String(err?.message||err))});return{}}}',
    ),
]

for pat, repl in regex_patches:
    s, cnt = re.subn(pat, repl, s, count=1)
    assert cnt == 1, f"Expected 1 match for pattern {pat!r}, got {cnt}"

with open(wb, "w", encoding="utf-8") as f:
    f.write(s)

subprocess.run(["/usr/lib/code-server/lib/node", "--check", wb], check=True)
print("Successfully patched and verified workbench:", wb)
PYEOF

# Copy entrypoint wrapper
USER root
COPY docker/editor/entrypoint.sh /usr/local/bin/brainsos-editor-entrypoint.sh
RUN chmod +x /usr/local/bin/brainsos-editor-entrypoint.sh

# Environment settings
ENV OPENAI_API_BASE=http://litellm:4000/v1
ENV AIDER_DARK_MODE=true

USER coder
WORKDIR /data

EXPOSE 8443

ENTRYPOINT ["/usr/local/bin/brainsos-editor-entrypoint.sh"]
