---
project: <Project name>
codename: <short-slug>
status: <e.g. Pre-alpha / Alpha / Beta 0.1.0 — publishing / Paused>
version: <e.g. v0.1.0>
owner: Justin St-Maurice
appliance: <e.g. DGX appliance (home lab) — ASUS Ascent GX10>
started: <YYYY-MM-DD>
last_updated: <YYYY-MM-DD>
tags: [agent-sdlc, <pattern-tag>, <pattern-tag>]
related_decks:
  - title: Injecting Agents into the SDLC
    file: Agent SDLC Process v1.1.pptx
  - title: The Autonomous Publishing Pattern
    file: Autonomous Publishing Pattern v1.pptx
---

<!--
CANONICAL COPY. This is the master template; a convenience mirror exists in the
OneDrive `Technical Counseling/Patterns` folder. Edit this one.

DIRECTORY LAYOUT
  docs/lab-work/projects/
    PROJECT-TEMPLATE.md          this file
    build-project-deck.py        the deck generator
    <project-codename>/          one directory per project
      project-<codename>.md      the report (build mirror; canonical in Patterns)
      Project <Name> — Status <date>.pptx   generated deck
      <other project assets>     diagrams, reference decks, screenshots

HOW TO USE THIS TEMPLATE
1. Create `projects/<codename>/` and copy this file to `project-<codename>.md`.
2. Sections 1–9 are the stable narrative. Rewrite them when the project's
   framing actually changes, not on every update.
3. Section 10 is the daily log. Newest entry at the TOP. Never edit an old
   entry — correct it in a later one. The log is the story of the project.
4. Anything you want to survive the project goes in section 8 (Lessons).
   The daily log is disposable narrative; section 8 is the durable payload.
5. Regenerate the deck with:
   python3 ../build-project-deck.py project-<codename>.md
   The generator reads the front matter, sections 1–9, and the three most
   recent log entries. It does not read anything else.

DAILY UPDATE PROTOCOL (what to hand Claude)
Paste a few sentences covering: what you intended, what happened, what broke,
what you changed, and what's next. Claude writes it into section 10 in the
entry format below, promotes any durable lesson into section 8, updates
`status` / `version` / `last_updated` in the front matter, and rebuilds
the deck.

DECK-SAFE WRITING
The generator sizes cards by row count, not by text length. Keep each
bold-led log field under roughly 350 characters, and put longer forensic
detail in plain paragraphs — the generator ignores those by design, so the
report can carry full detail while the deck stays legible.
-->

# <Project name>

## 1. One-liner

<One sentence a stakeholder could repeat accurately. What the agent does, on what
hardware, to what end.>

## 2. Why this project exists

**Research questions.** The project is an instrument; these are what it measures.

1. <Question — phrased so a result could contradict it.>
2. <Question>
3. <Question>

**What a result looks like.** <How you'll know you learned something: a pattern
another team can copy, a control that survives an attempted violation, a
measured number.>

## 3. Scope — what this is, and what it is not

| | |
| :--- | :--- |
| **It is** | <the experiment> |
| **It is not** | <the thing people will assume it is> |
| **The deliverable** | <pattern / framework / best-practice set — not the artifact itself> |

## 4. Architecture at a glance

| Layer | Component | Note |
| :--- | :--- | :--- |
| Hardware | <> | <> |
| Runtime | <> | <> |
| Control plane | <> | <> |
| Output surface | <> | <> |
| Feedback path | <> | <> |
| Observability | <> | <> |

**The loop.** <One paragraph: how output becomes feedback becomes the next
input, and where the human checkpoint sits.>

## 5. Related patterns and source material

| Artifact | Relationship |
| :--- | :--- |
| [Injecting Agents into the SDLC](Agent%20SDLC%20Process%20v1.1.pptx) | <how this project exercises or tests that pattern> |
| [The Autonomous Publishing Pattern](Autonomous%20Publishing%20Pattern%20v1.pptx) | <same> |
| <repo / doc / ticket> | <same> |

## 6. Current state

**Release.** <version — what it can actually do, stated without ambition.>

**Working.** <>

**Not working.** <>

**In flight today.** <>

## 7. Milestones

| Date | Milestone | Status |
| :--- | :--- | :---: |
| <YYYY-MM-DD> | <> | ✅ / 🟡 / 🔴 |

## 8. What I've learned

Durable lessons, promoted out of the daily log. Each one should be transferable
to a project that has nothing to do with this one.

| # | Lesson | Where it came from |
| :--- | :--- | :--- |
| L1 | <> | <YYYY-MM-DD> |

## 9. Open questions and risks

| Item | Type | Note |
| :--- | :---: | :--- |
| <> | Question / Risk | <> |

## 10. Daily log

<!-- Newest first. Copy this block for each new entry. -->

### <YYYY-MM-DD> — <five-word headline>

**Intent.** <What I set out to do.>

**What happened.** <Plainly. Including the parts that didn't work.>

**Change made.** <What I altered in response — config, persona, topology, prompt.>

**Lesson.** <What this generalises to. Promote to section 8 if durable.>

**Next.** <The very next action.>
