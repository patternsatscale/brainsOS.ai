# ==============================================================================
# brainsOS: Base Runner Container Image
# Provides Python 3.12, uv, non-root execution, and brainsOS-runner core runtime.
# ==============================================================================

FROM python:3.12-slim-bookworm

# Install essential system utilities
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git && \
    rm -rf /var/lib/apt/lists/* && \
    git config --system --add safe.directory '*'

# Copy pinned uv binaries for high-performance package management
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

# Create dedicated unprivileged runner user (uid 10001 / gid 10001 - #387)
RUN groupadd -g 10001 runner && \
    useradd -u 10001 -g runner -m -s /bin/bash runner

# Install brainsOS-telemetry, brainsOS-runner, and uvicorn into system python
WORKDIR /opt/brainsos
COPY packages/brainsOS-telemetry /opt/brainsos/packages/brainsOS-telemetry
COPY packages/brainsOS-runner /opt/brainsos/packages/brainsOS-runner
RUN uv pip install --system "/opt/brainsos/packages/brainsOS-telemetry" "/opt/brainsos/packages/brainsOS-runner" uvicorn

USER 10001:10001
WORKDIR /workspace
