# brainsOS: Strategic Planning & Epic Management Protocol (`PLAN.md`)

> **Authoritative Protocol**: See [`PLANNING.md`](PLANNING.md) for the complete planning lifecycle, two-repository routing, 3-step GitHub-native Epic standard, and backlog hygiene protocol.
>
> **Execution Protocol**: See [`AGENTS.md`](AGENTS.md) for ticket claiming, branching policy, script-first validation, and pre-commit review gates.

---

## The Core Product & Defect Tracks

### 1. Feature Track: Ideas ➔ Epics ➔ Sub-issues
```text
💡 Ideas (Backlog)  ──[/plan grooming]──>  📦 Epics (Active Milestones)  ──[decomposition]──>  🔨 Sub-issues (Execution via AGENTS.md)
```
- **💡 Ideas (`idea`)**: Lightweight concept captures registered in `Backlog / Future Research`. Low-friction, no heavy scoping required.
- **📦 Epics (`epic`)**: Multi-day / multi-component parent containers tracking 3–5 atomic child deliverables via native GFM task lists (`- [ ] #123`).
- **🔨 Sub-issues (`feature`, `task`, `security`, `infra`)**: Atomic, single-deliverable tasks executed strictly under [`AGENTS.md`](AGENTS.md) (branch `task/<id>-*`, test scripts, pre-commit review).

### 2. Defect Track: Bugs / Defects
```text
🐛 Bug Report (`bug` | `Bugs / Defects`)  ──[triage]──>  🛠️ Fix Ticket (`task/<id>-fix-...`)  ──[regression test]──>  ✅ Verified & Closed
```
- **🐛 Bugs (`bug`)**: Functional regressions, broken assertions, or unexpected crashes cataloged in `Bugs / Defects`. Blockers (P0) fast-track into active sprint milestones; non-blockers tracked until prioritized.

---

## The Master Planning Intent Router (`/plan`)

All planning workflows begin at `/plan`, which operates as an intelligent intent router:

```text
                                 ┌───────────────────────────────────────┐
                                 │       /plan (Intelligent Router)      │
                                 │  Classifies Intent & Dispatches Plan  │
                                 └──────────────────┬────────────────────┘
                                                    │
                 ┌──────────────────────────────────┼──────────────────────────────────┐
                 ▼                                  ▼                                  ▼
 ┌───────────────────────────────┐  ┌───────────────────────────────┐  ┌───────────────────────────────┐
 │          plan.epics           │  │            plan.ux            │  │           plan.copy           │
 │   Strategic Epics & Roadmap   │  │   UI/UX Prototypes & Mocks    │  │ Public Copy, Goals & README   │
 │ Decomposition, Tasks, Repos   │  │  Tokens, Iframes, Live Server │  │   "The Technical PR Guy"      │
 └───────────────────────────────┘  └───────────────────────────────┘  └───────────────────────────────┘
```

You can either pass a natural language request to `/plan` (which evaluates intent and routes automatically) or directly invoke a specialized planner:

1. **📦 `plan.epics` (`/plan:epics` | `/plan.epics`) — Strategic Epics & Roadmap Decomposition**
   - *Direct Invocation*: `/plan:epics Let's plan the next Epic for [feature/initiative] according to PLANNING.md.`
   - *Auto-Routing Trigger*: Feature roadmaps, milestone grooming, multi-task decomposition, two-repository split (Rule 11 & 14), backend systems, database schemas.
   - *Workflow*: Context audit ➔ Two-repo routing ➔ 3-step epic decomposition (3–5 child issues) ➔ Plan artifact approval.

2. **🎨 `plan.ux` (`/plan:ux` | `/plan.ux`) — UI/UX Prototyping & Mockup Alignment**
   - *Direct Invocation*: `/plan:ux Let's design the visual mockup and prototype for [feature/portal].`
   - *Auto-Routing Trigger*: UI/UX, layouts, split logins, floating dock ("Dockey"), iframe subsystems, CSS/tokens, interactive HTML prototypes.
   - *Workflow*: Design interview ➔ Token codification (`DESIGN.md`) ➔ Photorealistic mockups ➔ Interactive prototype (`stitch/`) ➔ Live preview (`:3033`).

3. **📢 `plan.copy` (`/plan:copy` | `/plan.copy`) — Public Relations, Copy & Goals ("The PR Guy")**
   - *Direct Invocation*: `/plan:copy Let's update the README and formulate goals for [milestone].`
   - *Auto-Routing Trigger*: Public positioning, README hero/topology, release notes, changelogs, developer advocacy, milestone goals.
   - *Workflow*: Technical extraction ➔ Milestone narrative ➔ README auditing ➔ Release notes kit ➔ Human review gate.

