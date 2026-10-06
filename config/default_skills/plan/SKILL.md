---
name: plan
description: >-
  Master planning router (/plan) that analyzes incoming requests, classifies intent into Epics/Roadmap, UI/UX Design, or PR/Copy, and dispatches to specialized planners (/plan:epics, /plan:ux, /plan:copy).
  Use this skill whenever the user invokes "/plan", asks a general planning question, or requires automatic routing to the appropriate planning archetype.
version: "1.0.0"
tags:
  - router
  - planning
  - dispatcher
  - workflow
triggers:
  - "/plan"
  - "plan"
  - "planning"
---

# `/plan` — The Master Planning Intent Router

The `/plan` command serves as the **front-door intent router** for all planning, architecture, design, and developer advocacy workflows in **brainsOS.ai**.

Instead of executing a monolithic planning protocol, `/plan` evaluates the incoming user request, classifies the intent, and automatically dispatches to the appropriate specialized planning archetype:

```
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

---

## 1. Intent Classification & Routing Rules

When invoked with a prompt (e.g. `/plan <prompt>` or conversational planning requests), evaluate the query against the following classification heuristics:

### Route A: Strategic Epics & Roadmap Decomposition ➔ `plan.epics` (`/plan:epics` or `/plan.epics`)
- **Matching Intent**: Multi-day engineering initiatives, architectural breakdowns, backlog grooming, milestone scoping, two-repository split (Rule 11 & Rule 14), issue pruning, task lists, or infrastructure changes.
- **Trigger Keywords**: `epic`, `roadmap`, `milestone`, `decompose`, `break down`, `tickets`, `issues`, `tasks`, `backlog`, `sprint`, `repository`, `sub-issues`, `database`, `backend`, `infra`, `architecture`.
- **Action**: Immediately announce the route to the user and execute the 4-phase protocol from [`plan.epics`](../plan.epics/SKILL.md):
  1. Audit active milestones, open issues, and PRs via `gh issue list`.
  2. Route components between `brainsOS.ai` (platform) and the private fleet repository (`$BRAINSOS_DATA_DIR`).
  3. Decompose into 3–5 atomic child issues (`infra`, `security`, `feature`).
  4. Present structured implementation plan artifact for human approval.

---

### Route B: UI/UX Prototyping & Visual Mockups ➔ `plan.ux` (`/plan:ux` or `/plan.ux`)
- **Matching Intent**: Visual interfaces, layouts, design systems, CSS/tokens, interactive HTML/JS prototypes, windowing paradigms, floating docks, or embedded iframe subsystems.
- **Trigger Keywords**: `ux`, `ui`, `design`, `mockup`, `prototype`, `css`, `tokens`, `layout`, `split`, `login screen`, `dock`, `dockey`, `canvas`, `portal`, `iframe`, `theme`, `dark mode`, `stitch`.
- **Action**: Immediately announce the route to the user and execute the 5-step workflow from [`plan.ux`](../plan.ux/SKILL.md):
  1. Conduct design alignment interview (viewports, windowing, taxonomy).
  2. Codify tokens in `docs/epics/<epic>/DESIGN.md`.
  3. Generate clean renders via `generate_image` (no floor reflections, 3D cyber grid).
  4. Build interactive prototype in `docs/epics/<epic>/stitch/` with persistent dock.
  5. Serve on port `3033` and provide clickable preview links.

---

### Route C: Public Relations, Copy & Goals ("The PR Guy") ➔ `plan.copy` (`/plan:copy` or `/plan.copy`)
- **Matching Intent**: Public developer documentation, `README.md` positioning, milestone goals, release notes, changelogs, marketing copy, or technical storytelling.
- **Trigger Keywords**: `copy`, `pr`, `readme`, `positioning`, `goals`, `release notes`, `changelog`, `announcement`, `pr guy`, `public facing`, `marketing`, `developer advocacy`, `open source`.
- **Action**: Immediately announce the route to the user and execute the 5-step workflow from [`plan.copy`](../plan.copy/SKILL.md):
  1. Extract technical feats and hardware grounding (GX10, GB10, ARM64 parity).
  2. Formulate concise milestone goals and developer narrative.
  3. Audit `README.md` hero section, badges, and quickstart commands.
  4. Draft changelog and release notes.
  5. Present copy plan artifact for human review.

---

## 2. Interactive Router Menu (Fallback)

If `/plan` is invoked without arguments or with ambiguous intent, present the operator with the interactive Planning Router Menu:

```markdown
### 🧭 brainsOS Planning Router (`/plan`)

Please specify your planning objective or select a specialized archetype:

1. **📦 `plan.epics` (`/plan:epics` | `/plan.epics`) — Strategic Epics & Roadmap Decomposition**
   *Break down complex multi-day initiatives into 3–5 atomic GitHub child issues, groom milestones, and route between platform and fleet repositories.*

2. **🎨 `plan.ux` (`/plan:ux` | `/plan.ux`) — UI/UX Prototypes & Visual Mockups**
   *Align on visual aesthetics, generate photorealistic mockups, codify design tokens, and build live interactive prototypes with persistent dock windowing.*

3. **📢 `plan.copy` (`/plan:copy` | `/plan.copy`) — Public Relations, Copy & Goals ("The PR Guy")**
   *Refine public copy, update `README.md`, formulate milestone goals, and translate deep systems engineering into compelling developer-first announcements.*

*Tip: You can invoke specialized planners directly (e.g. `/plan:epics`, `/plan:ux`, `/plan:copy`) or describe your goal in natural language to let `/plan` route automatically.*
```
