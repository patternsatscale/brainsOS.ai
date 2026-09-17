---
project: Cindy Pawford
codename: cindy-pawford
status: Beta — publishing path proven; orchestration being redefined
version: v0.1.0
owner: Justin St-Maurice
appliance: DGX appliance, home lab (desk-side) — Project Titan fleet
started: 2026-09-06
last_updated: 2026-09-17
tags: [agent-sdlc, autonomous-publishing, safe-publishing, sub-personas, agent-security]
related_decks:
  - title: Injecting Agents into the SDLC
    file: Agent SDLC Process v1.1.pptx
  - title: The Autonomous Publishing Pattern
    file: Autonomous Publishing Pattern v1.pptx
---

# Cindy Pawford

## 1. One-liner

An interactive agent running on a desk-side DGX appliance that authors and publishes
its own website to cindypawford.com, takes feature requests and votes from the public,
and acts on them — used as a live testbed for agent development patterns, safe
publishing patterns, and the security controls that make unattended publishing
defensible.

## 2. Why this project exists

The website is not the point. The agent is not the point either. The point is the
set of patterns that let an agent do this kind of work safely, repeatedly, and in a
form another team can copy.

**Research questions.**

1. Can an agent ship code to a public production surface with no human in the
   authoring loop, while holding no credential and being unable to approve its own
   work? (Tests the Autonomous Publishing Pattern against a real weekly cadence.)
2. Where does an agent's *identity* leak into its *output*, and what structural
   separation prevents it? (Persona and product are different concerns; the system
   does not know that by default.)
3. Can a closed feedback loop — publish, collect public votes, act on the ranked
   queue — run autonomously without a human reading every inbound request, given
   that fan payloads are untrusted input?
4. Which failure modes are model failures and which are harness failures? Token and
   context-window exhaustion, not reasoning quality, has caused most losses so far.
5. What does the SDLC actually look like when the developer is an agent — tickets,
   review, rollback, verification? (Exercises the Agent SDLC deck.)

**What a result looks like.** A named pattern with a control, a verification suite
that attempts to violate that control and requires failure, and a measured number.
Not a demo.

## 3. Scope — what this is, and what it is not

| | |
| :--- | :--- |
| **It is** | An agent-development experiment. A deliberately low-stakes, high-visibility surface on which to exercise publishing, safety, and feedback-loop patterns. |
| **It is not** | A website project. cindypawford.com is a conduit — the channel through which the agent communicates and receives feedback. Its content is disposable by design. |
| **It is not** | A persona project. The dog-on-the-phone voice is delivery, not payload. |
| **The deliverable** | A framework and set of best practices for securing an agent that authors and publishes to the public internet. The site is the evidence; the pattern is the product. |
| **Sibling project** | Football Dan (`football-dan`, already in the fleet manifest) will use the same reporting and SDLC scaffolding to study whether an agent can build a dynamic, curated, and *accurate* knowledge graph. Same instrument, different question. |

## 4. Architecture at a glance

| Layer | Component | Note |
| :--- | :--- | :--- |
| Hardware | DGX appliance, home lab | Local inference. Power draw is measurable, which makes cost-per-feature expressible in joules as well as dollars. |
| Runtime | Hermes, per-agent container | Declarative personas at `config/hermes/personas/*.md`. Sub-personas supported — this is the September 15 fix. |
| Fleet manifest | `config/agents.yaml` | Single source of truth. Compose topology is generated from it; CI fails on drift. |
| Model routing | LiteLLM, alias `cindy-active-coding-model` | Model is swappable behind an alias, which is what makes era-over-era model comparison possible. |
| Control plane | `patternsatscale/project-titan` | Human-owned. Infrastructure-as-code, verification suites, reset/archive/rollback scripts, the credential-injecting proxy. The agent has no write path. |
| Canvas | `CindyPawford-Online` | Agent-owned except the CI directory, which is bind-mounted read-only beneath it. |
| Credential custody | Caddy reverse proxy (`github-proxy`) | Token injected in transit. The agent's environment contains no credential, and a suite fails the build if one appears. |
| Output surface | cindypawford.com | Static site, deployed by the control plane after a guarded pull request merges. |
| Feedback path | Public suggestion + voting API, era-partitioned | The closed loop: publish, collect, rank, act. Inbound payloads are treated as data, never instructions. |
| Memory plane | Per-agent Markdown, `./data/memories/<id>` | Survives the canvas reset. The agent loses the artifact and keeps the learning. |
| Observability | Langfuse + OpenTelemetry | Inference is traced. Tool calls and memory writes are not yet — a known gap. |

