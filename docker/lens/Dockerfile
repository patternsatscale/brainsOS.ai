# ==============================================================================
# brainsOS: LiteLLM Lens Observability Service (Multi-Stage Rootless ARM64 Build)
# Built from pinned BerriAI/lens commit fa1b82f6ad67c63e82b949d73f0ea50914397dd5
# ==============================================================================

ARG LENS_GIT_REPO=https://github.com/BerriAI/lens.git
ARG LENS_GIT_COMMIT=fa1b82f6ad67c63e82b949d73f0ea50914397dd5
ARG LENS_BUILD_IMAGE=cgr.dev/chainguard/wolfi-base@sha256:ae9575b121f5776e2f04e192064bc2c5665af9d1c425d620dc773aca31698712
ARG LENS_RUNTIME_IMAGE=cgr.dev/chainguard/wolfi-base@sha256:ae9575b121f5776e2f04e192064bc2c5665af9d1c425d620dc773aca31698712
ARG LENS_UI_BUILD_IMAGE=node:24.14.1-bookworm-slim@sha256:b506e7321f176aae77317f99d67a24b272c1f09f1d10f1761f2773447d8da26c
ARG LENS_AGENT_BUILD_IMAGE=node:24.22.1-bookworm-slim@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c

FROM $LENS_BUILD_IMAGE AS source
ARG LENS_GIT_REPO
ARG LENS_GIT_COMMIT
RUN apk add --no-cache git ca-certificates
WORKDIR /lens-src
RUN git init && \
    git remote add origin "${LENS_GIT_REPO}" && \
    git fetch --depth 1 origin "${LENS_GIT_COMMIT}" && \
    test "$(git rev-parse FETCH_HEAD)" = "${LENS_GIT_COMMIT}" && \
    git checkout --detach FETCH_HEAD && \
    rm -rf .git

FROM $LENS_UI_BUILD_IMAGE AS ui-builder
WORKDIR /src
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=source /lens-src/package.json /lens-src/package-lock.json ./
COPY --from=source /lens-src/src/ui/lib/package.json src/ui/lib/package.json
COPY --from=source /lens-src/src/ui/app/package.json src/ui/app/package.json
RUN npm ci
COPY --from=source /lens-src/src/ui/ src/ui/
RUN npm run build:ui

FROM $LENS_AGENT_BUILD_IMAGE AS agent-builder
WORKDIR /app/agent
COPY --from=source /lens-src/src/agent/package.json /lens-src/src/agent/package-lock.json ./
RUN npm ci --ignore-scripts
COPY --from=source /lens-src/src/agent/ ./
RUN npm run build
WORKDIR /app/agent-chat
COPY --from=source /lens-src/src/agent-chat/package.json /lens-src/src/agent-chat/package-lock.json ./
RUN npm ci --ignore-scripts
COPY --from=source /lens-src/src/agent-chat/ ./
RUN npm run build && npm prune --omit=dev --ignore-scripts && npm prune --prefix ../agent --omit=dev --ignore-scripts && \
    rm -f dist/*.test.js dist/*.test.d.ts dist/connectors/slack/*.test.js dist/connectors/slack/*.test.d.ts ../agent/dist/*.test.js ../agent/dist/*.test.d.ts

FROM $LENS_BUILD_IMAGE AS builder
ARG CARGO_BUILD_JOBS=8
RUN apk add --no-cache rust build-base cmake perl pkgconf openssl-dev libseccomp-dev python-3.13 jq git
WORKDIR /src
COPY --from=source /lens-src/.cargo/ .cargo/
COPY --from=source /lens-src/src/worker/ src/worker/
WORKDIR /src/src/worker
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS} CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_PROFILE_RELEASE_STRIP=symbols \
    CARGO_PROFILE_RELEASE_LTO=thin CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
# Fix upstream BerriAI/lens fa1b82f6 trailing-comma CTE bug when concatenating lens_eval_spend.sql + lens_availability.sql
RUN python3.13 -c 'from pathlib import Path; p = Path("crates/traces-clickhouse/query/lens_availability.sql"); s = p.read_text(); assert s.startswith("SELECT\n"); p.write_text("_availability_anchor AS (SELECT 1)\n" + s)'
RUN cargo build --locked --release -p litellm-lens
RUN TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    LENS_PROFILE_MODEL_CACHE=/opt/lens-profile-model cargo run --locked --release -p lens-profiles --example resource_probe -- 1
RUN cargo build --locked --release -p lens-migrate
RUN cc -std=c11 -D_GNU_SOURCE -O2 -Wall -Wextra -Werror crates/lens/sandbox/python_policy.c -lseccomp -o /tmp/python-policy && \
    /tmp/python-policy /tmp/python.seccomp

FROM $LENS_RUNTIME_IMAGE AS runtime
ARG LENS_GIT_COMMIT
ARG LENS_VERSION=0.5.2-${LENS_GIT_COMMIT}
RUN apk add --no-cache --upgrade python-3.13 setpriv libgcc libstdc++ openssl ca-certificates ca-certificates-bundle curl libatomic
ENV LENS_VERSION=${LENS_VERSION} PYTHONDONTWRITEBYTECODE=1 LENS_UI_DIRECTORY=/app/ui \
    LENS_PROFILE_MODEL_CACHE=/app/profile-model
WORKDIR /app
COPY --from=builder /src/src/worker/target/release/litellm-lens /usr/local/bin/litellm-lens
COPY --from=builder /src/src/worker/target/release/lens-migrate /usr/local/bin/lens-migrate
COPY --from=builder --chown=65532:65532 /opt/lens-profile-model/ /app/profile-model/
COPY --from=builder /tmp/python.seccomp /app/lens/python.seccomp
COPY --from=ui-builder /src/src/ui/app/out/ /app/ui/
COPY --from=agent-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-builder /app/agent/ /app/agent/
COPY --from=agent-builder /app/agent-chat/ /app/agent-chat/
COPY --from=source /lens-src/src/worker/crates/lens/sandbox/python_runtime.py /tmp/python_runtime.py
RUN python3.13 -S /tmp/python_runtime.py /app/lens/python-runtime.json && rm /tmp/python_runtime.py
USER 65532:65532
EXPOSE 4318
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 CMD curl --fail --silent http://127.0.0.1:4318/health/ready > /dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/node", "/app/agent-chat/dist/supervisor.js"]
