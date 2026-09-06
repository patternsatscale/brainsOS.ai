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

# Copy agent server application
COPY docker/hermes/server.py /app/server.py
RUN chmod +x /app/server.py && chown hermes:hermes /app/server.py

# Switch to unprivileged user
USER hermes
WORKDIR /workspace

EXPOSE 8642

CMD ["python3", "/app/server.py"]
