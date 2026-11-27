# ==============================================================================
# brainsOS: Warm Claude SDK Runner Container
# Serves cognitive turns using Anthropic Claude SDK (Direct API or AWS Bedrock)
# ==============================================================================

FROM brainsos-runner-base:latest

USER root
RUN uv pip install --system "anthropic>=0.40.0" "boto3" "mcp>=1.0.0" "httpx>=0.25.0"

COPY --chown=10001:10001 docker/runners/claude-sdk/server.py /app/server.py
RUN chown -R 10001:10001 /app

USER 10001:10001
WORKDIR /workspace

EXPOSE 8001

CMD ["uvicorn", "server:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8001"]
