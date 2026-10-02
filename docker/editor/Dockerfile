# ==============================================================================
# brainsOS: Operator IDE Container Image
# Built on codercom/code-server:latest (native ARM64 / AMD64 parity)
# Pre-configured with Multi-Root Workspace, Aider, Goose, and PKM extensions
# ==============================================================================

FROM codercom/code-server:latest

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

# Patch LiteLLM Connector extension: remove "secret": true from apiKey field in languageModelChatProviders.
# In headless code-server, VS Code's SecretStorage cannot resolve secrets via its GUI prompt, so the
# apiKey resolves to an empty string and the extension throws "API key is empty". Removing this flag
# makes code-server pass the apiKey value from chatLanguageModels.json directly into the extension.
USER root
RUN LITELLM_PKG=$(find /opt/code-server/extensions -path "*/gethnet.litellm-connector-copilot-*/package.json" | head -1) && \
    python3 -c "
import json, sys
with open('${LITELLM_PKG}', 'r') as f: c = f.read()
c = c.replace('\"secret\": true,', '').replace('\"secret\": true', '')
with open('${LITELLM_PKG}', 'w') as f: f.write(c)
print('Patched:', '${LITELLM_PKG}')
"

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
