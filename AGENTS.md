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
1. Create and switch to a concise, ticket-referenced branch:
   ```bash
   git checkout -b task/<issue_number>-<short-description>
   ```
   *(Example: `git checkout -b task/2-control-plane`)*

### Step 3: Planning & Architectural Alignment
For non-trivial tasks, draft or update the implementation plan to map directly to the acceptance criteria checkboxes.

### Step 4: Verification Checklist
Before submitting work or opening a PR, the agent **must** run the verification steps detailed in the ticket.
1. Shell syntax & linting: `bash -n scripts/*.sh`
2. Docker Compose configuration: `docker compose config`
3. Any service-specific validations (e.g. Caddy validate, API tests).

### Step 5: Walkthrough Documentation in `/docs`
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

### Step 6: Pull Request & Issue Closure
To ensure the Git Graph in IDEs and `git log` remains clean, linear, and instantly readable without line truncation:
1. Stage only relevant, non-secret files (including the newly generated documentation in `docs/`).
2. **Front-Load the Ticket Number in Commits**:
   ```bash
   git commit -m "[#<issue_number>] <type>(<plane>): <concise description>"
   ```
   *(Example: `git commit -m "[#2] feat(control): deploy ollama & litellm gateway"`)*
3. Push the branch and create a Pull Request with the same front-loaded title:
   ```bash
   git push -u origin task/<issue_number>-<short-description>
   gh pr create --title "[#<issue_number>] <type>(<plane>): <concise description>" --body "Closes #<issue_number>.\n\n### Summary of Changes\n..."
   ```
4. **Merge Strategy (Squash and Merge)**:
   - Always merge PRs using **Squash and Merge** so all branch commits compress into a single, clean commit on `main`.
   - Result on `main`: `[#2] feat(control): deploy ollama & litellm gateway (#8)`
   - The Git graph remains a clean, linear vertical line with zero merge bubbles.

---

## 2. Scope Containment & Backlog Discipline

To maintain high velocity and avoid hallucinated drift, agents must observe strict scope boundaries:

1. **Atomic Scoping**: An issue should define **one single verifiable deliverable**. If a task requires more than 3-4 separate system modifications, it should be broken down into sub-tickets.
2. **Zero Scope Creep**: If an agent discovers a tangential bug, an unhandled edge case, or a potential enhancement during execution:
   - **DO NOT** expand the current branch or ticket to fix it.
   - **File a new GitHub Issue** labeled as `type:bug` or `type:task` and place it in the Backlog.
   - Complete the original ticket strictly against its published Acceptance Criteria.

## 3. Inviolable Architectural Guardrails

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
