# ==============================================================================
# brainsOS: Upstream Hermes Agent Sandbox Image
# Built on the official Nous Research Hermes Agent distribution
# Pre-configured with brainsOS OKF Memory Plugin, multi-channel gateways & sandboxing
# ==============================================================================

FROM nousresearch/hermes-agent:latest

# Install standalone brainsOS-memory package (L5: Memory & Tools)
COPY packages/brainsOS-memory /opt/hermes/packages/brainsOS-memory
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-memory

# Install standalone brainsOS-mail package (Communications Plane)
COPY packages/brainsOS-mail /opt/hermes/packages/brainsOS-mail
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-mail

# Install standalone brainsOS-queue package (Asynchronous Work Queue)
COPY packages/brainsOS-queue /opt/hermes/packages/brainsOS-queue
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-queue

# Install standalone brainsOS-telemetry package (Observability & Energy Accounting)
COPY packages/brainsOS-telemetry /opt/hermes/packages/brainsOS-telemetry
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-telemetry

# Install standalone brainsOS-mcp package (Dynamic Capabilities MCP Server)
COPY packages/brainsOS-mcp /opt/hermes/packages/brainsOS-mcp
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-mcp

# Install standalone brainsOS-runner package (Compute Plane)
COPY packages/brainsOS-runner /opt/hermes/packages/brainsOS-runner
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-runner

# Install standalone brainsOS-agent package (Agent Runtime & Dynamic Profile SPI)
COPY packages/brainsOS-agent /opt/hermes/packages/brainsOS-agent
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv -e /opt/hermes/packages/brainsOS-agent

# Install Langfuse SDK for native observability plugin
RUN /usr/local/bin/uv pip install --python /opt/hermes/.venv langfuse

# Install GitHub CLI (gh), Git tooling, and configure safe container defaults
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends gh git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    git config --system --add safe.directory '*' && \
    git config --system core.askPass "" && \
    mkdir -p /etc/skel/.config/gh /root/.config/gh /home/hermes/.config/gh && \
    printf 'github.com:\n    user: x-access-token\n    oauth_token: in-transit-placeholder\n    git_protocol: https\n' | tee /etc/skel/.config/gh/hosts.yml /root/.config/gh/hosts.yml /home/hermes/.config/gh/hosts.yml >/dev/null && \
    usermod -u 1000 hermes && groupmod -g 1000 hermes && \
    chown -R hermes:hermes /home/hermes

# Install Tool Egress Proxy CA trust boot hook
COPY docker/hermes/01-tool-egress-ca /etc/cont-init.d/01-tool-egress-ca
RUN chmod +x /etc/cont-init.d/01-tool-egress-ca


# Switch to /opt/data
WORKDIR /opt/data

EXPOSE 8642 9119
