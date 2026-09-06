# Project Titan: Autonomous Agent Workspace Specification

This repository contains the complete infrastructure, configuration manifests, and orchestration scripts for **Project Titan**—an isolated, secure, and human-auditable autonomous AI agent appliance built on an **ASUS Ascent GX10** running DGX OS (Ubuntu 24.04 ARM64).

The system architecture enforces an absolute boundary between execution runtimes, routing paths, and memory states to ensure zero-trust operations within local infrastructure.

-----

## 1\. System Topology & Philosophy

Project Titan transforms a dedicated bare-metal system into a transactional black box. Rather than running unverified Python loops or local AI tooling directly on the host operating system, the entire application stack is containerized, isolated, and governed by strict plane separation:

``` text
                     [ Local / Tunneler Ingress ]  
                                  │  
          ┌───────────────────────┼───────────────────────┐  
          ▼                       ▼                       ▼  
  hermes.titan.local      proxy.titan.local       memory.titan.local  
          │                       │                       │  
          └───────────────────────┼───────────────────────┘  
                                  ▼  
                     [ Ingress Reverse Proxy ]  
                     (titan-caddy Gateway)  
                                  │  
    ┌─────────────────────────────┼─────────────────────────────┐  
    │ :8642                       │ :4000                       │ :3000  
    ▼                             ▼                             ▼  
┌──────────────┐          ┌──────────────┐              ┌──────────────┐  
│ Hermes Agent │──(LLM)──►│   LiteLLM    │              │ SilverBullet │  
│ (Ephemeral)  │          │   Control    │              │  Memory UI   │  
└──────┬───────┘          └──────┬───┬───┘              └──────┬───────┘  
       │ (Writes)                │   │ (Persistence)           │ (Reads/Writes)  
       │             (Inference) │   ▼                         │  
       │                         │ ┌──────────────────┐        │  
       │                         │ │ titan-litellm-db │        │  
       │                         │ │  (PostgreSQL 16) │        │  
       │                         │ └────────┬─────────┘        │  
       │                         ▼          │                  │  
       │                  ┌──────────────┐  │                  │  
       │                  │ Inference Eng│  │                  │  
       │                  │ (vLLM/Ollama)│  │                  │  
       │                  └──────────────┘  │                  │  
       │                                    │                  │  
       └─────────────────────────┬──────────┼──────────────────┘  
                                 ▼          ▼  
                      [ Host Storage Bind-Mounts ]  
                      /data/titan/memories (OKF)   
                      /data/titan/litellm_db (PostgreSQL)
```

### Core Architecture Rules

  * **Zero Direct Connect:** The agent layer has no network visibility or access keys for raw local inference engines or external APIs. It connects strictly to the LiteLLM proxy gateway.
  * **Control Plane Database Isolation:** LiteLLM is backed by a dedicated PostgreSQL container (`titan-litellm-db`) isolated on `titan-litellm-net`. Hermes has zero database credentials, zero network route, and zero storage volume visibility to this database.
  * **Decoupled Memory Plane:** Runtimes are ephemeral and disposable. Long-term knowledge is preserved in human-readable, flat-file Markdown using the Open Knowledge Format (OKF) on a persistent host mount.
  * **Human-in-the-Loop Governance:** SilverBullet functions as the interactive debugging console. Human operators audit, rollback, or modify live agent memory structures directly through a web browser.
  * **Immediate Software Kill-Switch:** Invalidating a single virtual key inside LiteLLM severs inference streams instantly, stopping rogue agent loops without impacting host system states.

-----

## 2\. Security & Operational Baselines

  * **Identity Pinning:** All container applications run bound to uniform user configurations (`PUID=1000`, `PGID=1000`) to guarantee write access and eliminate file ownership collisions across shared storage volumes.
  * **Host Sandboxing:** The agent container runtime completely drops elevated Linux capabilities (`cap_drop: [ALL]`, only retaining minimal network hooks) and strictly blocks exposure of the host Docker socket (`/var/run/docker.sock`).
  * **Hardware Serialization:** To safely manage model execution on the GB10 chip without thrashing the unified LPDDR5x memory bus (\~273 GB/s peak bandwidth), LiteLLM serializes request scheduling via `max_parallel_requests: 1` or `2`.
  * **Host OS Protection:** Core NVIDIA stack dependencies (`linux-nvidia-hwe-24.04`, `nvidia-container-toolkit`) are held explicitly using `apt-mark hold` to isolate baseline configurations from breaking up-stream package modifications.

-----

## 3\. Repository Directory Structure

``` text
project-titan/  
├── README.md                 # System vision and development roadmap
├── docker-compose.yml        # Declarative service topology and isolated networks (cluster: titan)
├── .env.example              # Environment variables template (UID/GID, pathing, DB secrets)
├── config/  
│   ├── caddy/  
│   │   └── Caddyfile         # Reverse proxy virtual hosts mapping *.titan.local
│   ├── litellm/  
│   │   └── config.yaml       # Rate-limiting, model aliases, and database persistence settings
│   ├── hermes/  
│   │   ├── config.json       # Agent execution profiles, skills path, and OKF settings
│   │   └── SOUL.md           # Agent persona and behavioral directives
│   └── memories/             # Version-controlled starter OKF templates (knowledge/, rules/, logs/)
├── docker/
│   └── hermes/
│       ├── Dockerfile        # Unprivileged multi-arch agent container definition
│       ├── hermes_okf.py     # Standalone OKF memory manager, rule injector & CLI skill runner
│       └── server.py         # Lightweight Hermes web console, OKF explorer & sandboxed runner
├── data/  
│   ├── memories/             # Live host volume storage for OKF Markdown files
│   └── litellm_db/           # Dedicated LiteLLM PostgreSQL persistence storage (git-ignored)
└── scripts/  
    ├── setup-host.sh         # Idempotent baseline script for packages, Ollama, LiteLLM, and DB
    ├── setup-hermes.sh       # Automated builder and validator for unprivileged Hermes container
    ├── setup-memories.sh     # Idempotent provisioning & scaffolding manager for memory plane
    ├── verify-memories.sh    # Automated verification harness for SilverBullet & OKF sync
    ├── start-control-plane.sh# Service manager for host Ollama inference, LiteLLM gateway, and titan-litellm-db
    ├── snapshot-memories.sh  # Automated versioning and rollback snapshot manager
    └── emergency-stop.sh     # Key revocation script for immediate loop intervention
```

