# brainsOS: Strategic Planning & Epic Management Protocol (`PLAN.md`)

> **Authoritative Protocol**: See [`PLANNING.md`](PLANNING.md) for the complete planning lifecycle, two-repository routing, 3-step GitHub-native Epic standard, and backlog hygiene protocol.
>
> **Execution Protocol**: See [`AGENTS.md`](AGENTS.md) for ticket claiming, branching policy, script-first validation, and pre-commit review gates.

---

## The Core Flow: Ideas ➔ Epics ➔ Sub-issues

```text
💡 Ideas (Backlog)  ──[/plan grooming]──>  📦 Epics (Active Milestones)  ──[decomposition]──>  🔨 Sub-issues (Execution via AGENTS.md)
```

1. **💡 Ideas (`idea`)**: Lightweight concept captures registered directly in `Backlog / Future Research`. Low-friction, no heavy scoping required.
2. **📦 Epics (`epic`)**: Multi-day / multi-component parent containers tracking 3–5 atomic child deliverables via native GFM task lists (`- [ ] #123`).
3. **🔨 Sub-issues (`type:*`)**: Atomic, single-deliverable tasks executed strictly under [`AGENTS.md`](AGENTS.md) (branch `task/<id>-*`, test scripts, pre-commit review).

---

## Quick Reference: Initiating a Planning Session (`/plan`)

When capturing ideas, planning epics, or grooming backlogs, invoke:

```text
/plan Let's review our ideas in Backlog / Future Research and plan the next Epic for [feature/initiative] according to PLANNING.md.
```

The agent will automatically:
1. **Audit Context**: Dump and analyze current issues, ideas in backlog, active branches, and code state.
2. **Route Repositories**: Decide between `brainsOS.ai` (platform core) and `project_mJ` (private fleet).
3. **Groom Ideas to Epics**: Promote ideas into candidate Epics and decompose into 3–5 atomic child tasks following the 3-step standard.
4. **Align Milestones**: Assign active milestones (`MVP v0.1`, `v0.2 Security`, `v0.3 Governance`, `Backlog / Future Research`).
5. **Present Plan Artifact**: Request human approval before modifying code or creating issues.
