# ==============================================================================
# brainsOS: Warm Hermes Runner Container
# Serves stateless cognitive turns over universal IPC (/v1/agent/run) on port 8642
# and runtime configuration WebUI on port 8787
# ==============================================================================

FROM brainsos-runner-base:latest

USER root
RUN uv pip install --system "openai==3.26.0" "httpx==0.28.1" "pyyaml==6.0.3"

COPY --chown=10001:10001 docker/runners/hermes/server.py /app/server.py
COPY --chown=10001:10001 docker/runners/hermes/webui.py /app/webui.py
COPY --chown=10001:10001 docker/runners/hermes/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh && chown -R 10001:10001 /app

USER 10001:10001
WORKDIR /workspace

EXPOSE 8642
EXPOSE 8787

CMD ["/app/entrypoint.sh"]
