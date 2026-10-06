# ==============================================================================
# brainsOS: Warm Hermes Runner Container
# Serves stateless cognitive turns over universal IPC (/v1/agent/run) on port 8642
# and runtime configuration WebUI on port 8787
# ==============================================================================

FROM brainsos-runner-base:latest

RUN uv pip install --system "openai>=1.50.0" "httpx>=0.25.0" "pyyaml>=6.0.1"

COPY docker/runners/hermes/server.py /app/server.py
COPY docker/runners/hermes/webui.py /app/webui.py
COPY docker/runners/hermes/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

WORKDIR /workspace

EXPOSE 8642
EXPOSE 8787

CMD ["/app/entrypoint.sh"]
