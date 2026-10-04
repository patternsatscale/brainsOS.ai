---
name: agents-discipline
description: Mandatory operating protocol and architectural guardrails for AI agents
  and developers contributing to brainsOS. Use this skill whenever building code,
  modifying containers, creating branches, executing tests, or opening PRs.
version: 1.0.0
tags:
- operating-discipline
- architectural-guardrails
- pre-commit-gate
triggers:
- agent discipline
- agents.md
- walkthrough gate
---

# `agents-discipline` — Agent Operating Discipline & Architectural Guardrails

This skill enforces the core operating discipline, 14 inviolable architectural guardrails, and ticket-driven workflow defined in [`AGENTS.md`](../../../../AGENTS.md).

---

## The Ticket-Driven Workflow

1. **Claim & Read the Issue**: `gh issue view <id>`, `gh issue edit <id> --add-assignee "@me"`.
2. **Branching Policy**: Never commit directly on `main`. Create `task/<id>-<short-description>`.
3. **Script-First Validation**: Always test via repository scripts (`./scripts/verify/*.sh`, `./scripts/setup/*.sh`, `./scripts/control/*.sh`) rather than ad-hoc Docker commands.
4. **Environment Gate (Rule 13)**: If no `.env` file exists on the host, **STOP**.
5. **Walkthrough Documentation**: Write `docs/YYYY-MM-DD-ticket<id>.md` or `docs/epics/<epic>/YYYY-MM-DD-ticket<id>.md`.
6. **Mandatory Pre-Commit Review Gate**: Stop and present the walkthrough summary and preview URLs to the human developer. Never commit or push without explicit approval.
7. **Post-Approval Commit & PR**: Commit with front-loaded ticket number `[#<id>] <type>(<plane>): <desc>` and Antigravity co-authorship. Open PR with attribution banner. Always **Squash and Merge**.

---

## Inviolable Architectural Guardrails

- **Rule 1 (Memory Plane Purity)**: `/memories` is strictly reserved for human-auditable OKF Markdown files. No SQLite, vector indices, or caches.
- **Rule 2 (Inference Boundary)**: Host Ollama is loopback-only (`127.0.0.1:11434`). Agent plane must route strictly through LiteLLM (`http://host.docker.internal:4000/v1`).
- **Rule 3 (Hardware Serialization)**: LiteLLM must enforce `max_parallel_requests: 1` to prevent LPDDR5x bandwidth thrashing.
- **Rule 4 (Host Sandboxing)**: Docker socket (`docker.sock`) must never be mounted into the agent container.
- **Rule 5 (Secret Protection)**: Never commit `.env` or sensitive API keys.
- **Rule 6 (Database Isolation)**: `brainsos-infra-litellm-db` is strictly for LiteLLM. Never share schemas, connection strings, or networks with other services.
- **Rule 7 (Context Compartmentalization)**: Never disclose backend infrastructure names in agent persona documents.
- **Rule 8 (Script-Driven Discipline)**: Zero ad-hoc container or host patching. Everything codified in `scripts/*.sh`.
- **Rule 9 (Multi-Tenant Partitioning)**: Declarative authority in `agents.yaml`. Standalone domain packages in `/packages/`.
- **Rule 10 (Egress Token Injection)**: Zero ambient credentials in containers. All egress routed through proxy with in-transit injection.
- **Rule 11 (Separation of Build & Record)**: Lab work resides strictly in `project_mJ`. Core coding agents do not author private fleet records.
- **Rule 12 (Sub-Agent Persona Isolation)**: Decoupled persona hierarchy. Conversational agents act as orchestrators, never producing raw code contaminated with chatter.
- **Rule 13 (Execution Environment Gate)**: Missing `.env` halts all execution scripts.
- **Rule 14 (Two-Repository Architecture)**: Open-source stateless platform core separated from private fleet state.
