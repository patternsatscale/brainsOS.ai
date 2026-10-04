---
name: plan.epics
description: >-
  Strategic planning, 3-step GitHub Epic decomposition, milestone management, and two-repository routing protocol (/plan:epics or /plan.epics).
  Use this skill whenever the user asks for "/plan:epics", "/plan.epics", "/plan:epic", "/plan.epic", requests to groom milestones,
  break down high-level initiatives into 3–5 atomic child issues, or route components between core and fleet repositories.
version: "1.0.0"
tags:
  - strategic-planning
  - epic-management
  - agile
  - github-issues
triggers:
  - "/plan:epics"
  - "/plan.epics"
  - "/plan:epic"
  - "/plan.epic"
  - "plan epics"
  - "plan epic"
  - "epic decomposition"
  - "groom backlog"
---

# `plan.epics` — Strategic Planning & Epic Management Protocol

This skill enforces the core strategic planning, 3-step GitHub Epic decomposition, and milestone management protocol defined in [`PLANNING.md`](../../../../PLANNING.md).

It is triggered directly via `/plan:epics` or `/plan.epics` (or `/plan:epic`), or automatically dispatched by the `/plan` intent router whenever a planning question involves system architecture, multi-ticket decomposition, or roadmap alignment.

---

## The 4-Phase Planning Protocol

### Phase 1: Context & Backlog Auditing
1. Audit existing issues, bugs in `Bugs / Defects`, ideas in `Backlog / Future Research`, and open branches:
   ```bash
   gh issue list --limit 30 --state open
   ```
2. Review target milestone scope (`MVP v0.1`, `v0.2 Security`, `v0.3 Governance`).
3. Identify stale or superseded tickets for pruning per §6 of `PLANNING.md`.

### Phase 2: Two-Repository Routing (Rule 11 & Rule 14)
Enforce strict separation between open-source core platform and proprietary fleet state:
- **`brainsOS.ai` (Platform Core)**: Open-source stateless containers, Python domain packages, Caddy ingress, Dashy dashboard, and verification harnesses.
- **Private Fleet Repository (`$BRAINSOS_DATA_DIR`)**: Proprietary agent personas (`souls/`), OKF Markdown memories, custom fleet manifests, and lab narratives.
- *Strict Rule*: Zero proprietary fleet state commits to open-source core.

### Phase 3: Sizing & 3-Step Epic Decomposition
1. **The 2-Day Sizing Rule**:
   - Initiatives requiring > 2 days of engineering become an **Epic** (`epic`).
   - Smaller discrete tasks (≤ 2 days) stand alone as atomic **Tickets** (`feature`, `task`).
2. **Atomic Child Tasks (Rule of 3–5)**:
   - Decompose Epics into 3–5 single-deliverable child issues.
   - Separate infrastructure (`infra`), security boundaries (`security`), and UI/UX (`feature`).
3. **GFM Task Checklist**:
   - Parent Epic must track child issues via GitHub Flavored Markdown checkboxes (`- [ ] #123`).

### Phase 4: Implementation Plan Artifact & Pre-Creation Gate
1. Draft the structured implementation plan artifact:
   - Visual mockups and topology diagrams.
   - Inviolable architectural guardrails.
   - Exact child task breakdown with acceptance criteria.
   - Automated and manual verification steps.
2. Stop and request explicit human approval before creating issues or modifying remote milestones.
