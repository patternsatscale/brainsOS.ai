# ==============================================================================
# Project Titan: Upstream Hermes Agent Sandbox Image
# Built on the official Nous Research Hermes Agent distribution
# Pre-configured with Titan OKF Memory Plugin, multi-channel gateways & sandboxing
# ==============================================================================

FROM nousresearch/hermes-agent:latest

# Install standalone titan-memory package (L5: Memory & Tools)
COPY packages/titan_memory /opt/hermes/packages/titan_memory
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/titan_memory

# Install standalone titan-mail package (Communications Plane)
COPY packages/titan_mail /opt/hermes/packages/titan_mail
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/titan_mail

# Install native Titan OKF memory plugin
COPY docker/hermes/plugins/hermes-okf /opt/hermes/plugins/hermes-okf
RUN ln -sf /opt/hermes/plugins/hermes-okf /opt/hermes/plugins/memory/hermes-okf

# Install native Titan Mail plugin & tools
COPY docker/hermes/plugins/titan-mail /opt/hermes/plugins/titan-mail

# Install GitHub CLI (gh), Git tooling, and configure safe container defaults
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends gh git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    git config --system --add safe.directory '*' && \
    git config --system core.askPass "" && \
    mkdir -p /etc/skel/.config/gh /root/.config/gh /home/hermes/.config/gh && \
    printf 'github.com:\n    user: x-access-token\n    oauth_token: in-transit-placeholder\n    git_protocol: https\n' | tee /etc/skel/.config/gh/hosts.yml /root/.config/gh/hosts.yml /home/hermes/.config/gh/hosts.yml >/dev/null && \
    chown -R hermes:hermes /home/hermes/.config

# Install Tool Egress Proxy CA trust boot hook
COPY docker/hermes/01-tool-egress-ca /etc/cont-init.d/01-tool-egress-ca
RUN chmod +x /etc/cont-init.d/01-tool-egress-ca


# Switch to /opt/data
WORKDIR /opt/data

EXPOSE 8642 9119
