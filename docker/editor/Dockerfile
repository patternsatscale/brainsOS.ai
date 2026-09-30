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
      jq && \
    rm -rf /var/lib/apt/lists/*

# Install Astral uv package manager and Aider CLI with Python 3.12 into /opt/uv-tools
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV UV_TOOL_DIR=/opt/uv-tools
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh && \
    uv tool install --python 3.12 aider-chat && \
    chmod -R a+rx /opt/uv-python /opt/uv-tools

# Install fleet chat helper script
COPY docker/editor/brainsos-chat /usr/local/bin/brainsos-chat
RUN chmod +x /usr/local/bin/brainsos-chat

# Pre-create extensions directory with coder ownership
RUN mkdir -p /opt/code-server/extensions && chown -R coder:coder /opt/code-server

# Pre-install VS Code extensions into /opt/code-server/extensions
USER coder
RUN code-server --extensions-dir /opt/code-server/extensions --install-extension yzhang.markdown-all-in-one && \
    code-server --extensions-dir /opt/code-server/extensions --install-extension foam.foam-vscode && \
    code-server --extensions-dir /opt/code-server/extensions --install-extension Continue.continue

# Copy entrypoint wrapper
USER root
COPY docker/editor/entrypoint.sh /usr/local/bin/brainsos-editor-entrypoint.sh
RUN chmod +x /usr/local/bin/brainsos-editor-entrypoint.sh

# Environment settings
ENV OPENAI_API_BASE=http://litellm:4000/v1
ENV AIDER_DARK_MODE=true

USER coder
WORKDIR /workspace

EXPOSE 8443

ENTRYPOINT ["/usr/local/bin/brainsos-editor-entrypoint.sh"]
