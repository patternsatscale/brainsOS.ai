# brainsOS: Open-Source Edge Agent Operating System & Governance Runtime

[![Project Status: Active Alpha](https://img.shields.io/badge/Status-Active_Alpha-orange.svg)](https://brainsos.ai)
[![COHUMAIN ACSG: Target Architecture](https://img.shields.io/badge/COHUMAIN_ACSG-Target_Architecture-blue.svg)](docs/cohumain/README.md)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![Architecture: ARM64 Native](https://img.shields.io/badge/Architecture-ARM64_Native-purple.svg)](#prerequisites)

> **Website**: [brainsOS.ai](https://brainsos.ai) • **Initiative**: [Patterns at Scale](https://patternsatscale.com) • **Governance Standard**: [COHUMAIN ACSG](docs/cohumain/CONTROLS.md)

**brainsOS** is the open-source bare-metal operating system and governance runtime for the **Balanced Reasoning & Agent Inference Node System (BRAINS)**. It bridges local autonomous AI agents directly to physical hardware telemetry, deterministic safety circuit breakers, virtual token quotas, and asynchronous queue management.

Governed by physics. Accountable down to the millijoule.

---

> [!NOTE]
> ### 🚧 Project Status: Active Development (Alpha)
> **brainsOS is an active open-source engineering project under rapid alpha development.**
> 
> The **COHUMAIN Agentic Cybersecurity Governance (ACSG)** controls catalog included in this repository represents our **architectural North Star and aspirational conformance roadmap**. While foundational baseline controls (deterministic kill switches, least-privilege host sandboxing, and memory purity) are operational today, full conformance across all 25 controls is an ongoing, phased engineering effort. We publish our complete architecture, source code, and control mappings in the open to build transparently and invite community collaboration.

---

## 1. The Problem: Cloud AI Ignores Physics

Modern artificial intelligence largely operates on the premise that power is infinite, cloud compute is limitless, and execution is synchronous. Today, gigawatts are poured into unconstrained reasoning loops, offloading physical burdens—grid instability, carbon emissions, and unmanaged heat—onto the surrounding world. When an autonomous agent enters a divergent tool loop, it burns cash, spikes processor draw, and pushes real-world costs onto local infrastructure uninterrupted.

**Software token counters cannot protect your hardware.** Autonomous local intelligence needs bare-metal operational boundaries.

### The Patterns at Scale Philosophy
Rooted in the *Patterns at Scale Manifesto*, brainsOS enforces a new computing paradigm:

* **Computation Must Learn to Breathe with the Grid**: Scaling up when energy generation and ambient conditions afford it, scaling down when physical constraints demand it.
* **Energy Quotas Rather than Just Token Budgets**: Tying execution limits directly to battery reserves, solar generation curves, and ambient thermal saturation.
* **Accounting for Every Watt Down to the Millijoule**: Moving beyond theoretical model parameter counts to measure total thermodynamic cost per completed task.
* **Living with System Heat**: Treating compute as a responsive micro-utility, recycling thermal exhaust when possible, and curbing demands when the environment requires it.

---

## 2. Core Architectural Capabilities

```
┌────────────────────────────────────────────────────────┐
│                PROJECT MILLIJOULE (mJ)                 │
│    The Overarching Mission & Thermodynamic Research    │
│ (Solar orchestration, thermal sinks, waste heat reuse) │
├────────────────────────────────────────────────────────┤
│                         BRAINS                         │
│    Balanced Reasoning & Agent Inference Node System    │
│ (brainsOS.ai: ACSG governance runtime & kill switches) │
├────────────────────────────────────────────────────────┤
│                 PHYSICAL & SENSORY LAYER               │
│  Heterogeneous Hardware • Microgrid Bus • Sensors      │
└────────────────────────────────────────────────────────┘
```

### 1. Asynchronous Message & Queue Execution
Replaces unpredictable synchronous agent loops with a decoupled queuing harness (`packages/brainsOS-queue`). Reasoning steps, tool executions, and multi-agent communications flow through strict asynchronous message brokers, enforcing backpressure, concurrency limits, and energy-aware job scheduling.

### 2. Deterministic Safety Circuit Breakers & Kill Switches
Translates ACSG agent safety into hard physical boundaries. If an autonomous agent diverges or enters an unconstrained loop, brainsOS drains or drops queue workers, cutting execution deterministically via `./scripts/control/emergency-stop.sh` or virtual key invalidation before battery reserves collapse or silicon reaches thermal limits.

### 3. Least-Privilege Host Sandboxing
Enforces strict boundary isolation on bare-metal silicon. Agent runtimes drop elevated Linux capabilities (`cap_drop: [ALL]`), operate under non-root identities (`PUID=1000`, `PGID=1000`), and strictly block exposure of the host Docker socket (`/var/run/docker.sock`).

### 4. Memory Plane Purity (Open Knowledge Format)
Runtimes are ephemeral and disposable. Long-term agent knowledge is preserved exclusively in human-auditable flat-file Markdown notes using the Open Knowledge Format (OKF) via `packages/brainsOS-memory`. Binary indices, SQLite databases, and packages are strictly forbidden in `/memories` and reside in `/workspace`.

### 5. Dynamic Capabilities MCP Server (Zero Native Tool Injection)
Exposes agent tools across all domain packages dynamically via the Model Context Protocol (FastMCP) over `stdio` (`packages/brainsOS-mcp`). Eliminates prompt bloat and KV cache exhaustion on unified memory architectures by avoiding direct injection of custom tool definitions into native Hermes system prompts.

---

## 3. Out-of-the-Box Governance Stack

brainsOS unifies established enterprise-grade open-source components into a cohesive local governance and inspection plane:

| Component | Role in brainsOS Harness | Governance Boundary |
|---|---|---|
| **[LiteLLM](https://github.com/BerriAI/litellm)** | Local token governance, virtual quotas, model routing, and fallback pathways | Serializes requests (`max_parallel_requests: 1`) to protect unified LPDDR5x memory buses from bandwidth thrashing. |
| **[Langfuse](https://langfuse.com)** | Step-by-step local tracing of asynchronous agent trajectories and tool spans | Full OpenTelemetry observability into reasoning steps, token latency, and error states. |
| **[mitmproxy](https://mitmproxy.org) & [Caddy](https://caddyserver.com)** | Ingress/egress firewalls and boundary inspection proxies | Intercepts outbound HTTP/HTTPS calls, redacts secrets from flow logs, and terminates unauthorized external connections. |
| **In-Transit Egress Proxy** | Multi-tenant in-transit credential injection | Containers hold **zero ambient secrets** or GitHub tokens; credentials are dynamically injected in transit by proxy based on client container IP. |
| **[Postfix](https://www.postfix.org) & [SOGo](https://sogo.nu)** | Decoupled, auditable messaging backbone | Asynchronous agent-to-human and agent-to-agent email communication, avoiding fragile polling loops. |
| **Operator IDE ([code-server](https://github.com/coder/code-server))** | Controlled operator workspace and inspection console | Sandboxed environment for inspecting artifacts, memories, and workspace state behind HTTP Basic Auth. |

---

## 4. The BRAINS Reference Architecture (L1–L7 Model)

```mermaid
graph TD
    classDef l7 fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#fff;
    classDef l6 fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef l5 fill:#14532d,stroke:#4ade80,stroke-width:2px,color:#fff;
    classDef l4 fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#fff;
    classDef l3 fill:#7c2d12,stroke:#fb923c,stroke-width:2px,color:#fff;
    classDef l2 fill:#334155,stroke:#94a3b8,stroke-width:2px,color:#fff;
    classDef l1 fill:#18181b,stroke:#a1a1aa,stroke-width:2px,color:#fff;

    subgraph "L7: Communications, Ingress & Operator Console"
        CADDY["Caddy Reverse Proxy<br/>(*.brainsos.local :80/:443)"]:::l7
        EDITOR["Operator IDE & Console<br/>(editor.brainsos.local :8443)"]:::l7
        SOGO["SOGo / Postfix<br/>(mail.brainsos.local :20000)"]:::l7
    end

    subgraph "L6: Autonomous Agent Fleet Units (data/agent_apps/ & config/default_settings/agents.yaml)"
        CINDY["Cindy Pawford<br/>(site/ & pipeline/ :9122)"]:::l6
        TERRA["Terra Stella Operations<br/>(:8642 / :9119)"]:::l6
        MARVIN["Marvin Sports Analytics<br/>(:8643 / :9120)"]:::l6
    end

    subgraph "L5: Memory Plane & Tool Sandboxing"
        MEM["OKF Memory Engine<br/>(/memories - pure Markdown)"]:::l5
        QUEUE["Async WorkQueue & Worker<br/>(packages/brainsOS-queue)"]:::l5
        TEL["Telemetry Bus & mJ Calc<br/>(packages/brainsOS-telemetry)"]:::l5
        MCP["FastMCP Tool Server<br/>(packages/brainsOS-mcp)"]:::l5
    end

    subgraph "L4: Routing, Security & Control Plane"
        LITELLM["LiteLLM Gateway (:4000)<br/>(Virtual Keys & Spend Limits)"]:::l4
        MITM["Tool Egress Gateway (:8082)<br/>(In-Transit Credential Injection)"]:::l4
        DB["Control DB (:5432)<br/>(PostgreSQL - Isolated)"]:::l4
    end

    subgraph "L3: Host Inference Plane (Loopback Bound)"
        OLLAMA["Host Ollama / vLLM<br/>(127.0.0.1:11434)"]:::l3
    end

    subgraph "L2: Virtualization & Isolated Bridge Networks"
        NET_INGRESS["brainsos-ingress"]:::l2
        NET_INTERNAL["brainsos-internal"]:::l2
        NET_LITELLM["brainsos-litellm-net"]:::l2
    end

    subgraph "L1: Physical & Hardware Layer"
        HW["ASUS Ascent GX10 (NVIDIA GB10) / Apple Silicon<br/>Unified Memory Bus • Hardware Serializer"]:::l1
    end

    CADDY -->|routes to| CINDY
    CADDY -->|routes to| TERRA
    CADDY -->|routes to| MARVIN
    CADDY -->|routes to| EDITOR
    CADDY -->|routes to| SOGO

    CINDY -->|executes via| QUEUE
    QUEUE -->|emits mJ telemetry| TEL
    CINDY -->|loads notes from| MEM
    CINDY -->|LLM completions| LITELLM
    CINDY -->|outbound internet| MITM

    LITELLM -->|serializes requests| OLLAMA
    LITELLM -->|persists keys/spend| DB
    OLLAMA -->|runs on bare-metal| HW
```

``` text
┌─────────────────────────────────────────────────────────────────────────────┐
│ L7: Communications, UX & Operator IDE                                       │
│     - Ingress Reverse Proxy: Caddy (*.brainsos.local, TLS)                 │
│     - Messaging Daemons: brainsos-net-signal-cli, Postfix SMTP, SOGo        │
│     - Operator IDE & PKM: Containerized VS Code (editor.brainsos.local :8443)│
├─────────────────────────────────────────────────────────────────────────────┤
│ L6: Agent Execution Plane (Warm Stateless Hermes Runner & Dynamic Profiles) │
│     - Shared Hermes Runner (:8642 API /v1/chat/completions)                 │
│     - Dynamic Manifest Registry: config/agents.yaml (Zero Container Drift)  │
│     - Asynchronous Agent Core SPI: packages/brainsOS-agent                  │
│     - Isolated Tenancies: data/agent_workspaces/<tenant>/ & memories/       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L5: Memory Plane & Tool Sandbox                                             │
│     - Standalone Packages: packages/brainsOS-memory/, brainsOS-queue/, etc. │
│     - Telemetry & Energy Accounting: packages/brainsOS-telemetry/           │
│     - Partitioned Memories: ./data/agent_memories/<id> (Pure Markdown)      │
│     - Tenant Workspaces:   ./data/agent_workspaces/<id> (Tools, Caches, DBs)│
├─────────────────────────────────────────────────────────────────────────────┤
│ L4: Routing, Security & ACSG Control Plane                                  │
│     - LiteLLM Gateway (:4000) with dynamic virtual keys & spend limits      │
│     - Hardware Serialization: max_parallel_requests: 1 (LPDDR5x guard)      │
│     - Tool Egress Proxy: brainsos-net-egress-proxy (:8081/8082, flows & auth)│
│     - Control Plane DB: brainsos-infra-litellm-db (PostgreSQL, isolated)    │
├─────────────────────────────────────────────────────────────────────────────┤
│ L3: Inference Plane                                                         │
│     - Host Ollama / vLLM bound strictly to loopback (127.0.0.1:11434)       │
│     - Zero direct agent access; all completions route through LiteLLM       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L2: Virtualization & Isolated Bridge Networks                               │
│     - brainsos-ingress (Caddy -> Service ports)                             │
│     - brainsos-internal (Agent egress & messaging daemons)                  │
│     - brainsos-litellm-net (Strictly isolates PostgreSQL from agents)       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L1: Hardware & Physical Plane                                               │
│     - Bare-Metal Target: ASUS Ascent GX10 (NVIDIA GB10 ARM64, unified memory)│
│     - Development Workstation: Apple Silicon macOS (native ARM64 parity)    │
│     - Microgrid & Power Bus: DC shunts, Battery Management, Solar telemetry │
├─────────────────────────────────────────────────────────────────────────────┤
│ Cross-Cutting: Observability & Operational Safety                           │
│     - Decoupled Langfuse v4 + OpenTelemetry distributed tracing             │
│     - Full-data backup & versioning (scripts/control/backup.sh)             │
│     - Granular emergency kill-switch (make emergency-stop)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Built for Enterprise-Grade ACSG Compliance

brainsOS is engineered as an open-source reference implementation for **COHUMAIN certification**, operationalizing the **Agentic Governance & Security Controls (AGSC)** standard developed jointly by **[COHUMAIN Labs](https://www.cohumain.ai/research)** (responsible-AI research) and **[SafeAlign AI](https://safealignai.io/)** (enterprise agent governance and security).

The complete, canonical 25-control catalog is maintained directly within this repository under [`docs/cohumain/`](docs/cohumain/), licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](docs/cohumain/LICENSE):

| Control Domain | Focus Areas | Key Controls Operationalized |
|---|---|---|
| **🛡️ Safety (SAF)** | Runaway prevention & factual safeguards | `SAF-01` System Oversight, `SAF-02` Emergency Kill Switch, `SAF-05` Output Safeguards |
| **⚖️ Alignment (ALN)** | Boundary control & human intervention | `ALN-01` Autonomy Boundary, `ALN-02` Human Oversight, `ALN-05` Action Attribution |
| **🏛️ Governance (GOV)** | Data integrity & carbon accountability | `GOV-01` Data Provenance, `GOV-02` Change Governance, `GOV-08` Environmental Governance |
| **🔒 Security (SEC)** | Isolation, egress security & memory purity | `SEC-01` Coordination Security, `SEC-02` Least Privilege, `SEC-07` Memory Purity Guard |

*For complete control specifications, audit criteria, and external crosswalks (EU AI Act, NIST AI RMF, ISO 42001, MITRE ATLAS), see [docs/cohumain/README.md](docs/cohumain/README.md) and [docs/cohumain/CONTROLS.md](docs/cohumain/CONTROLS.md).*

---

## 6. Connection to Research: Project Millijoule (mJ)

**brainsOS** is the general-purpose, open-source platform that powers **Project Millijoule (mJ)**, an overarching research initiative and living laboratory operated by Patterns at Scale.

While brainsOS provides the open-source software harness, Project mJ investigates the outer physical boundaries of environment-aware computation:
* **Power-Adaptive Reasoning**: Dynamically scaling reasoning depth and model parameter sizes against real-time solar generation curves and battery state-of-charge.
* **Heat-Aware Compute Scheduling (Digital Boilers)**: Treating processors as responsive thermal micro-utilities, batching background reasoning to supplement living-space heating during cold hours.
* **Thermal Characterization Lab**: First-law open-loop flow calorimetry measuring empirical heat dissipation against electrical draw to calculate the true millijoules expended per generated token (`mJ/tok`).

> [!NOTE]
> **Data Demarcation**: Project mJ's living-space sensory feeds, continuous-flow calorimetry logs, proprietary agent personas, and private memory trees remain unshared. brainsOS is the reusable open-source tooling.

---

## 7. Quickstart & Getting Started

### Prerequisites

| Component | Minimum Requirement | Recommended / Notes |
|---|---|---|
| **Operating System** | macOS 14+ (Apple Silicon) or Ubuntu 24.04 LTS / DGX OS (ARM64) | Debian 12+ x86_64 or ARM64 compatible |
| **Container Engine** | Docker Engine 24.0+ & Docker Compose v2 (`docker compose`) | User must be in `docker` group (`sudo usermod -aG docker $USER`) |
| **Host Tooling** | `bash` 4+, `curl`, `git`, `jq`, `python3` (3.10+), `python3-venv` | Handled automatically by `setup-host.sh` on Linux |
| **Unified Memory** | 16 GB RAM minimum | Unified LPDDR5x (GX10 GB10) or Apple Silicon Unified Memory |
| **Inference Engine** | CPU fallback supported | NVIDIA CUDA 12+ & `nvidia-container-toolkit` for GPU acceleration |

---

### Step-by-Step Bootstrap

#### 1. Clone the Repository & Configure Environment
```bash
git clone https://github.com/patternsatscale/brainsOS.git
cd brainsOS

# Bootstrap environment: copies .env, creates data directories, installs virtualenv & packages
make setup

# Generate cryptographically secure passwords, configure domains/URLs, and reload services
make env

# Display all service URLs, credentials, and automatically synchronize /etc/hosts
make urls
```

##### Decoupled Private Fleet Mode (Two-Repository Architecture)
By default, runtime data resides locally in `./data`. To keep proprietary agent intellectual property, OKF memories, custom personas, and fleet manifests in an external private Git repository:
1. Clone or initialize your private fleet repo (e.g., at `/path/to/my-fleet-repo` using template `config/templates/data-repo.gitignore`).
2. Set `BRAINSOS_DATA_DIR=/path/to/my-fleet-repo` in `.env`.
3. Container volumes, Python core packages, and scripts will automatically bind to your private repository. Run `./scripts/control/snapshot-memories.sh` to take automated Git snapshots and push them directly to your private remote.

#### 2. Run Host Baseline Setup
Execute the idempotent setup script to audit system permissions, install dependencies, configure native loopback inference (Ollama), and seed the default model:
```bash
./scripts/setup/setup-host.sh --pull-model
```

#### 3. Initialize Memory Plane & Build Agent Sandbox
Provision the pure Open Knowledge Format (OKF) storage directories and build the unprivileged agent sandbox:
```bash
./scripts/setup/setup-memories.sh
./scripts/setup/setup-hermes.sh
```

#### 4. Start Host Control Plane
Launch the host-side inference runtime (`ollama` on `127.0.0.1:11434`), LiteLLM proxy gateway (`:4000`), and dynamic PostgreSQL persistence:
```bash
./scripts/control/start-control-plane.sh start
./scripts/control/start-control-plane.sh status
```

#### 5. Launch Appliance Container Cluster
Start the ingress proxy, database, Operator IDE, messaging daemons, and agent containers via Docker Compose:
```bash
make up
# or
docker compose up -d
docker compose ps
```

#### 6. Configure Network & Local Domain Routing (`/etc/hosts`)
Route appliance domains to loopback (or your appliance's static LAN IP):
```bash
sudo ./scripts/setup/setup-network.sh --skip-ip -y
```
*Or manually append to `/etc/hosts`:*
```text
127.0.0.1 brainsos.local terrastella.brainsos.local api.terrastella.brainsos.local marvin.brainsos.local api.marvin.brainsos.local cindypawford.brainsos.local api.cindypawford.brainsos.local proxy.brainsos.local memory.brainsos.local langfuse.brainsos.local editor.brainsos.local code.brainsos.local
```

#### 7. Run Verification Test Harnesses & Quality Gates
Validate system isolation, memory purity, package test suites, and routing:
```bash
# Run full package test suites (pytest)
make test

# Run static analysis and type checks (ruff & mypy)
make lint

# Verify multi-agent fleet manifest, isolation, and scheduling
./scripts/verify/verify-fleet.sh

# Verify primary agent workspace persistence and LiteLLM mediation
./scripts/verify/verify-hermes.sh

# Verify Operator IDE and OKF memory plane synchronization
./scripts/verify/verify-editor.sh
./scripts/verify/verify-memories.sh

# Verify in-transit edge egress credential injection
./scripts/verify/verify-egress-token-injection.sh
```

---

## 8. Appliance Service Directory

Once running, the following local services are accessible in your browser:

| Service | Ingress URL | Port | Default Credentials | Role |
|---|---|---|---|---|
| **Thin-Spine Portal** | [https://local.brainsos.ai/](https://local.brainsos.ai/) | `80` / `443` | *Public Portal* | Bespoke Thin-Spine React shell (<4% width, 96%+ full-bleed iframe) |
| **Authentik SSO Ingress** | [https://local.brainsos.ai/auth/](https://local.brainsos.ai/auth/) | `9000` | `operator` (SSO IdP) | Centralized Zero-Trust SSO & Forward-Auth identity gateway |
| **Operator IDE (VS Code)** | [https://local.brainsos.ai/editor/](https://local.brainsos.ai/editor/) | `8443` | Authentik SSO (`CODE_SERVER_AUTH=none`) | Containerized VS Code (code-server), Continue AI & PKM |
| **SOGo Webmail & Groupware** | [https://local.brainsos.ai/mail/](https://local.brainsos.ai/mail/) | `20000` | Authentik SSO (Trusted Proxy) | Webmail, agent mailboxes & CalDAV calendars |
| **LiteLLM Control Plane** | [https://local.brainsos.ai/proxy/ui](https://local.brainsos.ai/proxy/ui) | `4000` | Authentik SSO (Injected Key) | Hardware-serialized model routing, budgets & virtual keys |
| **Tool Egress Proxy Console** | [https://local.brainsos.ai/efw/](https://local.brainsos.ai/efw/) | `8081` | Authentik SSO | Mitmweb real-time egress flow inspection & secret masking |
| **Langfuse Observability** | [https://langfuse.local.brainsos.ai/](https://langfuse.local.brainsos.ai/) | `3001` | Authentik SSO | Distributed tracing & prompt token breakdown |
| **Hermes Runner WebUI** | [https://local.brainsos.ai/runner/](https://local.brainsos.ai/runner/) | `8787` | Authentik SSO | Multi-tenant stateless agent runner terminal & burn target |
| **Agent Queue & Ingress** | `http://127.0.0.1:8000` | `8000` | *Internal* | Non-blocking email webhook ingestion & queue worker daemon |

---

## 9. Common Lifecycle Operations

```bash
# Standardized lifecycle commands via root Makefile
make setup          # Bootstrap .env, data dirs, venv, and editable packages
make ssl-wildcard   # Configure public wildcard SSL via Route 53 & SST Ion (*.local.<zone>)
make deploy-infra   # Deploy platform cloud infrastructure via SST Ion (Route 53, ACME IAM, SES)
make env            # Generate .env with secure passwords, configure URLs, and rebuild
make reload_env     # Reload .env, synchronize passwords across DBs/containers, and show URLs
make urls           # Display all service URLs & credentials, and synchronize /etc/hosts
make up             # Synchronize fleet manifest and start Docker fleet
make down           # Gracefully stop all Docker services
make test           # Run pytest suite across all packages
make lint           # Run ruff check and mypy across all packages
make emergency-stop # Instantly terminate all agent containers

# Fleet snapshots & backups
./scripts/control/snapshot-memories.sh # Automated Git commit/push of private fleet repo
./scripts/control/backup.sh            # Compressed tarball backup of all data planes

# Inspect runtime services & logs
./scripts/control/start-control-plane.sh status
docker compose ps
docker compose logs -f caddy
docker compose logs -f hermes-runner
```

---

## 10. Repository Directory Structure

``` text
brainsOS/  
├── Makefile                  # Standardized lifecycle commands (setup, up, down, test, lint)
├── pyproject.toml            # Centralized Python tooling configuration (ruff, mypy, pytest)
├── LICENSE                   # Apache License 2.0
├── NOTICE                    # Copyright and third-party attribution notices
├── SECURITY.md               # Responsible vulnerability disclosure policy & threat model
├── REPO_MAP.md               # Navigation map & rules of engagement for contributors
├── CONTRIBUTING.md           # Developer guidelines and verification discipline
├── CODE_OF_CONDUCT.md        # Contributor Covenant v2.1
├── SUPPORT.md                # Community support and contact directory
├── README.md                 # System vision, architecture, and quickstart guide
├── AGENTS.md                 # Agent operating discipline and safety rules
├── docker-compose.yml        # Declarative service topology and isolated networks
├── .env.example              # Environment variables template
├── config/  
│   ├── default_settings/     # Declarative fleet and runner manifests (agents.yaml)
│   ├── default_runners/      # Runner templates (hermes, claude-sdk, openai-sdk)
│   ├── default_souls/        # Centralized baseline agent personas (bawtford, marvin, terrastella, ping)
│   ├── templates/            # Seed templates for private data repos (data-repo.gitignore)
│   ├── sample_agent_app/     # Sample agent web application templates (cindypawford)
│   ├── caddy/                # Ingress reverse proxy configuration
│   ├── editor/               # Operator IDE workspace and Continue configs
│   ├── litellm/              # Rate-limiting, model aliases, and DB settings
│   └── egress/               # In-transit credential injection proxy rules
├── packages/
│   ├── brainsOS-agent/       # Standalone AgentRuntime SPI & dynamic profile registry
│   ├── brainsOS-runner/      # Stateless runner adapter framework & agent registry
│   ├── brainsOS-memory/      # Standalone OKF memory engine & VectorStore SPI
│   ├── brainsOS-mail/        # Standalone RFC-compliant asynchronous email client
│   ├── brainsOS-mcp/         # Dynamic FastMCP server exposing tools across packages
│   ├── brainsOS-queue/       # Modular asynchronous FIFO work queue manager
│   └── brainsOS-telemetry/   # Decoupled Observer/Observable bus & SyntheticEnergyObserver
├── docker/                   # Dockerfiles for mail, caddy, editor, hermes, langfuse
├── docs/  
│   ├── cohumain/             # COHUMAIN ACSG 25-control catalog & conformance roadmap
│   ├── project-titan/        # Historical ticket & walkthrough archive (September 2026)
│   ├── reference-architecture-tenets.md  # Core security tenets (TN-1 to TN-9)
│   └── lab-work/             # Claude documentation & critique area (Rule 11)
├── data/                     # Partitioned host volumes / private fleet repo (via BRAINSOS_DATA_DIR)
└── scripts/                  # Structured operational scripts
    ├── setup/                # Host, container, memory, and network provisioning
    ├── control/              # Runtime lifecycle, fleet management, and kill-switch
    ├── verify/               # Automated test harnesses and verification suites
    └── apps/                 # Application-specific operations tooling
```

---

## 11. Repository Transition Notice

This repository has completed its architectural transition to **`patternsatscale/brainsOS`** ([brainsOS.ai](https://brainsos.ai)).

For existing local clones, update your Git remote URL:
```bash
git remote set-url origin https://github.com/patternsatscale/brainsOS.git
git fetch origin
```

All legacy compatibility shims, dual fallbacks, and deprecated naming have been permanently removed in favor of canonical brainsOS configurations and container runtimes.

---

## 12. License & Governance
* **brainsOS Platform Code**: Licensed under the **[Apache License, Version 2.0](LICENSE)**. Developed by **[Patterns at Scale](https://patternsatscale.com)**.
* **Agentic Governance & Security Controls (AGSC v1.0.0)**: Authored by **[COHUMAIN Labs](https://www.cohumain.ai/research)** and **[SafeAlign AI](https://safealignai.io/)**. Licensed under **[Creative Commons Attribution 4.0 International (CC BY 4.0)](docs/cohumain/LICENSE)** © 2026 COHUMAIN Labs & SafeAlign AI. Official standard documentation and workbook: [himjoe.github.io](https://himjoe.github.io/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI/).
