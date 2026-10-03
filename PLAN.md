# brainsOS: Strategic Planning & Epic Management Protocol (`PLAN.md`)

> **Authoritative Protocol**: See [`PLANNING.md`](PLANNING.md) for the complete planning lifecycle, two-repository routing, 3-step GitHub-native Epic standard, and backlog hygiene protocol.
>
> **Execution Protocol**: See [`AGENTS.md`](AGENTS.md) for ticket claiming, branching policy, script-first validation, and pre-commit review gates.

---

## Quick Reference: Initiating a Planning Session (`/plan`)

When planning new features, epics, or roadmaps, invoke:

```text
/plan Let's review active milestones and plan the next Epic for [feature/initiative] according to PLANNING.md.
```

The agent will:
1. **Audit Context**: Dump and analyze current issues, active branches, and code state.
2. **Route Repositories**: Decide between `brainsOS.ai` (platform core) and `project_mJ` (private fleet).
3. **Decompose into Epics**: Apply the 3-step Epic standard (`epic` label, parent issue with GFM task list, GitHub Projects field).
4. **Align Milestones**: Assign active milestones (`MVP v0.1`, `v0.2 Security`, `v0.3 Governance`, `Backlog`).
5. **Present Plan Artifact**: Request human approval before modifying code or creating issues.
