# ==============================================================================
# brainsOS: Warm OpenAI SDK Runner Container
# Serves cognitive turns using the OpenAI SDK and supports dynamic script execution
# ==============================================================================

FROM brainsos-runner-base:latest

RUN uv pip install --system "openai>=1.50.0" "mcp>=1.0.0" "httpx>=0.25.0"

COPY docker/runners/openai-sdk/server.py /app/server.py

WORKDIR /workspace

EXPOSE 8002

CMD ["uvicorn", "server:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8002"]
