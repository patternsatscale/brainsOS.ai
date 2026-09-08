# ==============================================================================
# Project Titan: Upstream Hermes Agent Sandbox Image
# Built on the official Nous Research Hermes Agent distribution
# Pre-configured with Titan OKF Memory Plugin, multi-channel gateways & sandboxing
# ==============================================================================

FROM nousresearch/hermes-agent:latest

# Install native Titan OKF memory plugin
COPY docker/hermes/plugins/hermes-okf /opt/hermes/plugins/hermes-okf
RUN ln -sf /opt/hermes/plugins/hermes-okf /opt/hermes/plugins/memory/hermes-okf

# Switch to /opt/data
WORKDIR /opt/data

EXPOSE 8642 9119