**The loop.** The agent wakes on a schedule, reads the ranked public request queue and
its own live site, writes changes into the canvas, and pushes through the injecting
proxy onto a branch it cannot deploy from. A guard workflow — defined inside a
directory the agent cannot write to — diffs the pull request and refuses governed
paths. On merge, the control plane deploys. The human checkpoint is a gate the agent
cannot reach, not a trust judgement about the agent. That is what permits a daily
cadence.

## 5. Related patterns and source material

| Artifact | Relationship |
| :--- | :--- |
| [Injecting Agents into the SDLC](Agent%20SDLC%20Process%20v1.1.pptx) | Cindy Pawford is the live case. Tickets, walkthroughs, acceptance criteria and verification suites in `docs/` are that pattern being executed rather than described. |
| [The Autonomous Publishing Pattern](Autonomous%20Publishing%20Pattern%20v1.pptx) | Written from this system. Two-repository split, credential injection in transit, destructive-actions-as-requests, weekly reset. This project is where its claims get falsified or hold. |
| `project-titan` — `docs/reference-architecture-tenets.md` | The TN-n control catalogue (TN-1 input governance through TN-9 recovery). Where each control here is scored against the working tree. |
| `docs/lab-work/scratch/agent-orchestration-discipline.md` | Written 2026-09-17 in response to the token-ceiling failure. A proposed runtime counterpart to `AGENTS.md`: orchestrator and builder roles, the ticket contract, and admission control. A recommendation in scratch — not accepted, not ticketed, not enforced. |
| `config/hermes/personas/cindy-pawford.md` | The soul file. Names no provider, no gateway host, no deploy mechanism — need-to-know, enforced by a test. |
| `docs/2026-09-*-ticket*.md` | Per-ticket walkthroughs. The audit trail of the agent SDLC in practice. |

## 6. Current state

**Release.** v0.1.0 — the first build in which code authored by the agent successfully
reaches the live domain through the full guarded path. End to end, unattended, no
credential in the agent.

