# Contributing to brainsOS

Thank you for your interest in contributing to **brainsOS** ([brainsOS.ai](https://brainsos.ai))! 

brainsOS is an open-source edge agent operating system and governance runtime engineered for the **BRAINS** (**Balanced Reasoning & Agent Inference Node System**) architecture. We welcome contributions from developers, security researchers, and systems engineers.

---

## 1. Operating Discipline & Architectural Tenets

Before submitting code, please review our core architectural rules in [README.md](README.md) and [AGENTS.md](AGENTS.md):
- **Script-First Discipline**: Never patch containers, volumes, or host permissions with one-off terminal hacks. Every operational action must be codified as an idempotent shell script under `scripts/`.
- **Hardware & Portability Rules**: All container images must run natively on ARM64 (Ubuntu 24.04 / DGX OS on the ASUS Ascent GX10 appliance, with full parity on macOS Apple Silicon).
- **Zero Ambient Secrets**: Containers never store raw API tokens or GitHub PATs. Traffic routes through the Tool Egress Gateway with credentials injected in transit.
- **Memory Plane Purity**: The `/memories` mount is strictly reserved for human-auditable flat Markdown files (Open Knowledge Format). Runtime state, tool packages, caches, and binary files belong in `/workspace`.

---

## 2. Development Setup

### Prerequisites
- **macOS (Apple Silicon)** or **Linux (Ubuntu 24.04 / ARM64)**
- **Docker Engine 24.0+** & **Docker Compose v2** (`docker compose`)
- `bash` 4+, `git`, `curl`, `jq`, `python3` (3.10+), `python3-venv`

### Bootstrap
```bash
# Clone the repository
git clone https://github.com/patternsatscale/brainsOS.git
cd brainsOS

# Copy baseline configuration
cp .env.example .env

# Run idempotent host baseline setup (audits permissions, sets up Ollama)
./scripts/setup/setup-host.sh --pull-model

# Scaffold memory plane and build agent sandbox
./scripts/setup/setup-memories.sh
./scripts/setup/setup-hermes.sh

# Start the host control plane and container cluster
./scripts/control/start-control-plane.sh start
docker compose up -d
```

---

## 3. Branching & PR Workflow

1. **Fork & Branch**: Create a focused branch off `main` using descriptive naming:
   ```bash
   git checkout -b task/<issue-number>-<short-description>
   # or for bug fixes:
   git checkout -b fix/<short-description>
   ```

2. **Atomic Commits**: Keep commits concise and meaningful. If your work addresses an issue, reference it:
   ```bash
   git commit -m "[#123] feat(queue): add FIFO priority scheduling"
   ```

3. **Validate Before Opening a PR**:
   Run the local verification checks:
   ```bash
   # 1. Shell script syntax validation
   find scripts -type f -name "*.sh" -exec bash -n {} +

   # 2. Docker compose configuration validation
   docker compose config -q

   # 3. Fleet manifest zero-drift validation
   ./scripts/control/sync-agents.sh --check

   # 4. Service-specific verification (e.g. queue, egress, memory)
   ./scripts/verify/verify-fleet.sh
   ./scripts/verify/verify-memories.sh
   ```

4. **Pull Request Template**:
   Complete all sections of the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md), including:
   - Summary of changes
   - Link to relevant issue (`Closes #...`)
   - Test evidence and command output logs
   - Confirmation of memory purity and secret protection

---

## 4. Coding Standards

- **Shell Scripts**: Bash scripts must use `set -euo pipefail` where appropriate, discover `REPO_ROOT` dynamically, and provide informative status output with idempotent execution.
- **Python**: Follow PEP 8. Standalone packages (`packages/brainsOS-memory`, `packages/brainsOS-mail`, `packages/brainsOS-queue`) must include dedicated pytest suites with high test coverage.
- **Documentation**: All new features, environment variables, or port configurations must be documented in [README.md](README.md).

---

## 5. Code of Conduct

All contributors and maintainers are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please report unacceptable behavior to `community@patternsatscale.com`.
