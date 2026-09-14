# Project Titan: Autonomous Agent Workspace Specification

This repository contains the complete infrastructure, configuration manifests, and orchestration scripts for **Project Titan**—an isolated, secure, and human-auditable autonomous AI agent appliance built on an **ASUS Ascent GX10** running DGX OS (Ubuntu 24.04 ARM64).

The system architecture enforces an absolute boundary between execution runtimes, routing paths, and memory states to ensure zero-trust operations within local infrastructure.

-----

## 1\. System Topology & Philosophy

Project Titan transforms a dedicated bare-metal system into a transactional black box. Rather than running unverified Python loops or local AI tooling directly on the host operating system, the entire application stack is containerized, isolated, and structured according to the **Titan L1–L7 Reference Model**:

### Titan L1–L7 Reference Model

``` text
┌─────────────────────────────────────────────────────────────────────────────┐
│ L7: Communications & UX                                                     │
│     - Ingress Reverse Proxy: Caddy (*.titan.local, TLS, streaming SSE)      │
│     - Messaging Daemons: titan-signal-cli (JSON-RPC daemon on :8080)        │
│     - Human-in-the-Loop PKM: SilverBullet UI (:3000 -> /space)              │
├─────────────────────────────────────────────────────────────────────────────┤
│ L6: Agent Core Units (Manifest-Driven Fleet: config/agents.yaml)            │
│     - titan-agent-primary       (:8642 API, :9119 Dashboard, $50 Budget)    │
│     - titan-agent-football-dan  (:8643 API, :9120 Dashboard, $25 Budget)    │
│     - titan-agent-cindy-pawford (:8644 API, :9121 Dashboard, $25 Budget)    │
│     - Personas: config/hermes/personas/*.md (SOUL.md isolation)             │
├─────────────────────────────────────────────────────────────────────────────┤
│ L5: Memory Plane & Tool Sandbox                                             │
│     - Standalone Package: packages/titan_memory/ (OKF Engine & Vector SPI)  │
│     - Partitioned Memories: ./data/memories/agents/<id> (Pure Markdown)     │
│     - Tenant Workspaces:   ./data/workspace/<id> (Tools, Caches, DBs)       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L4: Routing & Security Control Plane                                        │
│     - LiteLLM Gateway (:4000) with dynamic virtual keys & spend limits      │
│     - Hardware Serialization: max_parallel_requests: 1 (LPDDR5x guard)      │
│     - Control Plane DB: titan-litellm-db (PostgreSQL 16, titan-litellm-net) │
├─────────────────────────────────────────────────────────────────────────────┤
│ L3: Inference Plane                                                         │
│     - Host Ollama / vLLM bound strictly to loopback (127.0.0.1:11434)       │
│     - Zero direct agent access; all completions route through LiteLLM       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L2: Virtualization & Isolated Bridge Networks                               │
│     - titan-ingress (Caddy -> Service ports)                                │
│     - titan-internal (Agent egress & Signal daemon)                         │
│     - titan-litellm-net (Strictly isolates PostgreSQL from agents)          │
├─────────────────────────────────────────────────────────────────────────────┤
│ L1: Hardware & System Plane                                                 │
│     - ASUS Ascent GX10 (NVIDIA GB10 ARM64, unified LPDDR5x ~273 GB/s)       │
│     - Development Workstation: Apple Silicon macOS (native ARM64 parity)    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Cross-Cutting: Observability & Operational Safety                           │
│     - Decoupled Langfuse v2 + OpenTelemetry distributed tracing             │
│     - Unified full-data backup (scripts/backup.sh)                          │
│     - Granular single-tenant emergency kill-switch (scripts/emergency-stop) │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Architecture Rules

  * **Zero Direct Connect (Rule 2):** The agent layer has no network visibility or access keys for raw local inference engines or external APIs. It connects strictly to the LiteLLM proxy gateway (`http://proxy.local:4000/v1`).
  * **Control Plane Database Isolation (Rule 6):** LiteLLM is backed by a dedicated PostgreSQL container (`titan-litellm-db`) isolated on `titan-litellm-net`. Agents have zero database credentials, zero network routes, and zero storage mounts to this database.
  * **Memory Plane Purity (Rule 1):** Runtimes are ephemeral and disposable. Long-term knowledge is preserved in human-readable, flat-file Markdown using the Open Knowledge Format (OKF). Binary indices, SQLite databases, and packages are strictly forbidden in `/memories` and reside in `/workspace`.
  * **Manifest-Driven Multi-Agent Tenancy:** Fleet composition is declared centrally in `config/agents.yaml`. The reconciler (`scripts/sync-agents.sh`) renders compose topologies (`docker-compose.agents.yml`), Caddy virtual hosts (`config/caddy/agents.caddy`), seeds personas, and provisions virtual keys with budget caps.
  * **Decoupled Memory Module (`packages/titan_memory`):** Core memory logic, OKF models, purity validators, and a pluggable `VectorStore` abstract SPI are decoupled into a standalone package, allowing memory contributors to extend vector stores without stepping on agent runtime toes.
  * **Unified Persistent Storage & Cloud Backup:** All persistent state across the appliance lives under a single host data root (`./data` in development, or `/data/titan` on production GX10):
    * `memories/`: Human-auditable OKF Markdown notes partitioned per tenant (`tenants/<tenant_id>/`).
    * `litellm_db/`: LiteLLM PostgreSQL persistence (dynamic models, virtual keys, audit logs).
    * `workspace/`: Hermes agent runtime state, custom skills, Signal session credentials, tool configs, and caches partitioned per tenant (`<tenant_id>/`).
  * **Human-in-the-Loop Governance:** SilverBullet functions as the interactive debugging console across all tenant memory trees. Human operators audit, rollback, or modify live agent memory structures directly through a web browser.
  * **Immediate Software Kill-Switch:** Invalidating a single virtual key inside LiteLLM or running `./scripts/emergency-stop.sh <tenant_id>` severs inference streams and halts rogue agents instantly without impacting other agents or host state.