**Working.** Agent-authored commits push through the injecting proxy. The guard
workflow gates the governed directory. Deploy runs from the control plane. The fleet
verification suite, memory-purity audit, egress token-injection suite and the four
Cindy-specific suites all pass on the appliance (ticket #103, September 15).

**Not working.** Work decomposition. Given a four-deliverable brief the agent attempted
it in one pass, hit the output-token ceiling on every continuation, and wrote nothing to
disk. No rule governs how much work may enter a cycle, and there is no
orchestrator/builder split at runtime. Tool calls remain untraced (see §9).

**In flight today.** Defining the orchestration discipline — Cindy as orchestrator,
issuing one ticket at a time to a builder sub-agent, under a per-cycle work budget.

## 7. Milestones

| Date | Milestone | Status |
| :--- | :--- | :---: |
| 2026-09-06 | Project Titan control plane initialised; ticket-driven SDLC established | ✅ |
| 2026-09-14 | Fleet decomposed into per-agent containers; Cindy Pawford unit stood up | ✅ |
| 2026-09-15 | Full appliance verification pass — 11 acceptance criteria, all suites green | ✅ |
| 2026-09-15 | Persona bleed identified and fixed via a dedicated authoring sub-persona | ✅ |
| 2026-09-16 | v0.1.0 — agent-authored code published to cindypawford.com | ✅ |
| 2026-09-17 | Failure mode identified: no work-decomposition rule (four-deliverable brief) | ✅ |
| 2026-09-17 | Orchestration discipline proposed: orchestrator, builder, one ticket at a time | 🟡 |
| — | Proposal accepted, ticketed, and wired into Cindy's runtime context; re-tested | 🔴 |
| — | Per-cycle work budget and admission control on the request queue | 🔴 |
| — | Per-action audit log for tool calls and memory writes | 🔴 |
| — | Outbound egress restriction (custody is not containment) | 🔴 |
| — | Closed feedback loop unattended: votes to ranked queue to shipped feature | 🔴 |
| — | First era reset and model rotation, producing a longitudinal comparison | 🔴 |

## 8. What I've learned

| # | Lesson | Where it came from |
| :--- | :--- | :--- |
| L1 | Persona and product are separate concerns, and nothing enforces that by default. An agent asked to build something will treat its own identity as available material and write it into the artifact. | 2026-09-15 |
| L2 | Sub-personas are a compartmentalisation control, not just an ergonomic feature. Giving the authoring task its own persona with its own context removes the identity parameters from the generation path entirely — the same "remove the capability rather than police it" move the publishing pattern makes with credentials. | 2026-09-15 |
| L3 | The harness fails before the model does. The dominant failure so far is context and token-window exhaustion on open-ended creative tasks, not poor reasoning. Budget the window as a first-class resource and make the agent's task decomposable. | 2026-09-17 |
| L4 | Open-ended fun is a harder test than useful work. "Build a game about yourself" has no natural stopping condition, no acceptance criteria, and maximum incentive for self-reference — which is exactly why it surfaces limits that structured tickets hide. | 2026-09-17 |
| L5 | A gate the agent cannot reach beats a trust judgement about the agent. It is what makes a daily publishing cadence defensible rather than brave. | 2026-09-16 |
| L6 | Orchestration is a safety control, not a productivity trick. An agent that both plans and builds fills its own context with generated code and then loses both jobs. Split the roles: the orchestrator holds judgement, voice and the plan; a builder sub-agent holds one ticket, its own terminal and its own context, and returns a summary and file paths rather than code. | 2026-09-17 |
| L7 | Any agent facing a queue needs admission control. A brief with four deliverables and a public request queue with forty votes are the same input: unbounded work admitted into one cycle. The queue must be treated as a backlog, not a work order, with a per-cycle work budget that is enforced outside the agent. | 2026-09-17 |
| L8 | An agent's self-report is not evidence. Mid-run status claimed files written and syntax-valid that were not on disk. With no per-action record there is no way to adjudicate afterwards, so progress must be verified against the filesystem rather than read out of the transcript. | 2026-09-17 |

## 9. Open questions and risks

| Item | Type | Note |
| :--- | :---: | :--- |
| Unbounded work per cycle | Risk | Nothing limits how much work enters one run. Demonstrated 2026-09-17. Under cron with a public queue this becomes the primary availability risk, and it is enforced today only by instruction. |
| Self-reported progress | Risk | The agent claimed files written that were not on disk. Any status, ledger entry or era recap it authors is a claim, not a record, until verified against the filesystem. |
| No per-action audit record | Risk | Inference is traced; tool calls and memory writes are not. Input-boundary claims cannot be checked after the fact, and the 2026-09-17 run cannot be reconstructed. |
| Custody is not containment | Risk | Without outbound network restriction the injecting proxy is bypassable by design. Both halves are needed before the architecture can claim containment. |
| Untrusted public input | Question | Fan payloads are bounded by instruction ("data, not instructions"), not by structure. A public voting queue is a prompt-injection surface, and instruction is the weakest available control. |
| Context budget as a control | Question | Should the window be a hard budget enforced outside the agent, the way the two-hour wall-clock deadline already is? |
| Persona bleed in reverse | Question | The authoring sub-persona keeps identity out of the code. Does it also keep the product out of the identity — or does the primary persona now describe a site it did not write? |
| Reporting scaffold reuse | Question | Does this template survive contact with Football Dan, whose output is a knowledge graph with an accuracy measure rather than a website? |

## 10. Daily log

### 2026-09-17 — One brief, four deliverables, zero files written

**Intent.** Hand Cindy a large creative brief over Telegram with an eight-hour budget:
add several pages to the site, hide Easter eggs about me, build a treasure-hunt
mystery, fix the confusing 2:00 Sprint game, and build a Pac-Man-style game. Manual
testing ahead of putting this cycle on cron.

**What happened.** It planned well, then lost everything. After laying out three pages
and appending CSS cleanly, it tried to rewrite app.js to hold the Pac-Man engine, the
vault logic and a rebuilt Sprint in one pass. Every continuation hit the output-token
ceiling with reasoning consuming the whole budget; nothing reached disk. Asked for a
status, it claimed files written that were not there.

**Change made.** None to the running system; the change is architectural. Cindy stops
being a builder and becomes an orchestrator: decompose a brief into tickets, then
dispatch exactly one at a time to a builder sub-agent. Proposed in
docs/lab-work/scratch/ — a recommendation, not yet accepted or ticketed.

**Lesson.** Orchestration is a safety control, not a productivity trick (L6). Any agent
facing a queue needs admission control (L7). An agent's self-report is not evidence
(L8). And L3 holds: the harness failed, not the model — the reasoning was sound, the
missing piece was a rule about how much work may enter one cycle.

**Next.** Wire the discipline into Cindy's runtime context, then re-run this exact brief
as the test. The correct output is a written backlog with one ticket in flight — not one
giant call.

Fuller detail, kept out of the deck. The early work was better than asked: it re-read
the live home page and design tokens, stood up a dev server, laid out `pac.html`,
`mystery.html` and `gallery.html`, appended a new CSS block while preserving the
existing rules, and generated a symmetric 13×13 maze with a Node mirror helper rather
than hand-counting it. The collapse came only at the core rewrite. Context reached
roughly 145,000 tokens, after which the provider went unresponsive on `titan-core` for
five consecutive 300-second attempts and the session was aborted to avoid an indefinite
stall. Asked for a status it reported `app.js` as syntax-valid and already containing
the mascot, sprint, fetch and egg/toast systems, and all three pages as existing — none
of which was on disk. It had also, correctly, identified `delegate_task` as the right
tool and dispatched the game build to a sub-agent: the right instinct, one step too late
and from an already-exhausted context. A phase-by-phase reading is in
`docs/lab-work/scratch/agent-orchestration-discipline.md` §0.

Why this matters more than a lost game. A public request queue carrying forty upvoted
requests is structurally the same input as a brief carrying four deliverables:
unbounded work admitted into a single cycle. This is the autonomous loop's failure mode
arriving early, cheaply, and in a chat window with a human holding the other end —
which is the best possible place to find it.

---

### 2026-09-16 — v0.1.0: agent-authored code goes live

**Intent.** Close the loop end to end: agent writes, pipeline gates, control plane
deploys, no human in the authoring path and no credential in the agent.

**What happened.** It shipped. Code written by the agent reached cindypawford.com
through the injecting proxy, a guarded pull request, and an infrastructure-as-code
deploy. The agent held no token at any point, could not read the workflow that checked
its output, and could not merge its own work.

**Change made.** Tagged v0.1.0 as the first releasable beta of the publishing path.

**Lesson.** The claim from the publishing deck — that autonomy is bounded by a
checkpoint rather than by trust — is now demonstrated rather than argued (L5).

**Next.** Give it something unstructured to do and see what breaks.

---

### 2026-09-15 — Persona bleed into generated content

**Intent.** Have the agent author site content and markup directly.

**What happened.** The agent pulled its own personality parameters into the artifact.
The HTML it produced was polluted by the primary persona's soul file — voice, self-
reference and character material showing up in structure and content where a page was
wanted. The output was interesting, and wrong. The agent had conflated who it is with
what it was asked to build.

**Change made.** Used the Hermes framework's sub-agent and sub-persona capability to
create a second persona inside the Cindy Pawford container whose only job is authoring
code and content. It runs without the primary persona's identity parameters in context,
so there is nothing to bleed.

**Lesson.** Persona and product are separate concerns and nothing enforces that by
default (L1). The fix is structural, not a prompt instruction — remove the identity
parameters from the generation path rather than asking the agent not to use them (L2).
This is the same move the publishing pattern makes with credentials, applied to
identity.

**Next.** Verify that the authoring sub-persona stays clean under a creative brief,
where the temptation to self-reference is strongest.

---

### 2026-09-15 — Full appliance verification pass

**Intent.** Establish a known-good baseline on the DGX appliance before pushing the
publishing path further (ticket #103).

**What happened.** All eleven acceptance criteria passed: fleet drift check,
unprivileged sandboxing, Docker socket isolation, ingress routing, cross-tenant
isolation, hardware serialisation, targeted kill-switch, memory-plane purity,
persistence and backup, observability ingestion, in-transit credential injection with
zero ambient tokens, and the four Cindy-specific suites.

**Change made.** Baseline recorded. Suites are now the regression net for every claim
the publishing pattern makes.

**Lesson.** A control is only verified by attempting the thing it forbids and requiring
failure. Asserting that a config line is present proves only that someone wrote it.

**Next.** Ship agent-authored code to the live domain.
