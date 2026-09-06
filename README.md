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
                     (Caddy / Traefik Gateway)  
                                  │  
    ┌─────────────────────────────┼─────────────────────────────┐  
    │ :8642                       │ :4000                       │ :3000  
    ▼                             ▼                             ▼  
┌──────────────┐          ┌──────────────┐              ┌──────────────┐  
│ Hermes Agent │──(LLM)──►│   LiteLLM    │              │ SilverBullet │  
│ (Ephemeral)  │          │   Control    │              │  Memory UI   │  
└──────┬───────┘          └──────┬───────┘              └──────┬───────┘  
       │ (Writes)                │ (Inference)                 │ (Reads/Writes)  
       │                         ▼                             │  
       │                  ┌──────────────┐                     │  
       │                  │ Inference Eng│                     │  
       │                  │ (vLLM/Ollama)│                     │  
       │                  └──────────────┘                     │  
       │                                                       │  
       └─────────────────────────┬─────────────────────────────┘  
                                 ▼  
                     [ Host Storage Bind-Mount ]  
                     /data/titan/memories (OKF)   
```

### Core Architecture Rules

  * **Zero Direct Connect:** The agent layer has no network visibility or access keys for raw local inference engines or external APIs. It connects strictly to the LiteLLM proxy gateway.
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
├── docker-compose.yml        # Declarative service topology and isolated networks
├── .env.example              # Environment variables template (UID/GID, pathing)
├── config/  
│   ├── caddy/  
│   │   └── Caddyfile         # Reverse proxy virtual hosts mapping *.titan.local
│   ├── litellm/  
│   │   └── config.yaml       # Rate-limiting, model aliases, and concurrency rules
│   └── hermes/  
│       └── config.json       # Agent execution profiles and OKF settings
├── data/  
│   └── memories/             # Live host volume storage for OKF Markdown files (git-ignored)
└── scripts/  
    ├── setup-host.sh         # Idempotent baseline script for package locks and permissions
    ├── snapshot-memories.sh  # Automated versioning and rollback snapshot manager
    └── emergency-stop.sh     # Key revocation script for immediate loop intervention

```

-----

## 4\. Phased Engineering Roadmap

Project Titan follows a strict, step-by-step implementation discipline to prevent unvalidated configuration sprawl.

``` marp
Phase 0: Host OS & Ingress Baseline
  └── Phase 1: Control Plane & Throttling
        └── Phase 2: Isolated Agent Execution
              └── Phase 3: OKF Memory & SilverBullet Integration
                    └── Phase 4: System Hardening & Validation

```

### Phase 0: Host OS Ingress & Hardware Baseline

  * Execute package pinning (`apt-mark hold`) across hardware drivers and runtime toolkits on DGX OS.
  * Configure local directory layouts under `/data/titan/memories` and seed environment schemas.
  * Deploy the reverse proxy container (Caddy/Traefik) running inside an isolated Docker bridge network.
  * *Exit Criteria:* Validated local network routing across `hermes.titan.local` and `proxy.titan.local` endpoints to mockup responses.

### Phase 1: Control Plane (Inference & LiteLLM Gateway)

  * Provision local inference runtimes (vLLM or Ollama) matched to ARM64 architectural structures.
  * Deploy LiteLLM proxy container between the local hardware engine and consumer targets.
  * Enforce hardware-aware request queuing and initialize virtual proxy keys.
  * *Exit Criteria:* Local models are queried successfully via authenticated proxy paths; all direct access routes to raw inference ports are firewalled.

### Phase 2: Agent Plane (Isolated Hermes Deployment)

  * Deploy the Hermes Agent runtime within an isolated container mapping dropped Linux system capabilities.
  * Bind outbound agent model configurations exclusively to the internal LiteLLM proxy destination using virtual authentication headers.
  * Map the web interface to the proxy layer for external view resolution via `hermes.titan.local`.
  * *Exit Criteria:* Agent processing loops execute and log traces inside LiteLLM while running entirely in a non-root environment.

### Phase 3: Memory Plane (Flat-File OKF & PKM Interface)

  * Establish host storage mappings to `/data/titan/memories` using unified permission access keys (`1000:1000`).
  * Deploy the SilverBullet visual inspection workspace container mounting the same storage directory.
  * Initialize the `hermes-okf` plugin structure to track knowledge maps, rulesets, and logs as standard markdown documents.
  * *Exit Criteria:* Bi-directional persistence is verified—content modifications applied inside SilverBullet propagate to active agent reasoning streams.

### Phase 4: System Hardening & Operational Readiness

  * Configure automated cron scheduling for hourly host-side snapshots or localized Git tracking across the memory mount.
  * Enforce absolute network separation to guarantee the hardware appliance is unreachable from enterprise or corporate nodes.
  * Execute recovery test validations: simulate a runaway agent processing thread, apply immediate key revocation via `emergency-stop.sh`, and verify graceful degradation without impacting host states.
  * *Exit Criteria:* Deterministic cluster reconstruction from bare config parameters via `docker compose down && docker compose up -d` with complete retention of memory trees.