-----

## 2. Security & Operational Baselines

  * **Identity Pinning:** All container applications run bound to uniform user configurations (`PUID=1000`, `PGID=1000`) to guarantee write access and eliminate file ownership collisions across shared storage volumes.
  * **Host Sandboxing:** The agent container runtime completely drops elevated Linux capabilities (`cap_drop: [ALL]`, only retaining minimal network hooks) and strictly blocks exposure of the host Docker socket (`/var/run/docker.sock`).
  * **Hardware Serialization:** To safely manage model execution on the GB10 chip without thrashing the unified LPDDR5x memory bus (~273 GB/s peak bandwidth), LiteLLM serializes request scheduling via `max_parallel_requests: 1` or `2`.
  * **Host OS Protection:** Core NVIDIA stack dependencies (`linux-nvidia-hwe-24.04`, `nvidia-container-toolkit`) are held explicitly using `apt-mark hold` to isolate baseline configurations from breaking up-stream package modifications.
  * **Storage Path Conventions:**
    * **Development (macOS & standard clones):** Uses relative paths inside the repository root (`./data/memories`, `./data/workspace`, `./data/litellm_db`).
    * **Production Appliance (ASUS Ascent GX10):** Can optionally bind to dedicated NVMe mount paths (`/data/titan/memories`, `/data/titan/workspace`, `/data/titan/litellm_db`) configured via `.env`.

-----

## 3. Quickstart & Getting Started (Linux / DGX OS & macOS)

This guide provides the fastest path to bootstrap, run, and verify a complete Project Titan appliance on a standard Linux workstation (Ubuntu 24.04 LTS, DGX OS, or Debian-based distributions) or a macOS development environment.

### Prerequisites

| Component | Minimum Requirement | Recommended / Notes |
|---|---|---|
| **Operating System** | Ubuntu 24.04 LTS, DGX OS 6+ (ARM64), or macOS 14+ (Apple Silicon) | Debian 12+ x86_64 or ARM64 compatible |
| **Container Engine** | Docker Engine 24.0+ & Docker Compose v2 (`docker compose`) | User must be in `docker` group (`sudo usermod -aG docker $USER`) |
| **Host Tooling** | `bash` 4+, `curl`, `git`, `jq`, `python3` (3.10+), `python3-venv` | Handled automatically by `setup-host.sh` on Ubuntu/DGX OS |
| **Hardware / Memory** | 16 GB RAM minimum | Unified LPDDR5x (GX10 GB10) or Apple Silicon Unified Memory |
| **Inference Acceleration** | CPU fallback supported | NVIDIA CUDA 12+ & `nvidia-container-toolkit` for GPU acceleration |

