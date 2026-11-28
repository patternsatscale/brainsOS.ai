# ==============================================================================
# brainsOS: Warm OpenAI SDK Runner Container
# Serves cognitive turns using the OpenAI SDK and supports dynamic script execution
# ==============================================================================

FROM brainsos-runner-base:latest

USER root
RUN uv pip install --system "openai==3.29.0" "mcp==2.3.0" "httpx==0.28.1"

COPY --chown=10001:10001 docker/runners/openai-sdk/server.py /app/server.py
RUN chown -R 10001:10001 /app

USER 10001:10001
WORKDIR /workspace

EXPOSE 8002

CMD ["uvicorn", "server:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8002"]
