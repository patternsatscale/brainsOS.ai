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

# Copy uv binaries for high-performance package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

# Create non-root runner user (uid 1000 / gid 1000)
RUN groupadd -g 1000 runner && \
    useradd -u 1000 -g runner -m -s /bin/bash runner

# Install brainsOS-runner package and uvicorn into system python
WORKDIR /opt/brainsos
COPY packages/brainsOS-runner /opt/brainsos/packages/brainsOS-runner
RUN uv pip install --system "/opt/brainsos/packages/brainsOS-runner" uvicorn

WORKDIR /workspace
