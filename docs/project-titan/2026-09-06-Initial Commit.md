# Project Titan: Phase 0 Foundation Walkthrough

All Phase 0 baseline configurations, security boundaries, operational scripts, and version control setup for Project Titan have been created, validated, and pushed to GitHub.

---

## 1. Repository Status

- **GitHub Repository**: [patternsatscale/project-titan](https://github.com/patternsatscale/project-titan) *(Private)*
- **Tracking Branch**: `main -> origin/main`
- **Working Tree**: Clean (`.env`, live memories, and backups are safely ignored).

---

## 2. Architecture & File Manifest

### Configuration & Environment
- [`.gitignore`](file:///Users/pats/Development/project_titan/.gitignore): Protects secrets (`.env`), live memories (`data/memories/*`), snapshot archives (`data/backups/`), and OS artifacts.
- [`.env.example`](file:///Users/pats/Development/project_titan/.env.example) & [`.env`](file:///Users/pats/Development/project_titan/.env): Configured with paths (`TITAN_DATA_DIR`), user IDs (`1000:1000`), port mappings, domain defaults (`titan.local`), and virtual keys.

### Network Topology & Services
- [`docker-compose.yml`](file:///Users/pats/Development/project_titan/docker-compose.yml):
  - **`titan-ingress`** network: Caddy reverse proxy routing virtual hosts to internal containers.
  - **`titan-internal`** network: Enables Hermes agent outbound WAN egress (web browsing, Signal, external APIs) and routing to LiteLLM, while completely isolating raw inference.
  - **`titan-inference`** network (`internal: true`): Exclusively bridges LiteLLM to Ollama; raw inference is inaccessible to Hermes or external hosts.
  - **Agent Sandbox (`hermes`)**: Standard unprivileged execution (enabling `apt`, `pip`, headless browsers, local processes) with internal workspace storage (`hermes_runtime_state`) and no access to `/var/run/docker.sock`.
  - **Pure Memory Plane (`silverbullet` / `/memories`)**: Dedicated exclusively to human-auditable Open Knowledge Format (OKF) Markdown notes.

### Service Manifests
- [`config/caddy/Caddyfile`](file:///Users/pats/Development/project_titan/config/caddy/Caddyfile): Routes `hermes.titan.local`, `proxy.titan.local`, `memory.titan.local`, and provides a default ingress landing page. Validated with Caddy container.
- [`config/litellm/config.yaml`](file:///Users/pats/Development/project_titan/config/litellm/config.yaml): Enforces hardware serialization (`max_parallel_requests: 1`) to protect the unified memory bus, proxies to Ollama, and configures virtual keys.
- [`config/hermes/config.json`](file:///Users/pats/Development/project_titan/config/hermes/config.json): Connects Hermes to LiteLLM with OKF storage guidelines and internal `/workspace` segregation.

### Operational Scripts
- [`scripts/setup-host.sh`](file:///Users/pats/Development/project_titan/scripts/setup-host.sh): Idempotent baseline script with cross-platform OS detection (Ubuntu package pinning via `apt-mark hold` on DGX OS; safe execution on macOS).
- [`scripts/snapshot-memories.sh`](file:///Users/pats/Development/project_titan/scripts/snapshot-memories.sh): Automated backup and rollback tool for the OKF memory directory with 14-snapshot retention pruning.
- [`scripts/emergency-stop.sh`](file:///Users/pats/Development/project_titan/scripts/emergency-stop.sh): Immediate software kill-switch to pause the agent container and revoke the LiteLLM virtual key.

---

## 3. Validation Summary

| Component | Validation Step | Result |
| :--- | :--- | :--- |
| **Shell Scripts** | `bash -n scripts/*.sh` | All scripts passed syntax check |
| **Host Setup** | Executed `./scripts/setup-host.sh` | Initialized directories and permissions cleanly |
| **Snapshots** | Executed `./scripts/snapshot-memories.sh` | Successfully generated test archive |
| **Docker Compose** | `docker compose config` | Validated service topology and network definitions |
| **Caddyfile** | `caddy validate --config /etc/caddy/Caddyfile` | `Valid configuration` |
| **Git / GitHub** | `gh repo create` + `git push` | Private repository created and tracking `main` |

---

## 4. Next Steps

- Test local container startup:
  ```bash
  docker compose up -d
  ```
- Seed the initial test model into Ollama (`gemma2:2b`):
  ```bash
  ./scripts/setup-host.sh --pull-model
  ```
- When ready on the ASUS GX10:
  - Clone via SSH or `gh repo clone patternsatscale/project-titan`
  - Run `./scripts/setup-host.sh` to apply DGX OS package pins and path configs.