> [!IMPORTANT]
> **Linux Docker Group Membership:** Ensure your non-root user can interact with the Docker daemon without `sudo`:
> ```bash
> sudo usermod -aG docker $USER && newgrp docker
> ```

---

### Step-by-Step Quickstart

#### 1. Clone the Repository & Configure Environment
```bash
git clone https://github.com/patternsatscale/project-titan.git
cd project-titan

# Copy baseline environment configuration
cp .env.example .env
```
*Review `.env` parameters if needed:*
- `TITAN_DATA_DIR`: Set to `./data/memories` (development) or `/data/titan/memories` (production GX10).
- `TITAN_WORKSPACE_DIR`: Set to `./data/workspace` (development) or `/data/titan/workspace` (production GX10).
- `PUID` and `PGID`: Set to `1000:1000` (default non-root user).

#### 2. Run Idempotent Host Baseline Setup
Execute the host setup script to audit system permissions, install host dependencies, initialize the native Ollama inference engine, configure Python virtual environments, and seed the default local model:
```bash
./scripts/setup-host.sh --pull-model
```
*Flags:*
- `--pull-model`: Automatically pulls and seeds the baseline model (e.g. `qwen2.5:7b-instruct-q4_K_M` or `hermes3:8b`). Omit if seeding manually.

#### 3. Initialize Memory Plane & Build Hermes Agent
Provision the pure Open Knowledge Format (OKF) storage directories and build the unprivileged Hermes Agent sandbox:
```bash
# Provision flat-file OKF directory tree (knowledge/, rules/, logs/)
./scripts/setup-memories.sh

# Build unprivileged Hermes container image with native hermes-okf plugin
./scripts/setup-hermes.sh
```

#### 4. Start Native Host Control Plane
Launch the host-side inference runtime (`ollama` on `127.0.0.1:11434`), LiteLLM proxy gateway (`:4000`), and initialize dynamic PostgreSQL persistence:
```bash
./scripts/start-control-plane.sh start
```
*Verify control plane status:*
```bash
./scripts/start-control-plane.sh status
```

#### 5. Launch Appliance Container Cluster
Start the containerized ingress gateway, database, PKM interface, messaging daemons, and Hermes agent sandbox via Docker Compose:
```bash
docker compose up -d
```
*Verify running containers:*
```bash
docker compose ps
```

