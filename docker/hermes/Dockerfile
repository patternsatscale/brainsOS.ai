# ==============================================================================
# Project Titan: Upstream Hermes Agent Sandbox Image
# Built on the official Nous Research Hermes Agent distribution
# Pre-configured with Titan OKF Memory Plugin, multi-channel gateways & sandboxing
# ==============================================================================

FROM nousresearch/hermes-agent:latest

# Install standalone titan-memory package (L5: Memory & Tools)
COPY packages/titan_memory /opt/hermes/packages/titan_memory
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/titan_memory

# Install native Titan OKF memory plugin
COPY docker/hermes/plugins/hermes-okf /opt/hermes/plugins/hermes-okf
RUN ln -sf /opt/hermes/plugins/hermes-okf /opt/hermes/plugins/memory/hermes-okf

# Install GitHub CLI (gh), Git tooling, and configure safe container defaults
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends gh git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    git config --system --add safe.directory '*' && \
    git config --system credential.helper '!gh auth git-credential' && \
    git config --system url."https://github-proxy.titan.local/".insteadOf "https://github.com/" && \
    git config --system core.askPass ""

# Install Caddy PKI trust boot hook for in-transit proxy credential injection
COPY docker/hermes/00-caddy-ca /etc/cont-init.d/00-caddy-ca
RUN chmod +x /etc/cont-init.d/00-caddy-ca

# Switch to /opt/data
WORKDIR /opt/data

EXPOSE 8642 9119
