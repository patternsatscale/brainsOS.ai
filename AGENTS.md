# Project Titan: Agent Operating Discipline & Ticket Workflow

This document establishes the mandatory protocol for AI agents (and human developers) contributing to **Project Titan**. Adherence to these rules ensures architectural boundaries remain uncompromised and development remains disciplined and auditable.

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
1. Create and switch to an isolated task branch:
   ```bash
   git checkout -b task/issue-<issue_number>-<short-description>
   ```

### Step 3: Planning & Architectural Alignment
For non-trivial tasks, draft or update the implementation plan to map directly to the acceptance criteria checkboxes.

### Step 4: Verification Checklist
Before submitting work or opening a PR, the agent **must** run the verification steps detailed in the ticket.
1. Shell syntax & linting: `bash -n scripts/*.sh`
2. Docker Compose configuration: `docker compose config`
3. Any service-specific validations (e.g. Caddy validate, API tests).

### Step 5: Pull Request & Issue Closure
1. Stage only relevant, non-secret files.
2. Commit with conventional commit messages referencing the ticket:
   ```bash
   git commit -m "feat(plane): description (closes #<issue_number>)"
   ```
3. Push the branch and create a Pull Request:
   ```bash
   git push -u origin task/issue-<issue_number>-<short-description>
   gh pr create --title "feat: <title>" --body "Closes #<issue_number>.\n\n### Summary of Changes\n..."
   ```

---

## 2. Inviolable Architectural Guardrails

Agents must never violate the following zero-trust operational boundaries:

### Rule 1: Memory Plane Purity (`/memories`)
- The `/memories` mount is **strictly reserved for human-auditable Open Knowledge Format (OKF) Markdown files**.
- **FORBIDDEN in `/memories`**: SQLite `.db` files, vector database indices, Python packages, `node_modules`, pip caches, or runtime core dumps.
- All internal runtime packages, tools, caches, and local databases used by the agent must reside exclusively within the container's internal filesystem/volume (`/workspace`).

### Rule 2: Inference Boundary
- Raw inference engines (`ollama:11434` or vLLM) must remain isolated on `titan-inference` (`internal: true`).
- The agent plane (`hermes`) must **never** be routed directly to Ollama. All LLM completions must route strictly through the LiteLLM control plane gateway (`litellm:4000`).

### Rule 3: Hardware Serialization
- To protect the unified LPDDR5x memory bus on the GB10 chip and Apple Silicon from bandwidth thrashing, LiteLLM must enforce serialized request scheduling via `max_parallel_requests: 1` (or `2` max).

### Rule 4: Host Sandboxing
- The host Docker socket (`/var/run/docker.sock`) must **never** be mounted into the agent container.
- The agent container must **never** run with `--privileged` or `network_mode: host`.

### Rule 5: Secret Protection
- Never commit `.env` or sensitive API keys to Git. Keep all configuration templated in `.env.example`.