#### 6. Configure Network & Local Domain Routing (`/etc/hosts`)
Route appliance domains to loopback (or your Linux machine's LAN IP) using the automated network script:
```bash
# Register *.titan.local domains non-interactively in /etc/hosts
sudo ./scripts/setup-network.sh --skip-ip -y
```
*Or manually append to `/etc/hosts`:*
```text
127.0.0.1 titan.local hermes.titan.local api.hermes.titan.local proxy.titan.local memory.titan.local
```
*(Note: If accessing this Linux appliance remotely from another machine on your LAN, replace `127.0.0.1` with the appliance's actual static LAN IP).*

#### 7. Run Automated Verification Tests
Validate complete end-to-end functionality, storage isolation, and agent persistence:
```bash
# Verify Hermes agent workspace persistence and LiteLLM mediation
./scripts/verify-hermes.sh

# Verify SilverBullet PKM UI and OKF memory plane synchronization
./scripts/verify-memories.sh
```

---

### Appliance Service Directory

Once running, the following endpoints are accessible via your browser:

| Endpoint | Ingress URL | Port | Default Credentials | Description |
|---|---|---|---|---|
| **Appliance Portal** | [http://titan.local](http://titan.local) | `80` / `443` | *None* | ASUS Ascent GX10 appliance dashboard & hub |
| **Hermes Web Dashboard** | [http://hermes.titan.local](http://hermes.titan.local) | `9119` | `admin` / `titan_admin_secret` | Hermes agent UI, channel manager, and tool config |
| **Hermes API Gateway** | [http://api.hermes.titan.local/v1](http://api.hermes.titan.local/v1) | `8642` | Bearer `${HERMES_LITELLM_KEY}` | OpenAI-compatible chat completions interface |
| **SilverBullet PKM UI** | [http://memory.titan.local](http://memory.titan.local) | `3000` | *None* | Human-in-the-loop OKF memory & rules inspector |
| **LiteLLM Gateway** | [http://proxy.titan.local](http://proxy.titan.local) | `4000` | Bearer `${LITELLM_MASTER_KEY}` | Hardware-serialized model routing & audit proxy |

---

### Common Operations & Lifecycle Management

```bash
# Check service status across host and containers
./scripts/start-control-plane.sh status
docker compose ps

# View container logs
docker compose logs -f caddy
docker compose logs -f hermes

# Gracefully restart the full appliance
docker compose restart
./scripts/start-control-plane.sh restart

# Gracefully shut down all services
docker compose down
./scripts/start-control-plane.sh stop

# Emergency kill-switch (instantly revokes agent key and freezes loops)
./scripts/emergency-stop.sh
```

-----

## 4. Repository Directory Structure

``` text
project-titan/  
├── README.md                 # System vision, architecture, and quickstart guide
├── AGENTS.md                 # Agent operating discipline, tickets, and safety rules
├── docker-compose.yml        # Declarative service topology and isolated networks (cluster: titan)
├── docker-compose.agents.yml # Auto-generated multi-agent fleet service units (sync-agents.sh)
├── .env.example              # Environment variables template (UID/GID, pathing, DB secrets)
├── config/  
│   ├── agents.yaml           # Declarative multi-agent fleet manifest (L1–L7 layer definitions)
│   ├── caddy/  
│   │   ├── Caddyfile         # Main ingress reverse proxy configuration (*.titan.local)
│   │   └── agents.caddy      # Auto-generated agent subdomain vhosts (sync-agents.sh)
│   ├── litellm/  
│   │   └── config.yaml       # Rate-limiting, model aliases, and database persistence settings
│   ├── hermes/  
│   │   ├── config.yaml       # Upstream Hermes Agent config (providers, channels, plugins)
│   │   ├── model_pool.json   # Autonomous coding model pool for weekly engine rotation (cindy-active-coding-model)
│   │   ├── SOUL.md           # Primary agent persona and behavioral directives
│   │   └── personas/         # Decoupled tenant personas (primary, football-dan, cindy-pawford)
│   └── memories/             # Version-controlled starter OKF templates (knowledge/, rules/, logs/)
├── apps/
│   └── cindypawford/
│       ├── archive/          # Immutable Digital Museum Vault (2024 Genesis era, sealed snapshots, eras.json)
│       ├── clean-slate/      # Master atelier starter templates (index.html, styles.css, app.js) seeded on reset
│       └── site/             # Cindy Pawford public HTML canvas (cloned CindyPawford-Online repo; mapped to /app/html)
├── packages/
│   └── titan_memory/         # Standalone OKF memory engine, purity guards, & VectorStore SPI
│       ├── pyproject.toml    # Standalone Python package definition (pip/uv installable)
│       ├── README.md         # Architecture & contributor guide for memory engine & vector stores
│       ├── titan_memory/     # Core OKF parser, models, purity validator, and tools registry
│       └── tests/            # Dedicated pytest suite (100% test coverage)
├── docker/
│   ├── hermes/
│   │   ├── Dockerfile        # Upstream Nous Research Hermes Agent container definition
│   │   └── plugins/
│   │       └── hermes-okf/   # Native Hermes OKF plugin package (plugin.yaml, okf.py, tools.py)
│   └── langfuse/
│       ├── docker-compose.yml# Decoupled Langfuse v2 + PostgreSQL observability stack
│       └── .env.example      # Standalone Langfuse environment template
├── docs/                     # Architectural tenets, specifications, and ticket walkthroughs
│   ├── reference-architecture-tenets.md  # Core security tenets and controls (TN-1 to TN-9)
│   └── YYYY-MM-DD-ticket*.md # Human-auditable ticket walkthroughs & test evidence
├── data/  
│   ├── memories/             # Live host volume storage for OKF Markdown files
│   │   └── agents/           # Partitioned agent memories (primary, football-dan, cindy-pawford)
│   ├── litellm_db/           # Dedicated LiteLLM PostgreSQL persistence storage (git-ignored)
│   ├── workspace/            # Partitioned agent tools, caches, and Signal/Telegram state (git-ignored)
│   │   ├── primary/          # Primary agent sandbox workspace
│   │   ├── football-dan/     # Football-dan agent sandbox workspace
│   │   ├── cindy-pawford/    # Cindy-pawford agent runtime sandbox
│   │   └── signal/           # signal-cli identity keys and daemon registration state
│   └── backups/              # Timestamped full-data and memory snapshots (git-ignored)
└── scripts/  
    ├── sync-agents.sh        # Fleet manifest orchestrator (renders compose, caddy, keys, & storage)
    ├── verify-fleet.sh       # Multi-agent fleet verification harness (drift, routing, isolation)
    ├── verify-cindy-agent.sh # Cindy Pawford agent unit verification suite (CW-0A)
    ├── verify-cindy-canvas.sh# Cindy Pawford canvas isolation verification suite (CW-0A.1)
    ├── verify-cindy-archive.sh# Genesis archive, digital museum & seal-and-reset suite (CW-0B)
    ├── build-archive-portal.py# Digital museum gallery compiler
    ├── process-cindy-reset.sh# Automated 'Seal & Reset' execution engine
    ├── republish-archives.sh # Out-of-band museum republishing tooling
    ├── setup-host.sh         # Idempotent baseline script for packages, Ollama, LiteLLM, and DB
    ├── setup-network.sh      # Static IP & local appliance domain (/etc/hosts) setup script
    ├── setup-hermes.sh       # Automated builder and validator for unprivileged Hermes container
    ├── setup-memories.sh     # Idempotent provisioning & scaffolding manager for memory plane
    ├── setup-langfuse.sh     # Standalone decoupled service manager for Langfuse container stack
    ├── verify-hermes.sh      # Automated verification harness for Hermes workspace persistence
    ├── verify-memories.sh    # Automated verification harness for SilverBullet & OKF sync
    ├── verify-langfuse.sh    # Automated verification harness for Langfuse & OpenTelemetry ingestion
    ├── start-control-plane.sh# Service manager for host Ollama inference, LiteLLM gateway, and titan-litellm-db
    ├── reload-env.sh         # Synchronizes database passwords and safely reloads all .env changes
    ├── backup.sh             # Full appliance data plane backup and restore manager
    ├── snapshot-memories.sh  # Automated versioning and rollback snapshot manager for memories
    └── emergency-stop.sh     # Granular key revocation & process freeze (targeted or full-fleet)
```

-----

## 5. Phased Engineering Roadmap

Project Titan follows a strict, step-by-step implementation discipline to prevent unvalidated configuration sprawl.

``` marp
Phase 0: Base Config
  └── Phase 1: Control Plane
        └── Phase 2: Hermes Agent
              └── Phase 3: Memory Mgmt
                    └── Phase 4: Security
                          └── Phase 5: Benchmarking

```

### Phase 0: Base Config (Host OS & Ingress Baseline)

  * Execute package pinning (`apt-mark hold`) across hardware drivers and runtime toolkits on DGX OS.
  * Configure local directory layouts under `/data/titan/memories` and seed environment schemas.
  * Deploy the reverse proxy container (Caddy/Traefik) running inside an isolated Docker bridge network.
  * *Exit Criteria:* Validated local network routing across `hermes.titan.local` and `proxy.titan.local` endpoints to mockup responses.

### Phase 1: Control Plane (Inference & LiteLLM Gateway)

  * Provision native local inference runtimes (Ollama/vLLM) on the host system to maximize hardware acceleration (Metal on macOS, CUDA on GB10 / DGX OS) bound strictly to loopback (`127.0.0.1:11434`).
  * Deploy native LiteLLM proxy gateway on the host (`:4000`) backed by a dedicated, isolated PostgreSQL service (`titan-litellm-db`) with `store_model_in_db: true` for dynamic model and key persistence.
  * Enforce hardware-aware request queuing (`max_parallel_requests: 1`) and initialize virtual proxy keys (`HERMES_LITELLM_KEY`).
  * *Exit Criteria:* Local models are queried successfully via authenticated proxy paths; dynamic model and key mutations persist across process restarts; all direct access routes to raw inference and database ports are bound strictly to localhost loopback.

### Phase 2: Hermes Agent (Upstream Runtime, Web Dashboard & Messaging Gateways)

  * Deploy the unprivileged upstream Nous Research Hermes Agent sandbox container (`titan-hermes`) built via `docker/hermes/Dockerfile` with dropped privileges (`no-new-privileges:true`, UID 1000) and native s6 supervision.
  * Enforce outbound internet egress on `titan-internal` while strictly eliminating the host Docker socket (`/var/run/docker.sock`) and isolating the control plane database (`titan-litellm-db`).
  * Route outbound agent queries strictly to `http://proxy.local:4000/v1` authenticated via virtual proxy key, isolating host infrastructure names from agent context (Rule 7).
  * Deploy a companion `signal-cli` daemon service on `titan-internal` persisting registration state in `/workspace/signal`.
  * Expose the native Hermes Web Dashboard via Caddy reverse proxy at `hermes.titan.local` (port `9119`) and gateway API at `api.hermes.titan.local` (port `8642`).
  * *Exit Criteria:* Hermes processing loops and dashboard are operational; Web Dashboard allows visual configuration of Signal and Telegram channels; tools and workspace state persist strictly in `/workspace` with zero memory pollution.

### Phase 3: Memory Mgmt (Flat-File OKF & PKM Interface)

  * Establish host storage mappings to `${TITAN_DATA_DIR}` (`/data/titan/memories` on GX10, `./data/memories` on macOS) using unified permission access keys (`1000:1000`).
  * Deploy the SilverBullet visual inspection workspace container mounting the same storage directory, accessible via Caddy at `memory.titan.local`.
  * Deploy the native `hermes-okf` plugin package (`docker/hermes/plugins/hermes-okf`) registering `read_okf_note`, `write_okf_note`, and `synthesize_active_rules` into Hermes Agent's tool registry.
  * Implement budget-aware dynamic rule injection and working memory scratchpad loading into Hermes reasoning loops.
  * Enforce hardware-adaptive context windows: safe 4,096 tokens on 16GB macOS workstations and 32,768 tokens on ASUS Ascent GX10 appliances.
  * *Exit Criteria:* Bi-directional persistence and synchronization verified—content modifications applied inside SilverBullet propagate to active agent reasoning streams; memory purity audit asserts strictly human-auditable flat-file Markdown.

### Phase 4: Security (Hardening & Operational Readiness)

  * Configure automated cron scheduling for hourly host-side snapshots or localized Git tracking across the memory mount.
  * Enforce absolute network separation to guarantee the hardware appliance is unreachable from enterprise or corporate nodes.
  * Execute recovery test validations: simulate a runaway agent processing thread, apply immediate key revocation via `emergency-stop.sh`, and verify graceful degradation without impacting host states.
  * *Exit Criteria:* Deterministic cluster reconstruction from bare config parameters via `docker compose down && docker compose up -d` with complete retention of memory trees.

### Phase 5: Benchmarking (Evaluation, Optimization & Observability)

  * Benchmark Ollama vs. vLLM vs. SGLang on native ARM64 / DGX OS to evaluate prefill speed and KV-cache memory pressure.
  * Measure context scaling performance across 4k, 8k, 16k, 32k, and 64k token windows.
  * **Langfuse Observability & OpenTelemetry Tracing (#19)**:
    * **Decoupled Architecture**: Langfuse v2 container stack (`docker/langfuse/docker-compose.yml`) is completely decoupled from the main Titan appliance cluster, allowing it to run on a separate developer laptop or workstation over the LAN.
    * **No Auto-Start by Default**: Controlled via `LANGFUSE_AUTO_START=false` in `.env`. The GX10 appliance runs all core planes (Inference, Control, Agent, Memory) without auto-starting Langfuse.
    * **Standardized DNS & Dedicated Port**: Tracing endpoints target `langfuse.titan.local` on dedicated **port 3001** (eliminating conflict with SilverBullet on port 3000), mapped via `/etc/hosts` or Docker `extra_hosts` to the remote workstation IP (`LANGFUSE_HOST_IP`).
    * **Dual Ingestion**:
      * **LiteLLM Gateway**: Native tracing callback (`langfuse`) and OpenTelemetry exporter capturing request metadata, token counts, model aliases, and latency.
      * **Hermes Agent**: Direct OTLP trace export via `http://langfuse.titan.local:3001/api/public/otel/v1/traces`.
    * **Standalone Lifecycle Management**:
      * Setup & start: `./scripts/setup-langfuse.sh setup && ./scripts/setup-langfuse.sh start`
      * Service status & logs: `./scripts/setup-langfuse.sh status` / `./scripts/setup-langfuse.sh logs`
      * Key helper: `./scripts/setup-langfuse.sh keys` (prompts for keys and generates Base64 `LANGFUSE_OTEL_AUTH`)
      * Verification: `./scripts/verify-langfuse.sh`
  * *Exit Criteria:* Quantifiable benchmark report and automated profiling harness across memory bandwidth and agent execution latencies; dual OTel/LiteLLM trace ingestion validated.

---

## 6. Lab work: Hermes Multi-Agent Demonstrations & Hardening

Real-world agent operational testing across multi-tenancy, calibration, safety circuit breakers, and adversarial resilience.

### Shared Tenancy Foundation
- **Sprint 0 (#28)**: Shared multi-tenancy foundation (`football-dan` & `cindy-pawford`), memory/workspace partitioning, policy-plane behavioral budgets, append-only action log with agent versioning, out-of-band halt script, and canary seeding.

### Epic A: Football Dan (Probabilistic Reasoning & Financial Invariants)
- **FD-1 (#29)**: Read-only Telegram researcher, strict OKF provenance schema enforcement, frozen KPI baseline, benign injection marker suite.
- **FD-2 (#30)**: Calibrated advice with mandatory stated probability, automated weekly resolution job against real-world game outcomes, Brier score computation.
- **FD-3 (#31)**: Memory plane under localized Git versioning, volatility-aware retrieval, automated staleness sweep, duplicate detection/deletion, contributor reliability scoring.
- **FD-4 (#32)**: Isolated paper wagering ledger with reserve-then-commit semantics, hard financial invariants, open positions as committed capital, programmatic invariant fuzzing harness.
- **FD-5 (#33)**: Irreversible-action classification, external gate outside agent runtime, Telegram approval flow with timeout-to-deny, bypass attempt alerting.
- **FD-6 (#34)**: Whisper STT ingress with mandatory transcript retention in action log, Kokoro TTS response path with post-transcription text guardrails.
- **FD-7 (#35)**: Automated season report export from action log & KPI harness, memory archival to cold storage, clean tenant teardown & Season 2 carry-forward review.

### Epic B: Cindy Pawford (Staged Publishing & Autonomous Breakers)
- **CW-1 (#36)**: Content generation restricted strictly to staging storage prefix, scoped least-privilege credentials (`PutObject`), bucket versioning/rollback tooling, operator promotion CLI.
- **CW-2 (#37)**: Automated promotion guarded by deterministic circuit breakers (out-of-prefix writes, rate ceilings, diff anomalies, policy modification attempts) with graduated response (freeze -> suspend -> halt).
- **CW-3 (#38)**: Untrusted web page ingestion via tool-less reader sandbox (`TN-1.8`), comic/image generation into staging, indirect prompt injection test suite.
- **CW-4 (#39)**: Semantic safety circuit breakers: embedding drift baseline, real-person assertion detector, content policy classifier, calibrated false-positive arming gate.
- **CW-5 (#40)**: Self-hosted social arena (Mastodon), labeled agent identity, bidirectional cross-agent injection testing, memory pollution defense with provenance tracking.
- **CW-6 (#41)**: Explicit numerical traffic objective, strict tactic allowlist with breaker trip on violation, reward-hacking observation harness capturing agent rationalizations verbatim.

### Cross-Cutting Security & Telemetry
- **X-1 (#42)**: Outbound policy inspection at LiteLLM scanning consultation payloads for seeded tenant canary tokens (`TN-6`).
- **X-2 (#43)**: Isolated sandbox CloudTrail -> EventBridge -> SNS canary alerting infrastructure.
- **X-3 (#44)**: Adversarial "nosy neighbour" agent harness attempting cross-tenant penetration of memory, workspace, tools, and credentials.
- **X-4 (#45)**: Appliance power draw and thermal telemetry correlation logging against Heating Degree Days (HDD).


