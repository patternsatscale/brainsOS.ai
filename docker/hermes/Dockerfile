# ==============================================================================
# Project Titan: Hermes Agent Sandbox Image
# Unprivileged ARM64/AMD64 runtime with WAN egress, tool flexibility & isolation
# ==============================================================================

FROM python:3.11-slim

# Install baseline networking and development utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    jq \
    git \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged runtime user and group (1000:1000)
RUN groupadd -g 1000 hermes && \
    useradd -u 1000 -g hermes -m -s /bin/bash hermes && \
    mkdir -p /workspace /app /memories && \
    chown -R hermes:hermes /workspace /app /memories

# Copy agent server application and OKF memory plugin
COPY docker/hermes/server.py /app/server.py
COPY docker/hermes/hermes_okf.py /app/hermes_okf.py
RUN chmod +x /app/server.py /app/hermes_okf.py && \
    chown hermes:hermes /app/server.py /app/hermes_okf.py && \
    mkdir -p /workspace/skills && \
    cp /app/hermes_okf.py /workspace/skills/hermes_okf.py && \
    chown -R hermes:hermes /workspace

# Switch to unprivileged user
USER hermes
WORKDIR /workspace

EXPOSE 8642

CMD ["python3", "/app/server.py"]
