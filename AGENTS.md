# Project Titan: Agent Operating Discipline & Ticket Workflow

This document establishes the mandatory protocol for AI agents (and human developers) contributing to **Project Titan**. Adherence to these rules ensures architectural boundaries remain uncompromised and development remains disciplined and auditable.

## 0. Target Architecture & Hardware Context

- **Production Target**: **ASUS Ascent GX10** appliance (NVIDIA GB10 chip, ARM64, unified LPDDR5x memory bus ~273 GB/s, running DGX OS / Ubuntu 24.04).
- **Development Workstation**: **macOS (Apple Silicon)** providing native ARM64 container parity.
- **Portability Rules**:
  - All Docker images must run natively on ARM64 without emulation.
  - Storage paths are parameterized via `.env`: `./data/memories` for local macOS development, `/data/titan/memories` on the production GX10.
  - Hardware package pinning (`apt-mark hold`) applies only on Linux/DGX OS (safely bypassed on macOS in `scripts/setup-host.sh`).
- **Architectural Reference**: Agents must consult [README.md](file:///Users/pats/Development/project_titan/README.md) for full plane topology and system specifications.

---

## 1. The Ticket-Driven Workflow

Every unit of engineering work, bug fix, or configuration change must trace to a GitHub Issue.

### Step 1: Claim & Read the Issue
When assigned an issue (e.g., "Work on issue #2"):
1. View the issue requirements and acceptance criteria:
   ```bash
   gh issue view <issue_number>
   ```
2. Thoroughly parse the **Objective**, **Acceptance Criteria**, **Security Constraints**, and **Verification Steps**.

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
- **Script-First Validation**: Always test via repository scripts (`./scripts/verify-*.sh`, `./scripts/setup-*.sh`, `./scripts/backup.sh`) rather than one-off manual Docker or terminal commands.
- Shell syntax & linting: `bash -n scripts/*.sh`
- Docker Compose configuration: `docker compose config`
- Any service-specific validations (e.g. Caddy validate, API tests).

### Step 5: Architecture & Documentation Alignment (`README.md` & `AGENTS.md`)
Before finalizing a ticket or opening a PR, the agent **must** review whether the changes introduce any architectural shifts, new services, port updates, or revised security boundaries:
- **Topology & Runtimes**: If containers, host processes, ports, or environment parameters changed, update [README.md](file:///Users/pats/Development/project_titan/README.md).
- **Rules & Guardrails**: If operational rules, agent procedures, or workflows changed, update [AGENTS.md](file:///Users/pats/Development/project_titan/AGENTS.md).
- Documentation must never drift from the live codebase; all doc updates must be included within the ticket's branch and PR.

### Step 6: Walkthrough Documentation & Mandatory Pre-Commit Review Gate
Every ticket completion **must** include a dedicated walkthrough document placed in the `docs/` directory using the naming convention:
```text
docs/YYYY-MM-DD-ticket<issue_number>.md
```
*(Example: `docs/2026-09-06-ticket1.md`)*

The walkthrough document must record:
1. **Summary of Changes**: Exact files created, modified, or deleted.
2. **Acceptance Criteria Verification**: Evidence that all checkboxes in the ticket are satisfied.
3. **Automated & Manual Test Logs**: Exact terminal commands and outputs validating functionality.
4. **Follow-Up / Backlog Items**: Any edge cases or out-of-scope ideas discovered during the task.

> [!IMPORTANT]
> **Internal Pre-Commit Review Gate**:
> The agent must **NEVER** commit, push, or open a Pull Request without explicit human review and approval.
> - After generating the walkthrough document and validating all changes, the agent **must STOP and present the walkthrough summary to the user**.
> - The human developer conducts an internal review of the proposed changes, test logs, and diff.
> - Only upon receiving explicit approval ("Approved", "Proceed with commit/PR", etc.) may the agent proceed to Step 7.

### Step 7: Post-Approval Commit, Push & Pull Request
Only after the human reviewer explicitly approves the walkthrough in Step 6:
To ensure the Git Graph in IDEs and `git log` remains clean, linear, and instantly readable without line truncation:
1. Stage only relevant, non-secret files (including the newly generated documentation in `docs/`).
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

1. **Atomic Scoping**: An issue should define **one single verifiable deliverable**. If a task requires more than 3-4 separate system modifications, it should be broken down into sub-tickets.
2. **Zero Scope Creep**: If an agent discovers a tangential bug, an unhandled edge case, or a potential enhancement during execution:
   - **DO NOT** expand the current branch or ticket to fix it.
   - **File a new GitHub Issue** labeled as `type:bug` or `type:task` and place it in the Backlog.
   - Complete the original ticket strictly against its published Acceptance Criteria.
3. **Automated QA & Regression Backlog Promotion**: When delivering core architectural components, security boundaries, or infrastructure tickets, agents frequently validate critical guarantees through manual verification, ad-hoc shell commands, or isolation inspections:
   - **DO NOT** inflate the current deliverable's scope by building an entire automated regression harness or test suite unless the ticket explicitly calls for it.
   - **DO** file a new GitHub Issue for the Backlog labeled as `type:task`, `type:security`, or `type:infra` (e.g., `[Phase X] Automated CI/CD Regression Test Suite & Security Boundary QA`).
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
- The dedicated PostgreSQL persistence store (`titan-litellm-db`) is strictly reserved for LiteLLM's internal control plane (dynamic model registrations, virtual keys, rate limits, audit tables).
- The agent plane (`hermes`) must **never** be given database credentials, connection strings (`DATABASE_URL`), network access (`titan-litellm-net`), or storage volume mounts to the database.
- The database port is bound strictly to `127.0.0.1:${LITELLM_DB_PORT:-5432}` on the host for LiteLLM's use only.
- Strict isolation is enforced in `.github/workflows/pre-commit.yml` on every commit and PR.

### Rule 7: Information Compartmentalization in Agent Context
- Persona documents (`SOUL.md`), agent prompts, and runtime configurations provided to the agent plane (`hermes`) must observe strict need-to-know principles.
- **NEVER** disclose host backend infrastructure names (e.g. `Ollama`, `titan-litellm-db`), host daemon internals, host socket paths, or internal database architectures in agent-facing prompts or identity files.
- The agent must be instructed exclusively on its assigned interfaces (e.g. its OpenAI-compatible completions endpoint `http://litellm:4000/v1`), its sandbox storage root (`/workspace`), and its pure Markdown memory path (`/memories`).

### Rule 8: Script-Driven Discipline (Zero Ad-Hoc Container/Host Patching)
- **Zero Ad-Hoc Fixes**: AI agents and developers must **never** "fix" system issues, container states, volumes, networks, or file permissions using direct, one-off ad-hoc terminal commands (e.g. manual `docker exec`, `docker cp`, ad-hoc container restarts, manual host `chown`/`chmod` overrides) that leave no reproducible trace in the repository.
- **Codify in `scripts/*.sh`**: Every operational action—setup, directory scaffolding, permissions enforcement, build automation, backup/restore, emergency interventions, and health verifications—must be codified as an idempotent shell script within the `scripts/` directory.
- **Test the Scripts, Not One-Offs**: When debugging or verifying functionality, agents must execute the scripts themselves (e.g. `./scripts/setup-hermes.sh`, `./scripts/verify-hermes.sh`, `./scripts/backup.sh`). If a behavior needs adjustment, update the underlying script, Dockerfile, or configuration file, and re-run the script to validate the fix.
- **The GX10 Reproducibility Guarantee**: Anyone cloning the repository onto a fresh host (macOS development workstation or production ASUS Ascent GX10 appliance) must be able to achieve a 100% identical, functional state solely by executing the documented scripts in `scripts/`. If a step requires manual human intervention or undocumented Docker commands, the implementation is considered defective.