-----

## 4. Phased Engineering Roadmap

Project Titan follows a strict, step-by-step implementation discipline to prevent unvalidated configuration sprawl.

``` marp
Phase 0: Host OS & Ingress Baseline
  └── Phase 1: Control Plane & Throttling
        └── Phase 2: Isolated Agent Execution
              └── Phase 3: OKF Memory & SilverBullet Integration
                    └── Phase 4: System Hardening & Validation
                          └── Phase 5: Benchmarking & Optimization

```

### Phase 0: Host OS Ingress & Hardware Baseline

  * Execute package pinning (`apt-mark hold`) across hardware drivers and runtime toolkits on DGX OS.
  * Configure local directory layouts under `/data/titan/memories` and seed environment schemas.
  * Deploy the reverse proxy container (Caddy/Traefik) running inside an isolated Docker bridge network.
  * *Exit Criteria:* Validated local network routing across `hermes.titan.local` and `proxy.titan.local` endpoints to mockup responses.

### Phase 1: Control Plane (Inference & LiteLLM Gateway)

  * Provision native local inference runtimes (Ollama/vLLM) on the host system to maximize hardware acceleration (Metal on macOS, CUDA on GB10 / DGX OS) bound strictly to loopback (`127.0.0.1:11434`).
  * Deploy native LiteLLM proxy gateway on the host (`:4000`) backed by a dedicated, isolated PostgreSQL service (`titan-litellm-db`) with `store_model_in_db: true` for dynamic model and key persistence.
  * Enforce hardware-aware request queuing (`max_parallel_requests: 1`) and initialize virtual proxy keys (`HERMES_LITELLM_KEY`).
  * *Exit Criteria:* Local models are queried successfully via authenticated proxy paths; dynamic model and key mutations persist across process restarts; all direct access routes to raw inference and database ports are bound strictly to localhost loopback.

### Phase 2: Agent Plane (Isolated Hermes Deployment)

  * Deploy the unprivileged Hermes Agent sandbox container (`titan-hermes`) built via `docker/hermes/Dockerfile` with dropped capabilities (`no-new-privileges:true`) and non-root execution (UID 1000).
  * Enforce outbound internet egress on `titan-internal` while strictly eliminating the host Docker socket (`/var/run/docker.sock`) and isolating the control plane database (`titan-litellm-db`).
  * Route outbound agent queries strictly to `http://litellm:4000/v1` authenticated via `HERMES_LITELLM_KEY`.
  * Expose the Hermes interaction console, skills manager, and reasoning interface via Caddy reverse proxy at `hermes.titan.local`.
  * *Exit Criteria:* Hermes processing loops execute and log traces inside LiteLLM while running entirely in a non-root environment; interactive web console and sandboxed tool execution in `/workspace` are fully operational.

### Phase 3: Memory Plane (Flat-File OKF & PKM Interface)

  * Establish host storage mappings to `${TITAN_DATA_DIR}` (`/data/titan/memories` on GX10, `./data/memories` on macOS) using unified permission access keys (`1000:1000`).
  * Deploy the SilverBullet visual inspection workspace container mounting the same storage directory, accessible via Caddy at `memory.titan.local`.
  * Deploy the `hermes-okf` plugin and CLI tool (`docker/hermes/hermes_okf.py`) to manage `/memories/knowledge`, `/memories/rules`, and `/memories/logs`.
  * Implement budget-aware dynamic rule injection and working memory scratchpad loading into Hermes reasoning loops.
  * Enforce hardware-adaptive context windows: safe 4,096 tokens on 16GB macOS workstations and 32,768 tokens on ASUS Ascent GX10 appliances.
  * *Exit Criteria:* Bi-directional persistence and synchronization verified—content modifications applied inside SilverBullet propagate to active agent reasoning streams; memory purity audit asserts strictly human-auditable flat-file Markdown.

### Phase 4: System Hardening & Operational Readiness

  * Configure automated cron scheduling for hourly host-side snapshots or localized Git tracking across the memory mount.
  * Enforce absolute network separation to guarantee the hardware appliance is unreachable from enterprise or corporate nodes.
  * Execute recovery test validations: simulate a runaway agent processing thread, apply immediate key revocation via `emergency-stop.sh`, and verify graceful degradation without impacting host states.
  * *Exit Criteria:* Deterministic cluster reconstruction from bare config parameters via `docker compose down && docker compose up -d` with complete retention of memory trees.

### Phase 5: Benchmarking, Optimization & Observability

  * Benchmark Ollama vs. vLLM vs. SGLang on native ARM64 / DGX OS to evaluate prefill speed and KV-cache memory pressure.
  * Measure context scaling performance across 4k, 8k, 16k, 32k, and 64k token windows.
  * Integrate LLM tracing and observability (Langfuse) into LiteLLM control plane gateway.
  * *Exit Criteria:* Quantifiable benchmark report and automated profiling harness across memory bandwidth and agent execution latencies.

