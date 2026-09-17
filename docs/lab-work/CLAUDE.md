# `docs/lab-work/` — Claude's working area

**Owner**: Claude (documentation, supervision and critique), working for Justin St-Maurice.
**Status relative to the repository**: Out of scope for the coding agent. See `AGENTS.md`
Rule 11.

---

## Separation of church and state

This directory exists to keep two jobs apart.

| | Builds the system | Documents and critiques it |
| :--- | :--- | :--- |
| **Who** | The coding agent (Antigravity, Gemini, and any future pair programmer) | Claude |
| **Where** | Everywhere in this repository *except* this directory | This directory, plus governance documents in `docs/` when asked |
| **Produces** | Application code, scripts, configuration, infrastructure, tickets executed against acceptance criteria | Project reports, pattern write-ups, operating discipline specs, stakeholder decks, critique |
| **Must not** | Rewrite the record of what happened to match what it intended | Write or modify application code, scripts, or configuration |

The reason is the one already established elsewhere in this project: an actor that both
does the work and writes the account of the work has an unmanaged conflict of interest.
The 2026-09-17 failure made that concrete — the agent's own status report claimed files
written that were not on disk. Nobody was lying; a context under pressure produced a
plausible reconstruction of intended work. Keeping the narrator out of the build, and
the builder out of the narration, is cheap insurance against that class of error.

---

## Layout

```
docs/lab-work/
  CLAUDE.md                     this file — the contract for the directory
  projects/                     project reporting: shared tooling and templates
    PROJECT-TEMPLATE.md         canonical report template
    build-project-deck.py       deck generator (report markdown in, .pptx out)
    <codename>/                 one directory per project, all its assets
      project-<codename>.md     the report  (build mirror; canonical in Patterns)
      Project <Name> — Status <date>.pptx   generated deck
      <other assets>            diagrams, reference decks, screenshots
  scratch/                      proposals and recommendations for the source code
```

**The rule for the two levels.** Anything reusable across projects lives directly in
`projects/`. Anything that only makes sense for one project lives in
`projects/<codename>/`. A new project is a new directory — nothing else moves.

| Path | What it is | Canonical? |
| :--- | :--- | :--- |
| `CLAUDE.md` | The contract for this directory. | Yes |
| `projects/PROJECT-TEMPLATE.md` | Report template. Sits next to the generator that consumes it. | Yes — the `Patterns` copy is a reading mirror |
| `projects/build-project-deck.py` | Turns a report markdown file into a status deck. | Yes |
| `projects/cindy-pawford/project-cindy-pawford.md` | The Cindy Pawford report. | **No** — canonical copy in the OneDrive `Technical Counseling/Patterns` folder |
| `projects/cindy-pawford/Project Cindy Pawford — Status <date>.pptx` | Generated deck. Rebuildable; never hand-edited. | No — build artifact |
| `projects/cindy-pawford/Autonomous Publishing Pattern v1.pptx` | Reference copy of the published pattern deck. | No — canonical copy in `Patterns` |
| `projects/cindy-pawford/cindy-pawford-reference-architecture.html` | Reference architecture diagram. | — |
| `scratch/` | Proposals and recommendations *for* the source code. No authority over it. See below. | — |

Expected next project directory: `projects/football-dan/` — the knowledge-graph
accuracy study.

### `scratch/` — recommendations, not doctrine

Anything that reads like it belongs in the repository proper — an operating discipline,
a control specification, a proposed rule, a tenet redline — goes in `scratch/` first.

The distinction that matters: a document in `scratch/` is a **recommendation addressed
to a maintainer**, not a requirement addressed to a builder. It authorises nothing. A
coding agent that finds it must not build against it, and the presence of a rule there
is not evidence that the rule exists.

**Promotion path.** A maintainer accepts the proposal → it is filed as a GitHub Issue
→ a ticket implements and verifies it → the binding version lives outside `lab-work/`,
owned by the repository. Until all four have happened, it is a draft with an author's
opinion in it.

Current contents:

| File | What it proposes | State |
| :--- | :--- | :--- |
| `agent-orchestration-discipline.md` | Orchestrator/builder role split, ticket contract, decomposition rules, admission control, failure protocol. Written 2026-09-17 in response to the token-ceiling failure. | 🔴 Proposal. Not accepted, not ticketed, not implemented. |

### Why the report is mirrored rather than moved

The canonical project reports live in the OneDrive `Technical Counseling/Patterns`
folder, alongside *Injecting Agents into the SDLC* and *The Autonomous Publishing
Pattern*, because that is where the pattern library lives and where these documents get
read from. That folder is not reachable from the sandbox that runs the deck generator,
so a mirror lives here as build input.

**The mirror is downstream.** Edit the `Patterns` copy; the mirror is synced to match.
If the two ever disagree, `Patterns` wins.

---

## Working rules

1. **No application code from this directory.** Nothing here is imported, executed by,
   or depended upon by the running system. `build-project-deck.py` is documentation
   tooling: it reads markdown and writes a deck. Nothing in `apps/`, `scripts/`,
   `config/` or `packages/` may reference it.
2. **Generated artifacts are rebuildable, never hand-edited.** The deck is regenerated
   from the report. A deck edited by hand is a fork of the record.
3. **Claims are attributed.** Anything in a report that came from the agent's own
   transcript rather than from a verified artifact is labelled as a claim. See
   `scratch/agent-orchestration-discipline.md` §7.
4. **Governance documents are marked for enforcement status.** A rule written down is
   not a control. Specifications authored here carry the 🔴 planned marker until a
   mechanism enforces them and a suite attempts to violate them — the discipline already
   in `docs/reference-architecture-tenets.md`.
5. **Recommendations for the source code go in `scratch/`.** Claude does not write
   binding documents into the repository proper. Anything intended to govern code is a
   proposal until a maintainer promotes it through a ticket.
6. **The log is append-only in spirit.** Daily entries are not edited after the fact.
   Corrections go in a later entry, so the evolution of understanding stays visible.
   That record is the research output; tidying it destroys the thing being studied.
7. **No credentials, no secrets, no infrastructure detail that the fleet's own agents
   are kept ignorant of.** Need-to-know applies to documentation too — the personas
   deliberately name no provider, gateway host or deploy mechanism, and a stakeholder
   deck is not a reason to undo that.

---

## The daily update loop

The workflow this directory supports:

1. Justin pastes an update — what he intended, what happened, what broke, what changed,
   what's next.
2. Claude writes it into §10 of the project report (newest first), promotes any durable
   lesson into §8, and updates the front matter (`status`, `version`, `last_updated`).
3. Claude syncs the mirror here and regenerates the deck.
4. Structural changes to the project's framing (§§1–9) happen when the framing actually
   changes, not on every update.

New projects start by creating `projects/<codename>/` and copying
`projects/PROJECT-TEMPLATE.md` into it as `project-<codename>.md`. `football-dan` is
the next expected adopter.

---

## Known limitations of the tooling here

Recorded rather than fixed, so they are not rediscovered:

- **The deck generator sizes cards by count, not by text length.** Long entries in a
  section with many rows overflow their cards. The current workaround is editorial —
  keep bold-led log fields under roughly 350 characters, and put longer forensic detail
  in plain paragraphs, which the generator ignores by design.
- **Section numbers matter, titles do not.** The generator keys off `## <n>.` headings.
  Renumbering a report silently changes which slides appear.
- **The lessons and risks slides do not paginate.** Beyond roughly eight rows they will
  need splitting.
