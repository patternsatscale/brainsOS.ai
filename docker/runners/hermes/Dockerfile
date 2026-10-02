# ==============================================================================
# brainsOS: Warm Hermes Runner Container
# Serves stateless cognitive turns over universal IPC (/v1/agent/run) on port 8642
# ==============================================================================

FROM brainsos-runner-base:latest

RUN uv pip install --system "openai>=1.50.0" "httpx>=0.25.0"

COPY docker/runners/hermes/server.py /app/server.py

WORKDIR /workspace

EXPOSE 8642

CMD ["uvicorn", "server:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8642"]
