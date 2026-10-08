# brainsOS: Agent Operating Discipline & Ticket Workflow

This document establishes the mandatory protocol for AI agents (and human developers) contributing to **brainsOS** ([brainsOS.ai](https://brainsos.ai)). Adherence to these rules ensures architectural boundaries remain uncompromised and development remains disciplined and auditable.

## 0. Target Architecture & Hardware Context

- **Production Target**: **ASUS Ascent GX10** appliance (NVIDIA GB10 chip, ARM64, unified LPDDR5x memory bus ~273 GB/s, running DGX OS / Ubuntu 24.04).
- **Development Workstation**: **macOS (Apple Silicon)** providing native ARM64 container parity.
- **Portability Rules**:
  - All Docker images must run natively on ARM64 without emulation.
  - Storage paths are parameterized via `.env`: `./data/agent_memories` for local macOS development, `/data/brainsos/agent_memories` on the production GX10.
  - Hardware package pinning (`apt-mark hold`) applies only on Linux/DGX OS (safely bypassed on macOS in `scripts/setup/setup-host.sh`).
- **Architectural Reference**: Agents must consult [README.md](README.md) for full plane topology and system specifications.
- **Out of Scope**: All experimental documentation, persona critiques, and lab work reside exclusively within the private fleet repository (`${BRAINSOS_DATA_DIR}/docs/lab-work/`) under the Two-Repository Architecture (Rule 14) and are **excluded from all platform core coding work**. See Rule 11.

---

## 1. The Ticket-Driven Workflow

Every unit of engineering work, bug fix, or configuration change must trace to a GitHub Issue.
For higher-level roadmap planning, multi-ticket initiative scoping, two-repository routing, and Epic decomposition, developers and AI agents must follow [PLANNING.md](PLANNING.md).

### Step 1: Claim & Read the Issue
When assigned an issue (e.g., "Work on issue #2"):
1. View the issue requirements and acceptance criteria:
   ```bash
   gh issue view <issue_number>
   ```

2. Claim the ticket by assigning it:
   ```bash
   gh issue edit <issue_number> --add-assignee "@me"
   ```

3. Thoroughly parse the **Objective**, **Acceptance Criteria**, **Security Constraints**, and **Verification Steps**.

### Step 2: Branching Policy
Never develop or commit directly on the `main` branch.
1. Create and switch to a concise, ticket-referenced branch:
   ```bash
   git checkout -b task/<issue_number>-<short-description>
   ```
   *(Example: `git checkout -b task/2-control-plane`)*

### Step 3: Planning & Architectural Alignment
For non-trivial tasks, draft or update the implementation plan to map directly to the acceptance criteria checkboxes.

### Step 4: Verification Checklist & Script-First Execution
Before submitting work or opening a PR, the agent **must** run the verification steps detailed in the ticket.
- **Documentation & Static Asset Exemption**: If the task is purely documentation, specs, or static asset additions, **skip all test script executions** (see Rule 13).
- **Environment Gate**: If no `.env` file exists on the host, **STOP**—the machine is an unconfigured repository clone and must not run execution or verification scripts.
- **Script-First Validation**: When verifying functional code, always test via repository scripts (`./scripts/verify/*.sh`, `./scripts/setup/*.sh`, `./scripts/control/*.sh`) rather than one-off manual Docker or terminal commands.
- Shell syntax & linting: `find scripts -type f -name "*.sh" -exec bash -n {} +`
- Docker Compose configuration: `docker compose config`
- Any service-specific validations (e.g. Caddy validate, API tests).

### Step 5: Architecture & Documentation Alignment (`README.md` & `AGENTS.md`)
Before finalizing a ticket or opening a PR, the agent **must** review whether the changes introduce any architectural shifts, new services, port updates, or revised security boundaries:
- **Topology & Runtimes**: If containers, host processes, ports, or environment parameters changed, update [README.md](README.md).
- **Rules & Guardrails**: If operational rules, agent procedures, or workflows changed, update [AGENTS.md](AGENTS.md).
- Documentation must never drift from the live codebase; all doc updates must be included within the ticket's branch and PR.

### Step 6: Walkthrough Documentation & Mandatory Pre-Commit Review Gate
Every ticket completion **must** include a dedicated walkthrough document:
- **Standalone Tickets**: Placed in the `docs/` root directory using the naming convention:
  ```text
  docs/YYYY-MM-DD-ticket<issue_number>.md
  ```
  *(Example: `docs/2026-09-06-ticket1.md`)*
- **Epic Sub-Tickets**: When working on tickets that are part of an Epic (decomposed per [PLANNING.md](PLANNING.md)), the walkthrough document must be placed directly inside the epic's dedicated subfolder under `docs/epics/`:
  ```text
  docs/epics/<epic-name>/YYYY-MM-DD-ticket<issue_number>.md
  ```
  *(Example: `docs/epics/brainsOS-runner/2026-09-29-ticket186.md`)*


The walkthrough document must record:
1. **Summary of Changes**: Exact files created, modified, or deleted.
2. **Acceptance Criteria Verification**: Evidence that all checkboxes in the ticket are satisfied.
3. **Automated & Manual Test Logs**: Exact terminal commands and outputs validating functionality.
4. **Follow-Up / Backlog Items**: Any edge cases or out-of-scope ideas discovered during the task.
5. **Local Web Preview URLs**: For tickets touching web applications, canvases, portals, or frontend UI components (e.g. `data/agent_apps/cindypawford/`), the agent must ensure a local preview server is running and explicitly provide clickable localhost and LAN URLs with instructions on specific rendering and interaction points to test (including mobile viewport emulation).

> [!IMPORTANT]
> **Internal Pre-Commit Review Gate**:
> The agent must **NEVER** commit, push, or open a Pull Request without explicit human review and approval.
> - After generating the walkthrough document and validating all changes, the agent **must STOP and present the walkthrough summary to the user along with active preview URLs**.
> - The human developer conducts an internal review of the proposed changes, test logs, live web rendering, and diff.
> - Only upon receiving explicit approval ("Approved", "Proceed with commit/PR", etc.) may the agent proceed to Step 7.

### Step 7: Post-Approval Commit, Push & Pull Request
Only after the human reviewer explicitly approves the walkthrough in Step 6:
To ensure the Git Graph in IDEs and `git log` remains clean, linear, and instantly readable without line truncation:
1. Stage only relevant, non-secret files (including the newly generated documentation in `docs/` or `docs/epics/`).
2. **Front-Load the Ticket Number & Add Co-Authorship**:
   Include the `Co-authored-by` trailer so GitHub automatically displays Antigravity as a co-author and contributor:
   ```bash
   git commit -m "[#<issue_number>] <type>(<plane>): <concise description>

   Co-authored-by: Google Antigravity <antigravity@google.com>"
   ```
   *(Example: `git commit -m "[#2] feat(control): deploy ollama & litellm gateway\n\nCo-authored-by: Google Antigravity <antigravity@google.com>"`)*
3. **Push & Open PR with Agent Attribution Banner**:
   Prepend the standard agent header to all PR descriptions and issue comments:
   ```bash
   git push -u origin task/<issue_number>-<short-description>
   gh pr create --title "[#<issue_number>] <type>(<plane>): <concise description>" \
     --body "> 🤖 **Automated Agent Report** — *Google Antigravity Pair Programmer*
   > **Ticket**: #<issue_number>

   Closes #<issue_number>.

   ### Summary of Changes
   ..."
   ```
4. **Merge Strategy (Squash and Merge)**:
   - Always merge PRs using **Squash and Merge** so all branch commits compress into a single, clean commit on `main`.
   - Result on `main`: `[#2] feat(control): deploy ollama & litellm gateway (#8)`
   - The Git graph remains a clean, linear vertical line with zero merge bubbles and co-authorship preserved.

---

## 2. Scope Containment & Backlog Discipline

To maintain high velocity and avoid hallucinated drift, agents must observe strict scope boundaries:

1. **Atomic Scoping**: An issue should define **one single verifiable deliverable** (typically 1–2 days of engineering). If a task requires more than 3-4 separate system modifications, break it down into an Epic and child sub-tickets per [PLANNING.md](PLANNING.md).
2. **Zero Scope Creep**: If an agent discovers a tangential bug, an unhandled edge case, or a potential enhancement during execution:
   - **DO NOT** expand the current branch or ticket to fix it.
   - **File a new GitHub Issue** labeled as `bug` or `task`, assign it to the appropriate active milestone, and if applicable add it to the parent Epic's tasklist per [PLANNING.md](PLANNING.md).
   - Complete the original ticket strictly against its published Acceptance Criteria.
3. **Automated QA & Regression Backlog Promotion**: When delivering core architectural components, security boundaries, or infrastructure tickets, agents frequently validate critical guarantees through manual verification, ad-hoc shell commands, or isolation inspections:
   - **DO NOT** inflate the current deliverable's scope by building an entire automated regression harness or test suite unless the ticket explicitly calls for it.
   - **DO** file a new GitHub Issue for the Backlog labeled with primary type (`task`) and domain tags (`security`, `infra`) (e.g., `[Phase X] Automated CI/CD Regression Test Suite & Security Boundary QA`).
   - **Required QA Ticket Content**:
     - **Context & Originating Tickets**: Reference previous tickets where boundaries and behaviors were established.
     - **Consolidated Test Cases**: Explicit checkboxes detailing functional and security assertions (e.g., container DNS isolation, hardware concurrency limits, unauthorized key rejection, dynamic model/key persistence across restarts, memory purity, file permission masks).
     - **Automation Commands**: Proposed test harness invocation (e.g., `./scripts/run-regression-tests.sh` or pytest) to be integrated into CI/CD.
   - This ensures automated testing and CI/CD hardening remain auditable, comprehensive, and prioritized without stalling atomic feature delivery.

## 3. Inviolable Architectural Guardrails

Agents must never violate the following zero-trust operational boundaries:

### Rule 1: Memory Plane Purity (`/memories`)
- The `/memories` mount is **strictly reserved for human-auditable Open Knowledge Format (OKF) Markdown files**.
- **FORBIDDEN in `/memories`**: SQLite `.db` files, vector database indices, Python packages, `node_modules`, pip caches, or runtime core dumps.
- All internal runtime packages, tools, caches, and local databases used by the agent must reside exclusively within the container's internal filesystem/volume (`/workspace`).

### Rule 2: Inference Boundary
- Raw inference engines (`ollama:11434` or vLLM) run natively on the host system, bound strictly to loopback (`127.0.0.1:11434`), and are completely unreachable from external networks.
- The agent plane (`hermes`) running inside Docker must **never** be routed directly to Ollama. All LLM completions must route strictly through the host LiteLLM control plane gateway (`http://host.docker.internal:4000/v1`).

### Rule 3: Hardware Serialization
- To protect the unified LPDDR5x memory bus on the GB10 chip and Apple Silicon from bandwidth thrashing, LiteLLM must enforce serialized request scheduling via `max_parallel_requests: 1` (or `2` max).

### Rule 4: Host Sandboxing
- The host Docker socket (`/var/run/docker.sock`) must **never** be mounted into the agent container.
- The agent container must **never** run with `--privileged` or `network_mode: host`.

### Rule 5: Secret Protection
- Never commit `.env` or sensitive API keys to Git. Keep all configuration templated in `.env.example`.

### Rule 6: Control Plane Database Isolation
- The dedicated PostgreSQL persistence store (`brainsos-control-litellm-db`, formerly `brainsos-infra-litellm-db`) is strictly reserved for LiteLLM's internal control plane (dynamic model registrations, virtual keys, rate limits, audit tables).
- The agent plane (`hermes`) must **never** be given database credentials, connection strings (`DATABASE_URL`), network access (`brainsos-control-net`), or storage volume mounts to the database.
- The database port has zero host port bindings; it communicates strictly over the isolated `brainsos-control-net` network with the containerized LiteLLM gateway.
- Strict isolation is enforced in `.github/workflows/pre-commit.yml` on every commit and PR.

### Rule 7: Information Compartmentalization in Agent Context
- Persona documents (`SOUL.md`), agent prompts, and runtime configurations provided to the agent plane (`hermes`) must observe strict need-to-know principles.
- **NEVER** disclose host backend infrastructure names (e.g. `Ollama`, `brainsos-control-litellm-db`), host daemon internals, host socket paths, or internal database architectures in agent-facing prompts or identity files.
- The agent must be instructed exclusively on its assigned interfaces (e.g. its OpenAI-compatible completions endpoint `http://litellm:4000/v1`), its sandbox storage root (`/workspace`), and its pure Markdown memory path (`/memories`).

### Rule 8: Script-Driven Discipline (Zero Ad-Hoc Container/Host Patching)
- **Zero Ad-Hoc Fixes**: AI agents and developers must **never** "fix" system issues, container states, volumes, networks, or file permissions using direct, one-off ad-hoc terminal commands (e.g. manual `docker exec`, `docker cp`, ad-hoc container restarts, manual host `chown`/`chmod` overrides) that leave no reproducible trace in the repository.
- **Codify in `scripts/*.sh`**: Every operational action—setup, directory scaffolding, permissions enforcement, build automation, backup/restore, emergency interventions, and health verifications—must be codified as an idempotent shell script within the `scripts/` directory.
- **Test the Scripts, Not One-Offs**: When debugging or verifying functionality, agents must execute the scripts themselves (e.g. `./scripts/setup/setup-hermes.sh`, `./scripts/verify/verify-hermes.sh`, `./scripts/control/backup.sh`). If a behavior needs adjustment, update the underlying script, Dockerfile, or configuration file, and re-run the script to validate the fix.
- **The GX10 Reproducibility Guarantee**: Anyone cloning the repository onto a fresh host (macOS development workstation or production ASUS Ascent GX10 appliance) must be able to achieve a 100% identical, functional state solely by executing the documented scripts in `scripts/`. If a step requires manual human intervention or undocumented Docker commands, the implementation is considered defective.
- **Script Organization & Domain Separation**: Operational scripts are organized strictly into domain-specific subdirectories under `scripts/`:
  - `scripts/setup/`: Host, container, memory, and network provisioning.
  - `scripts/control/`: Runtime lifecycle, fleet sync, backups, and emergency kill-switch.
  - `scripts/verify/`: Automated test harnesses and verification suites.
  - `scripts/apps/<app_id>/`: Application-specific deployment and management scripts.
  All scripts dynamically discover `REPO_ROOT` so they function identically across environments.
- **Strictly No Symbolic Links**: The repository strictly forbids symbolic links (`symlinks`). All scripts, configurations, templates, and documentation must reside in and reference their canonical filesystem locations directly. Compatibility symlinks across directories are strictly prohibited to ensure maximum portability across host operating systems (Linux and macOS) and container bind mounts.

### Rule 9: Multi-Tenant Partitioning & Shared Runner Registry Authority
- **Declarative Manifest Authority**: All multi-agent fleet compositions must be defined declaratively in `config/default_settings/agents.yaml` (seeded to `data/settings/agents.yaml` on bootstrap). The manifest serves as the authoritative dynamic registry consumed by `packages/brainsOS-agent` and the shared stateless runner (`hermes-runner`). Adding, removing, or updating agent profiles requires zero container rebuilds or Docker daemon restarts.
- **Zero Cross-Tenant Leakage**: Every tenant agent unit must be assigned its own isolated host workspace (`/data/agent_workspaces/<tenant_id>` or dedicated web app workspace like `data/agent_apps/<app_name>/site`), its own pure OKF memory partition (`/data/agent_memories/<tenant_id>`), and its own isolated virtual key. The shared stateless runner dynamically validates path boundaries and injects isolated persona and memory partitions on a per-request basis. Probing or accessing another tenant's filesystem partition constitutes an immediate security breach.
- **Standalone Package Decoupling**: Core domain logic intended for cross-agent reuse or community contributions (such as `packages/brainsOS-agent/`, `packages/brainsOS-queue/`, `packages/brainsOS-mail/`, and `packages/brainsOS-memory/`) must reside in standalone Python packages with dedicated unit test suites and abstract SPIs, isolated from direct container runtime dependencies to avoid PR merge conflicts.

### Rule 10: In-Transit Egress Credential Injection
- **Zero Ambient Container Secrets**: Agent containers must **never** hold raw GitHub tokens (`GH_TOKEN`, `GITHUB_TOKEN`), personal access tokens (PATs), or third-party egress API secrets in their environment variables, `.env` mounts, or on-disk configuration files.
- **Dedicated Egress Proxying**: All outbound internet traffic from agent containers routes through the dedicated Tool Egress Gateway proxy (`brainsos-agent-egress-proxy:8082` via `HTTPS_PROXY`), maintaining 100% standard destination URLs (`https://github.com`, `https://api.github.com`) without fragile URL rewrites or custom enterprise host overrides.
- **Multi-Tenant In-Transit Injection & Isolation**: The egress proxy addon (`config/egress/addons/github_auth.py`) inspects client container IP identity on `brainsos-internal-net`. Authorized tenants (e.g. Cindy Pawford) have credentials injected in transit (`Authorization: Bearer` for REST/GraphQL APIs, `Authorization: Basic` for Git Smart HTTP) while unauthorized tenants are rejected (`403 Forbidden`).
- **Flow Display Redaction**: All injected credentials are masked to `[INJECTED_CINDY_TOKEN]` within flow displays and inspection APIs, ensuring zero ambient secrets leak into the `mitmweb` console.

### Rule 11: Separation of Build and Record (Lab Work Resides in Private Fleet Repository)
- **Out of Scope for the Platform Core**: Under the Two-Repository Architecture (Rule 14), all documentation, critique areas, and experimental persona narratives (formerly in `docs/lab-work/`) reside strictly within the private fleet repository (`${BRAINSOS_DATA_DIR}/docs/lab-work/`), owned by Claude on behalf of the maintainer. Platform coding agents must **never** read private fleet records for core open-source requirements, nor commit proprietary lab work or persona critiques to the `brainsOS.ai` core.
- **Why**: An actor that both builds the system and authors the account of the system has an unmanaged conflict of interest. Keeping the narrator out of the core build, and the builder out of private fleet narration, ensures that the open-source platform core remains uncompromised and decoupled from proprietary fleet IP.
- **Requirements Never Originate There**: Work on `brainsOS.ai` is authorised exclusively by a GitHub Issue per §1. A project report, pattern write-up, or stakeholder deck in the private fleet repository is a record or a proposal, never an automatic core work order. If something in it needs building in `brainsOS.ai`, it becomes an open-source Issue first.
- **No Runtime Coupling**: Nothing in `scripts/`, `config/`, `packages/`, or CI workflows may import, execute, or depend on files from the private lab-work area.
- **The Boundary Is Reciprocal**: Claude does not write application code, scripts, configuration or infrastructure in this repository, and does not write binding documents into the repository proper. Coding agents do not write the project record.

### Rule 12: Sub-Agent Persona Isolation & Code Quality Protection
- **Decoupled Persona Hierarchy**: Primary conversational agents operate under centralized personas (`config/default_souls/<agent_id>.md` or live override `data/souls/<agent_id>.md`), while specialized execution sub-agents operate under dedicated dot-namespaced prompts at `config/default_souls/<agent_id>.<subagent_id>.md` (or `data/souls/<agent_id>.<subagent_id>.md`), resolved via `brainsos_agent.souls.resolve_soul` across all runtime runners.
- **Supervisory Orchestration Without Code Contamination**: Primary conversational agents act as Creative Directors / Orchestrators with full visibility into `/app/html`, Git, and project tools, formulating structured technical parameters (`feature_name`, `specification`, `target_files`, `design_tokens`) to trigger specialized sub-agents. Conversational agents must **never** generate raw production code contaminated with conversational banter, roleplay, canine humor, or markdown code fences.
- **Automated Quality Gates & Sanitization**: All code generated by sub-agents must pass automated linting and sanitization (fences stripped, conversational text removed, `node -c` syntax validation) before writing to target filesystems. Sub-agent execution briefs and diffs must be logged to `/memories/logs/` in human-auditable Open Knowledge Format (OKF) Markdown (Rule 1).

### Rule 13: Execution Environment Precondition & Doc-Only Verification Exemption
- **Mandatory `.env` Execution Precondition**: If there is **NO `.env` file** present in the repository root, **STOP**. The host machine is strictly an unconfigured repository clone, not an active execution host, and must **never** run test scripts, daemon processes, docker containers, or background services.
- **Pure Documentation & Asset Exemption**: When a ticket or user request is strictly updating documentation (`docs/`, `*.md`, specifications) or static assets (`apps/*/assets/`), agents must **NEVER** run runtime verification scripts, fleet synchronization, or test harnesses. Script-first validation applies strictly to functional code changes, shell scripts, and infrastructure modifications.

### Rule 14: Two-Repository Architecture & Private Fleet State Isolation
- **Platform vs. Private Fleet Separation**: The `brainsOS` repository is strictly an open-source, stateless platform core containing container topologies, reusable Python packages, and operational harnesses. All proprietary agent personas (`souls/`), OKF Markdown knowledge/memories (`agent_memories/`), custom agent fleet definitions (`settings/`), agent-authored codebases (`agent_workspaces/`, `agent_apps/`), and persistent databases must be decoupled from the core repository.
- **Dynamic Path Parameterization**: All platform containers, packages, and scripts must resolve data paths via `BRAINSOS_DATA_DIR` (defaulting to `./data` for local mode, or an external private repository path like `/path/to/my-fleet-repo` in decoupled mode). Sub-path overrides (`BRAINSOS_AGENT_MEMORIES_DIR`, `BRAINSOS_SOULS_DIR`, etc.) inherit dynamically from `BRAINSOS_DATA_DIR`.
- **Zero Proprietary Fleet Commits to Core**: Proprietary agent personas, client memories, and confidential manifests must **never** be committed to `brainsOS.ai`. When decoupled, fleet state is committed and pushed exclusively to the private fleet repository using `./scripts/control/snapshot-memories.sh` or Git workflows within `BRAINSOS_DATA_DIR`.
- **Strict Exclusion of Private Fleet Repository Names**: AI agents and developers must **NEVER** mention or commit the literal private fleet repository name or private developer filesystem paths in public GitHub issues, PR titles/descriptions, commit messages, or core platform codebase files. Always refer to external fleet storage using the parameter `${BRAINSOS_DATA_DIR}`, generic descriptions ("the external private fleet repository"), or sample documentation placeholders (`/path/to/my-fleet-repo`). Zero private leakage is strictly enforced locally via `./scripts/verify/verify-no-private-refs.sh` and remotely in CI (`.github/workflows/pre-commit.yml`).


