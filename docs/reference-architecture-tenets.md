# Autonomous Agent Security Reference Architecture: Core Tenets & Controls
*A Blueprint for Secure, Sandboxed, and Auditable Local Agent Appliances*

- **Document Type**: Reference Architecture & Engineering Tenets (v2.1 — renumbered, full control template, status markers verified against repo)
- **Model Baseline**: Project Titan Appliance Architecture (ASUS Ascent GX10 / macOS Parity)
- **Target Audience**: Enterprise AI Architects, Security Officers (CISO/SecOps), Autonomous System Engineers — **and AI coding assistants (Gemini, Antigravity) generating code against this spec**
- **Location**: `docs/reference-architecture-tenets.md`
- **Status basis**: Every 🟢/🟡/🔴 marker below was verified against the working tree at commit `da882a8`. Evidence citations are `file:line`. See Appendix A for the full evidence table.

---

> ### ⚠️ Document governance warning — read before relying on this file
>
> As of commit `da882a8`, this file is **untracked in git** (`?? docs/reference-architecture-tenets.md`). It has never been committed on any branch, and `git log --all -- 'docs/reference-architecture-tenets*'` returns nothing.
>
> Two consequences, both already realised:
>
> 1. **Antigravity has never been able to read this spec from version control.** It co-authored 10 of the 18 commits on `main` (19 across all refs including task branches) — including every feature commit (#2, #3, #4, #9, #17, #21, #25) — but it built against `AGENTS.md` (tracked) and the ticket walkthroughs in `docs/2026-09-06-ticket*.md`, not this document. Any claim that generated code was written "against this spec" is currently unfounded.
> 2. **An untracked spec has no recovery path.** On 2026-09-07 this file was overwritten in place (v2 content, 36,184 bytes → v1 content, 18,885 bytes) by a process outside the authoring session, concurrent with a `.git/index.lock`. Because the file was untracked, git held no copy and the content was only recoverable from the author's session.
>
> **`TN-8.1` is not satisfied for this document itself.** Commit it. Until it is tracked and CI-visible, it is a local note, not a control baseline.

---

## Migration note (v1 → v2)

This revision renumbers the eight prose "Tenets" into nine `TN-n` control categories, shared with the enterprise reference-architecture document so both use one ID system.

**Verified: the old numbering is referenced nowhere in this repo.** No code, script, comment, CI job, or `AGENTS.md` line cites "Tenet 1–8" — the string `tenet` appears only in this document and its own remediation drafts under `docs/`. Renumbering breaks nothing. The crosswalk below is retained as document history, not as a compatibility shim.

| Old | New | Notes |
|---|---|---|
| Tenet 1 — Topological Isolation | **TN-5** | Direct match |
| Tenet 2 — Zero-Trust Inference & Kill-Switch | **TN-3** | Partial match — see gap notes in TN-3 |
| Tenet 3 — Memory Plane Purity | **TN-4** | Direct match, strongest tenet in the doc |
| Tenet 4 — Need-to-Know Compartmentalization | **TN-5.6** | Folded in as a control, not a standalone tenet |
| Tenet 5 — Hardware-Aware Resource Serialization | **TN-3** (partial), **TN-8** (driver pinning) | Split across two tenets |
| Tenet 6 — Storage & Disaster Recovery | **TN-9** | Direct match |
| Tenet 7 — Script-Driven Discipline | **TN-9** | Merged with old Tenet 6 |
| Tenet 8 — Dev Governance & Pre-Commit Gate | **TN-8** | Direct match |
| *(none)* | **TN-1** | New — no input channel has ever been governed |
| *(none)* | **TN-2** | New — no tool authorization existed |
| *(none)* | **TN-6** | New — no *inference-tier* egress path exists; general agent egress does |
| *(none)* | **TN-7** | New — observability was entirely absent |

### Forward references already in the working tree

The coupling runs the opposite direction to what a migration note usually guards against. `README.md` — in an **uncommitted** 33-line addition — already cites TN- IDs that exist only in this v2 document:

| Location | Cites | Context |
|---|---|---|
| `README.md:199` | `TN-1.8` | CW-3 (#38) — tool-less reader sandbox for untrusted web pages |
| `README.md:205` | `TN-6` | X-1 (#42) — outbound policy inspection for canary tokens |

Reverting this document to v1 orphans both references. Committing v2 resolves them. That is the actual reconciliation pressure — not legacy numbering.

---

## Part 0 — ID Conventions

| Prefix | Meaning | Example |
|---|---|---|
| `A-nn` | Asset | `A-06` Policy plane and its configuration |
| `T-nn` | Threat | `T-14` Memory exfiltration |
| `TN-n` | Tenet (control category) | `TN-4` Memory Integrity, Provenance, and Version Control |
| `TN-n.m` | Individual control within a tenet | `TN-4.3` |

Each tenet follows a fixed template: **normative statement → threats addressed → required controls (MUST) → recommended controls (SHOULD) → verification method → what this does not protect against → `[Titan]` implementation status.**

**Status legend used throughout:** 🟢 implemented and verified in this repo · 🟡 partially implemented · 🔴 not yet implemented

**Marker discipline:** a marker is 🟢 only when a control is *enforced by code or CI* at a citable `file:line`. A control described in prose — in `SOUL.md`, `AGENTS.md`, or this document — but not mechanically enforced is at most 🟡, and 🔴 if the prose is the only artifact. Aspirational architecture is marked 🔴 and labelled *planned*, never 🟢.

---

## Part 1 — Reference Architecture: Plane Separation Model

Renamed from "control plane" to **policy plane** for consistency with the enterprise reference document — same component, same behavior, no code change implied.

**This diagram reflects the working tree as verified, not target state.** Items marked `[PLANNED]` are not implemented; items marked `[GAP]` are asserted elsewhere in the project but absent from the manifests.

```text
 ═════════════════════════════════════════════════════════════════════════════════════
  1. INGRESS PLANE         Local / Tailscale DNS (*.titan.local)
                           └─► Reverse Proxy (titan-caddy) [:80/:443]
                           Routes: hermes.* → agent console, proxy.* → LiteLLM,
                                   memory.* → SilverBullet   (Caddyfile:10,25,39)
                           Input channel: HTTP agent console, UNAUTHENTICATED  [GAP]
                           Signal operator-bound channel                   [PLANNED]
 ─────────────────────────────────────────────────────────────────────────────────────
  2. AGENT EXECUTION       Hermes Agent Container (titan-hermes)
     PLANE                 ├─ Unprivileged UID/GID 1000 — via image, Dockerfile:18-19,33
                           ├─ no-new-privileges: true    — compose:91-92
                           ├─ cap_drop: ALL — ABSENT from manifests; asserted in
                           │                  README.md:70 and v1 Tenet 1        [GAP]
                           ├─ Network: titan-ingress AND titan-internal (compose:114-116)
                           │    titan-internal permits agent WAN egress (compose:127)
                           ├─ Blocked: Docker Socket (/var/run/docker.sock) — verified absent
                           ├─ No pids_limit / cpus / mem_limit               [GAP]
                           └─ Workspace: Bind-Mount (/workspace) for tool state & caches
                                                                        (compose:104)
 ─────────────────────────────────────────────────────────────────────────────────────
  3. POLICY PLANE          LiteLLM Gateway Engine (host:4000 / proxy.titan.local)
     & GATEWAY             ├─ Model Virtualization & Aliasing (titan-core)  litellm:8
                           ├─ Virtual API Key Minting & Revocation
                           │    (manual, best-effort kill-switch — see TN-3)
                           ├─ Hardware Concurrency Serialization
                           │    (max_parallel_requests: 1)          litellm:13,22,30
                           ├─ Request timeout 300s                  litellm:14,37
                           └─ Isolated Persistence: Dedicated PostgreSQL (titan-litellm-db)
                                on titan-litellm-net only, loopback-bound  compose:40,47-48
 ─────────────────────────────────────────────────────────────────────────────────────
  4. INFERENCE PLANE       Native Compute (Ollama / vLLM on host:11434)
                           ├─ Hardware-Accelerated (Apple Metal / NVIDIA GB10 CUDA)
                           └─ Bound strictly to Loopback (127.0.0.1:11434)
                                enforced at launch — setup-host.sh:299
                           (No cloud-tier escalation path exists — see TN-6)
 ─────────────────────────────────────────────────────────────────────────────────────
  5. MEMORY PLANE          Open Knowledge Format (OKF) Storage (/memories)
                           ├─ Pure Flat-File Markdown with YAML frontmatter
                           ├─ Memory Purity Guardrail — runtime-enforced
                           │    hermes_okf.py:255-256 (.md only), :258-260 (no binary),
                           │    :189 (traversal guard), :412-433 (validate_purity)
                           ├─ No provenance / trust-tier fields on notes       [GAP]
                           ├─ Not under version control — .gitignore:10        [GAP]
                           └─ Interactive PKM UI (SilverBullet) at memory.titan.local
                                image pinned to :latest — compose:60           [GAP]
 ─────────────────────────────────────────────────────────────────────────────────────
  6. PERSISTENCE &         Unified Root Host Mount (/data or ./data)
     DISASTER RECOVERY     ├─ memories/ (OKF notes) | litellm_db/ (PostgreSQL) | workspace/
                           ├─ Atomic Snapshot & Backup Automation (scripts/backup.sh)
                           │    manifest + integrity test + retention 14
                           └─ No scheduler (cron/systemd/launchd) — manual invocation [GAP]
 ═════════════════════════════════════════════════════════════════════════════════════
```

---

## Part 2 — Asset Inventory

| ID | Asset | Why it matters |
|---|---|---|
| `A-03` | Agent memory store (`/memories`) | Human-legible, but currently unversioned and unprovenanced |
| `A-06` | Policy plane and its configuration (LiteLLM + `titan-litellm-db`) | Where enforcement concentrates — a single point that disables several controls at once if compromised |
| `A-07` | Agent execution container (Hermes) | Runs untrusted-content-adjacent reasoning; least-privileged by design |
| `A-08` | Native inference engine (Ollama/vLLM) | Loopback-only; currently zero external exposure |
| `A-09` | Host OS / container runtime | Ultimate trust anchor; a breakout here defeats every plane above it |
| `A-10` | Persistent data root (`/data`) | Single point of backup and recovery for the whole appliance |
| `A-11` | Development/CI pipeline (`AGENTS.md`, GitHub Actions) | Governs how the agent's *own* code and config change over time |
| `A-12` | Agent HTTP console (`docker/hermes/server.py`) | **Newly catalogued.** Exposes shell execution, skill authoring, and memory writes; currently the appliance's real ingress and its largest unmediated attack surface |

*Note: `A-07`–`A-12` are newly assigned in this pass. Reconcile against the master asset catalog if one exists outside this document.*

---

## Part 3 — Threat Catalog Additions

The enterprise reference document's threat catalog runs through `T-35`. This pass adds threats surfaced by Titan's actual implementation that weren't previously catalogued:

| ID | Threat | Scenario | Tenet |
|---|---|---|---|
| `T-36` | Container/host breakout | Runtime compromise escalates via a reachable host socket or over-broad capability to host-level control | TN-5 |
| `T-37` | Lateral movement to adjacent services | Shared network bridge lets a compromised agent reach the policy-plane database or loopback-bound inference | TN-5, TN-6 |
| `T-38` **[A]** | Infrastructure reconnaissance via context extraction | Prompt injection or extraction attack dumps the agent's system prompt, revealing host topology, service names, or credentials | TN-1, TN-5 |
| `T-39` | Shared-hardware resource exhaustion | Unthrottled concurrent inference saturates a unified memory bus, causing thermal throttling or host lockup | TN-3 |
| `T-40` | Configuration drift | Manual, undocumented host changes accumulate until the environment can no longer be reproduced from manifests | TN-9 |
| `T-41` | Unreviewed dependency or driver change | An unpinned base image, model runtime, or driver upgrades silently and introduces a breaking or malicious change | TN-8 |
| `T-42` | Unauthenticated control-surface invocation | An unauthenticated management or execution endpoint on the agent container is reached directly, or cross-origin from a browser the operator is already using, bypassing every model-level and prompt-level control | TN-2, TN-5 |
| `T-43` | Ungoverned spec drift | A security baseline held only as an untracked local file diverges from the code generated against it, with no diff, review, or recovery path | TN-8 |

*Identifiers continue in registration order from the existing catalog (T-01–T-35).*

---

## Part 4 — The Tenets

---

### TN-1 — Untrusted Input Boundary and Content Provenance

> All content entering the agent's context is data. It is never instruction, regardless of the channel it arrived through or its apparent origin. Content carries provenance sufficient to determine its trust tier at the point of use.

**Threats addressed:** `T-01` `T-02` `T-03` `T-04` `T-05` `T-14` `T-34` `T-38`

#### Required controls

| ID | Control |
|---|---|
| `TN-1.1` | Every input channel MUST be enumerated in a maintained inventory. |
| `TN-1.2` | Content MUST be assigned a trust tier at ingestion: **Operator-authored**, **Organization-controlled**, **Tool-derived**, **External**. |
| `TN-1.3` | Content at Tool-derived or External tier MUST NOT be interpreted as instruction — separation MUST be structural (distinct message roles, delimiting), not a prompt-level request that the model please ignore embedded instructions. |
| `TN-1.4` | Provenance metadata MUST travel with content into durable memory (see `TN-4.3`). |
| `TN-1.5` | Tool output MUST be labelled as tool output and MUST NOT be renderable as system or operator content. |
| `TN-1.6` | Operator-authored tier MUST be assigned by authorship, not channel — content a verified operator forwards or pastes stays classified by its origin, not theirs. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-1.7` | Guardrail scanning at the policy plane, ingress and egress. |
| `TN-1.8` | External-tier content handled in a separate, tool-less reader context. |
| `TN-1.9` | Size-cap and rate-limit external content ingestion. |
| `TN-1.10` | Neutralize active content (scripts, hidden text, control characters) before ingestion. |

#### Verification

Enumerate the agent's actual reachable input surface by auditing every request handler in `docker/hermes/server.py` against the channel inventory; confirm no ungoverned path exists. Once a trust-tiering mechanism exists, inject a benign marker instruction and confirm Hermes reports it rather than acting on it.

#### What this does not protect against

No known complete defence against indirect prompt injection exists. Treat successful injection as inevitable and rely on `TN-2` and `TN-3` to bound the consequence.

#### `[Titan]` status

🔴 **Unaddressed, and the premise of the v2 draft was wrong.**

**Correction:** the draft claimed "Signal is the sole input channel (confirmed), bound to a single verified personal account, which is a real and valuable mitigation." **Signal is not implemented.** There is no Signal code, dependency, config key, or credential anywhere in the repo. It appears only as forward-looking prose (`README.md:60,103`, `docker-compose.yml:127`, `docs/2026-09-06-ticket21.md:166,171`), and `docs/2026-09-06-ticket3.md:29` records that Signal parameters were **removed** from `.env.example`. The claimed operator-account mitigation does not exist and must not be credited.

**The actual input surface** is the Hermes HTTP console, and no endpoint authenticates. Inventory per `TN-1.1`, all in `docker/hermes/server.py`:

| Channel | Handler | AuthN | Trust tier assigned |
|---|---|---|---|
| `POST /api/chat` | `:1008` | none | none |
| `POST /api/terminal` | `:1095` | none | none |
| `POST /api/skills` | `:1078` | none | none |
| `POST /api/memories/note` | `:1057` | none | none |
| `GET /`, `/health` | `:856` | none | n/a |
| SilverBullet UI → `/memories` | `compose:70` | none | none |
| Files already in `/memories` → context | `hermes_okf.py:347,392` | n/a | none |

`get_auth_key()` (`server.py:818`) exists but is called in only two places — `:911` and `/api/chat` at `:1012` — both of which merely *forward* the bearer token upstream to LiteLLM. It gates nothing. `do_POST` (`:999`) reads the request body and dispatches straight to the handlers above with no authentication step. All responses carry `Access-Control-Allow-Origin: *` (`server.py:829`, `do_OPTIONS` at `:833`).

No trust-tiering, no structural separation of tool output from instruction, no provenance metadata on memory writes. `TN-1.4` cannot be met until `TN-4.3` exists. **`TN-1.1` is the cheapest control here and should land first** — the inventory above is most of it.

---

### TN-2 — Action Authorization and Tool Governance

> The agent's ability to affect the world is explicitly enumerated, scoped to the current task, and mediated by a component the agent runtime cannot modify.

**Threats addressed:** `T-03` `T-06` `T-07` `T-08` `T-09` `T-12` `T-24` `T-25` `T-32` `T-42`

#### Required controls

| ID | Control |
|---|---|
| `TN-2.1` | A tool inventory MUST exist recording, per tool: purpose, scope, reversibility, blast radius, minimum trust tier permitted to initiate it. |
| `TN-2.2` | Default deny — the tool set available to a task MUST be the minimum for that task, not the full registry. |
| `TN-2.3` | Every tool MUST be classed reversible or irreversible. Irreversible actions MUST require an explicit authorization gate, not model discretion alone. |
| `TN-2.4` | Credentials MUST be scoped per tool — the agent MUST NOT hold a credential broader than the narrowest tool that uses it. |
| `TN-2.5` | Authorization MUST be enforced outside the agent runtime. Telling the agent via its system prompt what it is "allowed" to touch is self-certification, not authorization. |
| `TN-2.6` | Arbitrary code execution and package installation MUST be treated as maximal-blast-radius tools and MUST NOT be default-available. |
| `TN-2.7` | Self-initiated actions (no operator trigger) MUST be constrained to a strictly narrower tool set than operator-initiated actions. |
| `TN-2.12` | **Added.** Every control-surface endpoint on the agent container MUST authenticate the caller, and MUST NOT be reachable cross-origin from an operator's browser. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-2.8` | Composition review — chained tools that jointly exceed any single tool's intent. |
| `TN-2.9` | Proposed-action mode for irreversible operations, logged whether approved or not. |
| `TN-2.10` | Time-boxed authorization grants preferred over standing grants. |
| `TN-2.11` | Tool/connector definitions treated as supply chain artifacts — pinned, reviewed, version-controlled (`TN-8.5`). |

#### Verification

From an unauthenticated client on the ingress network, `POST` to `/api/terminal` and `/api/skills`; both MUST be rejected. From the agent runtime, attempt invocation of a tool outside its authorized task context; confirm denial happens at the mediating component, not the runtime. Assuming full runtime compromise, enumerate every action still reachable — that set is the actual blast radius.

#### What this does not protect against

An attacker working within a legitimately authorized tool set can still achieve an unanticipated outcome through composition. Authorization says nothing about whether an authorized action was *correct*.

#### `[Titan]` status

🔴 **Unimplemented — and materially worse than "prompt-level scoping only."**

The prompt-level mechanism the draft described is real but permissive rather than restrictive: `SOUL.md:24-26` tells the agent it "can execute sandboxed shell and python tasks inside `/workspace`" and that "tools and custom skills can be installed or authored dynamically." Capabilities are four unconditional booleans in `config/hermes/config.json:55-58` — `shell_enabled`, `browser_enabled`, `python_enabled`, `network_egress`, all `true`. No inventory, no reversibility classification, no operator-vs-self-initiated distinction. `TN-2.5` fails exactly as the draft said.

**Correction — the draft omitted the live defect that dominates this tenet.** `T-42`, filed as a GitHub issue (see Appendix B):

- **`POST /api/terminal`** (`server.py:1095`) executes `subprocess.run(["/bin/bash", "-c", command], cwd=WORKSPACE_DIR, timeout=30)` (`:1103-1108`) on arbitrary caller-supplied input **with no authentication check**.
- **`POST /api/skills`** (`server.py:1078`) writes caller-supplied code into `/workspace/skills` and `chmod 0o755` (`:1087`) — also unauthenticated. `/workspace` is a host bind-mount (`compose:104`), so this writes executable content to host-visible storage that persists across container rebuilds.
- Both carry `Access-Control-Allow-Origin: *` (`server.py:829`).
- The port is loopback-bound (`compose:94`), **but** Caddy reverse-proxies it to `hermes.titan.local` across `titan-ingress` (`Caddyfile:10-20`).

Net effect: `TN-2.6` is inverted — arbitrary code execution is not merely default-available to the model, it is available to any unauthenticated caller, and to any web page the operator visits. Every model-level and prompt-level control in this document is bypassable by calling the endpoint directly. **`TN-2.12` is the highest-priority remediation in this document**, ahead of the inventory work, because it is small and it currently nullifies TN-1, TN-2, and parts of TN-5.

Forward-looking note retained from the draft: irreversible-action gating (`TN-2.3`) is the control that must exist before the Football Dan wagering work lands. Per `README.md:191` (FD-4 / #32) that ledger is *paper* wagering with programmatic invariants, and `README.md:192` (FD-5 / #33) explicitly scopes "irreversible-action classification, external gate outside agent runtime" — so `TN-2.3` and `TN-2.5` already have a ticket. This tenet is planned, not merely missing.

---

### TN-3 — Autonomy Budget, Liveness Bounds, and Circuit Breaking

> A resident agent operates under explicit behavioural budgets enforced automatically, and is haltable by a mechanism that depends on neither the agent, the policy plane, nor an operator being present.

**Threats addressed:** `T-10` `T-11` `T-12` `T-32` `T-33` `T-35` `T-39`

> On fixed-cost hardware, financial budgets are not a substitute for behavioural budgets. A spend ceiling is the primary runaway detector in metered environments and provides almost no signal on owned hardware, where a pathological loop costs the same as useful work.

#### Required controls

| ID | Control |
|---|---|
| `TN-3.1` | Behavioural budgets MUST be defined and enforced: max steps, max tool invocations, max actions/interval, max wall-clock per task. |
| `TN-3.2` | Budget exhaustion MUST halt the agent automatically, without operator action. |
| `TN-3.3` | Repeated identical or near-identical tool invocations MUST trip a breaker independently of budget state. |
| `TN-3.4` | An out-of-band halt path MUST exist that does not require the policy plane to be healthy — process termination, container stop, or power. |
| `TN-3.5` | Halt semantics MUST be documented: what stops, what continues, what's not rolled back. |
| `TN-3.6` | Concurrency ceilings MUST be derived from measurement on the target hardware, not assumed. |
| `TN-3.7` | A resident agent MUST have a defined idle state holding no tool access and initiating no action. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-3.8` | Graduated response (throttle → suspend → halt) rather than a binary trip. |
| `TN-3.9` | Behavioural baselining with anomaly alerting, to replace the missing cost signal. |
| `TN-3.10` | Dead-man switch — the agent must periodically re-affirm authorization or degrade to idle. |
| `TN-3.11` | An independent watchdog process, outside the agent's and policy plane's reach. |

#### Verification

Trip each budget deliberately and confirm automatic halt; **measure and publish halt latency**. Execute `scripts/emergency-stop.sh` with LiteLLM deliberately stopped and confirm the container halt still succeeds and the agent stops.

#### What this does not protect against

A halt stops future activity — it does not reverse actions already completed. Recovery is `TN-9`.

#### `[Titan]` status

🟡 **Partial. Split verdict, and the draft was wrong in both directions.**

**`TN-3.4` — 🟢 already satisfied. Correction: the draft under-credited this.** The draft asserted that `emergency-stop.sh` "works *through* the policy plane it's supposed to be independent of, so it does not satisfy `TN-3.4` as written," and recommended "formally adopting container-stop" as new work. That recommendation is already implemented. The script's **first** action is a host-side container halt with no LiteLLM dependency:

- `scripts/emergency-stop.sh:43-49` — `docker compose pause hermes || docker compose stop hermes`
- `scripts/emergency-stop.sh:54-69` — LiteLLM `/key/delete`, explicitly **best-effort second**, guarded by `if [ -n "${LITELLM_KEY}" ] && [ -n "${MASTER_KEY}" ]`, and on failure logs (`:67`) *"LiteLLM API returned HTTP ${HTTP_CODE} or was unreachable. Container halt ensures loop is terminated."*

It runs on the host, outside the agent runtime, and does not require the policy plane to be healthy. `TN-3.4` is met. Also drop the draft's "revokes a virtual key in milliseconds" claim — no latency is measured anywhere, and `TN-3.4`'s verification step explicitly calls for a published figure.

One low-severity defect: the guard at `:43`, `docker compose ps -q hermes >/dev/null 2>&1`, exits 0 whether or not the container is running, making the `:48` "not currently running" branch near-unreachable. Cosmetic; the halt still fires.

**`TN-3.1`/`TN-3.2` — 🔴, and the structural reason matters more than the marker.** The draft correctly identified that `max_parallel_requests: 1` (`config/litellm/config.yaml:13,22,30`) caps concurrency rather than steps. It is not the only limit — there are also `timeout: 300` / `request_timeout: 300` (`:14,23,31,37`), a 30 s subprocess timeout (`server.py:1108`) and a 30 s LiteLLM call timeout (`server.py:1046`).

But **no behavioural budget can be exhausted today because there is no agent loop.** `docker/hermes/server.py` is a `BaseHTTPRequestHandler` with `do_GET`/`do_POST` (`:856`, `:999`) — request/response only. There is no iteration, no step counter, no autonomy to bound. This should read *"not applicable until an autonomous loop exists"* rather than 🟡, because that is far more actionable for Antigravity: **the budget must be designed into the loop when the loop is built, not retrofitted.** Per `README.md:185` (Sprint 0 / #28), "policy-plane behavioral budgets" and an "out-of-band halt script" are already scoped.

Also absent: `pids_limit`, `cpus`, `mem_limit` on any service in `docker-compose.yml`, so container-level runaway resource protection relies solely on the LiteLLM concurrency cap. `TN-3.3`, `TN-3.5`, `TN-3.6`, `TN-3.7` — 🔴, none implemented; `TN-3.6` in particular has no measurement record, so the `max_parallel_requests: 1` value is currently assumed rather than derived (`AGENTS.md` Rule 3 states it as policy).

---

### TN-4 — Memory Integrity, Provenance, and Version Control

> Agent memory is stored in a human-legible, non-opaque format, carries provenance sufficient to distinguish trusted from untrusted content, and is recoverable to a specific point in time — not merely restorable from the most recent snapshot.

**Threats addressed:** `T-05` `T-14` `T-34` `T-35`

#### Required controls

| ID | Control |
|---|---|
| `TN-4.1` | Durable agent memory MUST be stored in a human-readable, non-opaque format — no binary blobs, vector databases, or serialized/pickled objects. |
| `TN-4.2` | Memory content MUST be directly editable and revertible by a human operator without specialized tooling. |
| `TN-4.3` | Memory writes MUST carry provenance metadata (source, trust tier, timestamp) sufficient to distinguish operator-authored from tool-derived or agent-inferred content. |
| `TN-4.4` | Memory MUST be under version control with recoverable history — a snapshot restores the whole store to a point in time; it does not show what changed, when, or why. |
| `TN-4.5` | Context assembled from memory into a prompt MUST respect a hardware/token-budget ceiling. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-4.6` | Anomalous memory writes (bulk edits, edits during unattended operation) SHOULD trigger review. |
| `TN-4.7` | A periodic integrity check SHOULD diff current memory state against last known-good and flag unexplained deltas. |
| `TN-4.8` | Cross-session persistent memory SHOULD be distinguished from ephemeral working memory, with different retention policies. |

#### Verification

Attempt to write a binary or `.db` file into `/memories` via `POST /api/memories/note` and confirm rejection. Run `hermes_okf.py purity` and confirm it reports violations. Edit a note via SilverBullet and confirm the next agent context read reflects the change *and* that the prior version is recoverable. Inject a delayed-trigger instruction into memory and confirm a human reviewer can read it as plain text.

#### What this does not protect against

A poisoned note written in the operator's own voice can pass casual human review — legibility lowers the detection bar, it doesn't guarantee detection. Filesystem-level tampering is `TN-5`'s and `TN-9`'s problem, not `TN-4`'s.

#### `[Titan]` status

🟡 **Strongest tenet in the architecture on its first half; the half in its own title is missing.** The draft's assessment was accurate — retained with evidence added and the overall marker corrected from 🟢 to 🟡, since `TN-4.3` and `TN-4.4` are both unmet MUSTs.

🟢 `TN-4.1` — OKF flat-file Markdown, enforced at **three** layers, all verified:
- Runtime: `hermes_okf.py:255-256` rejects any path not ending `.md`; `:259-260` rejects binary content (`if "\0" in content`); `:189` blocks path traversal (in `_resolve_safe_path`, `:184-190`); `:412-436` `validate_purity()` scans the tree; forbidden-extension list at `:37-40`
- Config: `config/hermes/config.json:32` `enforce_purity: true`, disallowed content at `:36-41`
- Policy: `AGENTS.md` Rule 1 (`:127`), `config/memories/rules/memory_purity_guardrail.md`

🟢 `TN-4.2` — SilverBullet mounts `/memories` directly as `/space` (`compose:70`); plain Markdown is editable with any text editor. *Caveat:* "revertible" is currently satisfied only at snapshot granularity — see `TN-4.4`.

🟡 `TN-4.5` — a context ceiling exists (`INFERENCE_NUM_CTX`, `compose:113`, `config.json:15`, `litellm/config.yaml:15`) and `hermes_okf.py:347,392` accept `max_chars`, but retrieval is `on_demand_only` with knowledge/logs injection disabled (`config.json:27-31`), so the ceiling is not yet exercised against a realistic assembled context.

🔴 `TN-4.3` — **no provenance whatsoever.** `OKFNote` frontmatter carries `title`, `tags`, `active`, `priority` (fields at `hermes_okf.py:52-58`, emitted by `serialize()` at `:144-148`) and nothing identifying source, trust tier, or author. `write_note` (`:244`) accepts no provenance argument. This is the dependency that blocks `TN-1.4`.

🔴 `TN-4.4` — **snapshot-only, no versioned history.** `data/memories/` is not a git repo (no nested `.git`) and is explicitly excluded — `.gitignore:10` (`data/memories/*`), confirmed via `git check-ignore -v`. CI actively enforces that exclusion (`pre-commit.yml:39-48`). The only history is timestamped tarballs: `snapshot-memories.sh:75` (`tar -czf`, 14 retained at `:83`) and `backup.sh:160` (`MAX_BACKUPS=14` at `:56`). No diff, no per-note history, no "what changed and why."

*Note the tension worth resolving deliberately:* CI is configured to keep memory **out** of the repo's git, while `TN-4.4` requires memory to be **under** version control. These are compatible — `TN-4.4` wants a *separate, local* history for `/memories`, not memory committed to the project repo. `README.md:190` (FD-3 / #31) scopes exactly this as "memory plane under localized Git versioning." Whoever implements #31 must not weaken `pre-commit.yml:39-48` to do it.

---

### TN-5 — Execution Isolation and Least Privilege

> The agent execution environment is unprivileged, capability-stripped, network-partitioned from everything it isn't authorized to reach, and disclosed no more infrastructure information than its task requires.

**Threats addressed:** `T-36` `T-37` `T-38` `T-42`

#### Required controls

| ID | Control |
|---|---|
| `TN-5.1` | The agent execution environment MUST run as an unprivileged, non-root identity. |
| `TN-5.2` | Linux capabilities MUST be dropped in full (`cap_drop: ALL`); no re-added capability without individual justification. |
| `TN-5.3` | Privilege escalation MUST be disabled at the runtime level (`no-new-privileges`). |
| `TN-5.4` | The host container-management socket MUST NOT be reachable from the agent execution environment. |
| `TN-5.5` | Network access MUST be partitioned to only the services the agent is authorized to call. |
| `TN-5.6` | Information disclosed to the agent (system prompt, persona files, environment) MUST be scoped to task need — internal infrastructure names, credentials, and topology MUST NOT appear in agent-visible context. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-5.7` | Hardware driver and kernel module versions SHOULD be pinned. |
| `TN-5.8` | Isolation boundaries SHOULD be periodically re-tested from inside the container. |

#### Verification

From inside the agent container, attempt to reach the host docker socket, the policy-plane database, and loopback-bound inference — all three MUST fail. Run `capsh --print` (or read `/proc/self/status` `CapEff`) inside the container and confirm the effective capability set is empty. Extract the agent's full system prompt via injection and confirm no host infrastructure names, ports, or credentials appear.

#### `[Titan]` status

🟡 **Downgraded from the draft's 🟢. `TN-5.2` is unmet, and the claim has survived both document versions unchallenged.**

**Correction — `cap_drop` is 🔴, not 🟢.** `cap_drop` appears in **no manifest in this repo** — not in `docker-compose.yml`, not in the `Dockerfile`. The Hermes service's entire hardening block is `security_opt: ["no-new-privileges:true"]` (`compose:91-92`). The container therefore retains Docker's default capability set — including `CAP_CHOWN`, `CAP_DAC_OVERRIDE`, `CAP_SETUID`, `CAP_SETGID`, `CAP_NET_RAW`, and others.

Where the string *does* appear is prose, and that is the problem: it is asserted as fact in **`README.md:70`** (`cap_drop: [ALL]`, "only retaining minimal network hooks"), in the v2 Part 1 diagram, and in v1's Tenet 1 and threat matrix ("**Tenet 1**: `cap_drop: [ALL]`… non-root UID 1000"). Most seriously, v1's advisory checklist asks *clients* to verify "Are all Linux capabilities dropped (`cap_drop: [ALL]`)?" while Titan itself does not do so.

This is the single most load-bearing false claim in the project's documentation, and it is stated in a committed, user-facing file. The remediation is two lines in `docker-compose.yml` plus a `README.md:70` correction, and should land alongside `TN-2.12`.

🟢 `TN-5.1` — non-root UID/GID 1000, but **via the image, not the manifest**: `Dockerfile:17-19` creates the user, `:33` `USER hermes`. Hermes has no compose `user:` directive (unlike silverbullet at `compose:63`). Worth stating precisely, because a compose override or an image change could silently undo it and CI would not notice.

🟢 `TN-5.3` — `compose:91-92`.

🟢 `TN-5.4` — `/var/run/docker.sock` verified absent from every volume block. Backed by policy (`AGENTS.md` Rule 4, `:139`).

🟡 `TN-5.5` — **partial, and the draft over-credited it.** DB isolation is genuinely strong and CI-enforced: `titan-litellm-db` is on `titan-litellm-net` alone (`compose:47-48`), loopback-bound (`:40`), with four guardrails in `pre-commit.yml:78-110` failing any PR that bridges it or leaks DB env vars into Hermes. That part is 🟢. But Hermes sits on **two** networks (`compose:114-116`) — `titan-internal`, documented as permitting agent WAN egress (`compose:127`), and `titan-ingress`, which is what makes the unauthenticated console reachable via Caddy. Partitioning protects the database; it does not currently constrain the agent's outbound reach or shield its own control surface (`T-42`).

🟢 `TN-5.6` — **verified, and the draft was right.** `SOUL.md` discloses only `/workspace`, `/memories`, and `http://litellm:4000/v1` (`:21`). No `Ollama`, no `titan-litellm-db`, no host socket paths, no credentials. `AGENTS.md` Rule 7 (`:152-155`) explicitly permits naming the agent's assigned completions endpoint while forbidding host backend names, so `SOUL.md:21` is compliant by design rather than by oversight.

🟡 `TN-5.7` — `apt-mark hold` at `setup-host.sh:51-55`, Linux/DGX only and safely bypassed on macOS (`AGENTS.md:12`). Not comprehensive. See also `TN-8.4`, where container base images are unpinned.

🔴 `TN-5.8` — `verify-hermes.sh` exists but no scheduled or CI-driven re-test of isolation boundaries from inside the container.

---

### TN-6 — Inference Tiering and Data Egress Control

> Any request leaving the appliance boundary passes through a single, inspectable egress point, and the decision to escalate is treated as a data-classification decision, never a pure capability or cost optimization.

**Threats addressed:** `T-37` *(inference-tier escalation applies once such a path exists; general egress applies today)*

#### Required controls — apply once any cloud-tier escalation exists

| ID | Control |
|---|---|
| `TN-6.1` | Any request leaving the appliance MUST pass through a single, identifiable egress point — not be reachable directly from the agent execution environment. |
| `TN-6.2` | Escalation content MUST be authored as a discrete, inspectable artifact rather than a raw forwarded context window. |
| `TN-6.3` | An outbound classification/secret-scanning check MUST run on every egress artifact, regardless of pattern. |
| `TN-6.4` | The escalation decision MUST NOT be made solely by a component optimizing for capability or latency. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-6.5` | Prefer asynchronous, brokered consultation over synchronous context-forwarding. |
| `TN-6.6` | Retain request/response pairs at the egress point as the audit record. |

#### Verification

Attempt a direct network call from the agent execution environment to an external endpoint, bypassing the designated egress point — it MUST fail at the network layer. **Run this test now**: `docker compose exec hermes curl -s -o /dev/null -w '%{http_code}' https://example.com`. Per the configuration below this is expected to *succeed*, which is the finding.

#### What this does not protect against

A capable model can be manipulated into abstracting or encoding sensitive content into plausible prose that evades classification.

#### `[Titan]` status

🟡 **Corrected from the draft's 🟢. The draft conflated "no cloud inference tier" with "no egress path"; these are different claims and only the first is true.**

🟢 **True and verified:** there is no cloud-tier *inference* escalation path. All three model entries route to `ollama_chat/...` at `http://127.0.0.1:11434` (`litellm/config.yaml:10-11,20-21,28-29`), Ollama is launched bound to loopback (`setup-host.sh:299`, `OLLAMA_HOST="127.0.0.1:11434"`), no cloud provider keys appear in `.env.example`, and `AGENTS.md` Rule 2 (`:132-135`) forbids routing Hermes directly to Ollama. `TN-6.4` has nothing to decide yet.

🔴 **False as stated in the draft:** the agent does have general outbound WAN egress today, and it is not mediated by any inspectable egress point.
- `config/hermes/config.json:58` — `"network_egress": true`
- `config/hermes/config.json:56` — `"browser_enabled": true`
- `docker-compose.yml:127` — `titan-internal` is documented as existing to permit "agent WAN egress (web browsing, Signal)"
- `Dockerfile:9-15` — `curl` and `git` installed in the image
- Combined with the unauthenticated `/api/terminal` (`TN-2`), any caller can run arbitrary outbound network commands from inside the agent container

So `TN-6.1` — "any request leaving the appliance MUST pass through a single, identifiable egress point" — is **unmet today**, and `TN-6.3` has no implementation. The draft's advice to "track this tenet's status separately… it will flip from 🟢 to 🔴 the day tiering ships" is the right instinct applied to the wrong trigger: **the flip has already happened for general egress.** What remains scheduled is inference-tier egress specifically. `README.md:205` (X-1 / #42) scopes "outbound policy inspection at LiteLLM scanning consultation payloads for seeded tenant canary tokens" and cites `TN-6` — note that inspecting *at LiteLLM* covers the inference path only, not the agent's direct `curl`/browser egress, which needs `TN-6.1` enforced at the network layer.

---

### TN-7 — Observability, Audit, and Forensic Reconstruction

> Every action the agent takes and every decision the policy plane makes is logged with enough detail to reconstruct what happened, exported somewhere the agent cannot reach, and retained long enough to matter during an incident.

**Threats addressed:** `T-27` `T-33` `T-42` `T-43`

#### Required controls

| ID | Control |
|---|---|
| `TN-7.1` | Every tool invocation, memory write, and policy-plane decision MUST be logged with enough detail to reconstruct what happened and on whose authorization. |
| `TN-7.2` | Logs MUST be exported off the appliance on a schedule independent of the appliance's own uptime. |
| `TN-7.3` | Log integrity MUST be protected — the agent execution environment MUST NOT be able to edit or delete its own audit trail. |
| `TN-7.4` | A minimum retention period MUST be defined and enforced. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-7.5` | Behavioural baselining SHOULD give a signal for anomalous activity, since no cost-based signal exists (see `TN-3`). |
| `TN-7.6` | Budget-exhaustion, halt, and authorization-denial events SHOULD surface to a human without log-diving. |

#### Verification

Trigger a tool call, a memory write, and a policy denial; confirm each appears in the exported log with enough detail to answer "what happened and why" without touching the live appliance. Attempt to delete a log entry from inside the agent execution environment; confirm it fails.

#### What this does not protect against

Logging is detective, not preventive — a fast, quiet compromise can complete before anyone reads the log.

#### `[Titan]` status

🔴 **Entirely unimplemented — confirmed as the largest single gap. The draft's assessment was accurate; evidence added.**

What exists is default container logging and nothing else:
- `server.py:1123` — `log_message` writes request lines to `sys.stderr`
- `Caddyfile:12-15,27-30,41-44` — `output stdout`, `format console`
- `setup-host.sh:299` — Ollama stdout/stderr redirected to `data/control_plane/ollama.log`
- **`docker-compose.yml` contains no `logging:` block on any service**, so Docker's default `json-file` driver applies with no size, rotation, or retention configuration

Against each MUST:
- `TN-7.1` 🔴 — **no action log exists at all.** `/api/terminal` (`server.py:1095`) records the executed command nowhere; `/api/skills` (`:1078`) records authored code nowhere; `write_note` (`hermes_okf.py:244`) records no audit entry. `log_message` captures HTTP request lines, not tool arguments, results, or authorization basis. The `/memories/logs/` tree exists (`config.json:45`) but is agent-authored narrative, not a tamper-evident audit trail.
- `TN-7.2` 🔴 — no export. No syslog, OTel, journald, or aggregation anywhere in the repo.
- `TN-7.3` 🔴 — stderr-to-container-logs is not integrity-protected, and `/memories/logs/` is directly agent-writable, so the agent can edit its own narrative record.
- `TN-7.4` 🔴 — no retention period defined; default `json-file` logs do not survive `docker compose down`, which `TN-9.3` requires as a routine operation.

**Note the cross-tenet consequence, which is the real reason to prioritise this:** the verification steps in TN-1, TN-2, TN-3, and TN-4 all assume a durable record exists to check against. Right now most of them cannot be executed as written. `README.md:185` (Sprint 0 / #28) scopes an "append-only action log with agent versioning" — that ticket is the dependency for verifying half this document.

---

### TN-8 — Supply Chain Integrity

> Changes to the agent's own code, configuration, dependencies, and granted tools are tracked, reviewed by a human before they take effect, and version-pinned so an upgrade is a deliberate action rather than a side effect.

**Threats addressed:** `T-41` `T-43`

#### Required controls

| ID | Control |
|---|---|
| `TN-8.1` | Every code contribution MUST trace to a tracked work item with defined scope; scope creep MUST be split into a new tracked item, not folded in silently. |
| `TN-8.2` | Autonomous or AI-assisted code contributions MUST stop for explicit human review before any commit, push, or PR — no autonomous merge path. |
| `TN-8.3` | CI MUST automatically fail any change introducing a tracked secret, leaking policy-plane credentials into the agent execution environment, or bridging an isolated network segment. |
| `TN-8.4` | Base images, model runtimes, and hardware drivers MUST be version-pinned; upgrades MUST be deliberate, not automatic. |
| `TN-8.5` | Third-party tools/connectors granted to the agent MUST be reviewed and version-pinned before joining the tool inventory (`TN-2.1`). |
| `TN-8.8` | **Added.** Security-baseline documents that generated code is written against MUST themselves be version-controlled and review-gated (`T-43`). |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-8.6` | Dependency and base-image vulnerability scanning SHOULD run on a schedule independent of the next planned rebuild. |
| `TN-8.7` | Keep a record of why each pinned version was chosen and when it was last reviewed. |

#### Verification

Submit a PR containing a tracked secret and confirm CI blocks it. Submit a PR bridging `titan-internal` to an external network and confirm CI blocks it. Attempt an unreviewed autonomous commit and confirm the pre-commit gate stops it. Run `docker compose config | grep image:` and confirm every image is digest-pinned.

#### What this does not protect against

Supply chain controls reduce the odds of an unreviewed change reaching production — they don't catch a maliciously-crafted change that passes review because the reviewer missed it. Pinning without active review just becomes permanent staleness.

#### `[Titan]` status

🟡 **Code governance is genuinely strong; artifact pinning is weaker than the draft recorded.**

🟢 `TN-8.1` — ticket-driven scoping is real and observed in practice: every feature commit carries an issue prefix (`[#2]`, `[#3]`, `[#4]`, `[#9]`, `[#17]`, `[#21]`, `[#25]`), with `AGENTS.md:109` requiring one verifiable deliverable per issue and `AGENTS.md:48` requiring architectural-shift review. Backlog promotion for tangential findings is codified (commit `59d1a9f`). **Exception: this document violates `TN-8.1`/`TN-8.8` — see the governance warning at the top.**

🟢 `TN-8.2` — `AGENTS.md:67-71` — the agent must "NEVER commit, push, or open a Pull Request without explicit human review and approval," requiring explicit approval before Step 7. Antigravity attribution is required on the resulting commits (`AGENTS.md:78-84`) and is present on 13 commits, so contributions are traceable to the assisting agent.

🟢 `TN-8.3` — `.github/workflows/pre-commit.yml` is real and does exactly what the control requires: gitleaks (`:24`), tracked-secret-file check (`:29-37`), memory purity (`:39-48`), workspace hygiene (`:50-59`), `bash -n` syntax (`:61-69`), compose topology validation (`:71-76`), and four DB-isolation guardrails (`:78-110`).

🔴 **`TN-8.4` — corrected from the draft's 🟡.** The draft scored this 🟡 on the strength of NVIDIA driver pinning alone and did not assess container images. **No image in the repo is digest-pinned, and one floats entirely:**

| Artifact | Location | Pin state |
|---|---|---|
| `zefhemel/silverbullet:latest` | `compose:60` | 🔴 **floating tag** |
| `caddy:2-alpine` | `compose:13` | 🟡 mutable tag |
| `postgres:16-alpine` | `compose:36` | 🟡 mutable tag |
| `python:3.11-slim` | `Dockerfile:6` | 🟡 mutable tag |
| NVIDIA driver packages | `setup-host.sh:51-55` | 🟢 `apt-mark hold` (Linux/DGX only) |

There is also **no dependency lockfile of any kind** — no `requirements.txt`, `pyproject.toml`, `uv.lock`, or `package.json`. `apt-get install` at `Dockerfile:9-15` is unpinned, so every rebuild can pull different `curl`, `git`, and `jq` versions.

`silverbullet:latest` is the sharpest edge and deserves its own remediation: it is an unpinned third-party image with the memory plane mounted directly into it (`compose:70` → `/space`). A malicious or broken upstream push lands on `A-03` at the next `docker compose pull`. Pinning it by digest is a one-line change and the highest value-per-effort item in this tenet.

🔴 `TN-8.5` — no third-party tool/connector review process. As the draft correctly noted, it has nowhere to attach: `mcp` and `connector` return zero matches outside prose, so no tool registry exists for it to govern. Sequence it after `TN-2.1`.

🔴 `TN-8.6` — no vulnerability or dependency scanning. Gitleaks scans for secrets only; nothing scans images or packages for CVEs.

🔴 `TN-8.8` — see the governance warning. This document is untracked, so it is outside every control in this tenet.

---

### TN-9 — Operational Discipline and Deterministic Recovery

> All persistent state lives under one clearly bounded root, is backed up on a verified schedule, and every operational action — setup, permissions, backup, restore, health check — is an idempotent script, never a manual intervention on running infrastructure.

**Threats addressed:** `T-40`

#### Required controls

| ID | Control |
|---|---|
| `TN-9.1` | All persistent appliance state MUST live under a single, clearly bounded data root, partitioned by function. |
| `TN-9.2` | A backup mechanism MUST capture the complete data root on a defined schedule, with retention and pruning policy, and MUST be verifiable. |
| `TN-9.3` | The container/compute plane MUST be fully stateless and reconstructable from clean manifests without data loss. |
| `TN-9.4` | Operational actions MUST be codified as idempotent scripts — no manual `docker exec`, ad hoc file copies, or permission changes on running infrastructure. |
| `TN-9.5` | Halt and recovery semantics MUST be documented: what a full stop/restart does and doesn't preserve. |

#### Recommended controls

| ID | Control |
|---|---|
| `TN-9.6` | Cross-platform reproducibility SHOULD be verified periodically. |
| `TN-9.7` | A recovery drill SHOULD be run periodically — actually destroying and rebuilding the appliance, not just trusting the scripts would work. |

#### Verification

Run the full backup, then destroy and rebuild the appliance from manifests alone; confirm 100% of memory, policy-plane state, and workspace data survives. Perform an operational task using only documented scripts and confirm no manual intervention was needed.

#### What this does not protect against

Deterministic recovery restores the system to its last backed-up state — it doesn't tell you whether that state was already compromised or poisoned (that's `TN-4` and `TN-7`'s job). It also assumes the scripts themselves haven't drifted from what production needs, which is exactly what `TN-9.7` exists to catch.

#### `[Titan]` status

🟢 **Second-strongest tenet, alongside `TN-4`'s implemented half. The draft's assessment holds, with one correction on scheduling.**

🟢 `TN-9.1` — single data root partitioned by function: `data/memories`, `data/workspace`, `data/litellm_db`, `data/backups`, resolved consistently in `backup.sh:51-56` and via `TITAN_DATA_DIR` / `TITAN_WORKSPACE_DIR` / `LITELLM_DB_DATA_DIR` (`compose:70,100,104,46`).

🟡 `TN-9.2` — **corrected: the mechanism is strong but there is no schedule.** The capability is real and better than the draft credited: `backup.sh:160-164` archives all three planes with a manifest (`:146-157`), `:180-193` enforces `MAX_BACKUPS=14` retention, `:209-213` verifies archive integrity with `tar -tzf` before restoring, and `:221-227` requires confirmation unless `--force`. `snapshot-memories.sh` provides a memory-only path with matching retention (`:83-90`). **But no scheduler exists** — grepping `scripts/`, `.github/`, and `docker-compose.yml` for `cron`, `systemd`, `launchd`, or `timer` returns nothing. Backups are entirely manual, so "on a defined schedule" is unmet and `TN-7.2`'s off-appliance export has no scheduling precedent to build on. The draft's own `TN-9.2` wording sets "verifiable" as the bar and it is met; "scheduled" is not.

🟢 `TN-9.3` — container plane is stateless: all mutable state is bind-mounted or in named volumes (`compose:70,100,102,104,141-145`), Hermes is rebuilt from `Dockerfile`, and LiteLLM model state persists to Postgres (`litellm/config.yaml:43-45`, `store_model_in_db: true`).

🟢 `TN-9.4` — codified and policed. `AGENTS.md` Rule 8 (`:157`) forbids ad-hoc `docker exec`, `docker cp`, container restarts, and manual `chown`/`chmod`, requires codification in `scripts/*.sh`, and requires debugging via the scripts themselves. Nine idempotent scripts cover setup, build, memory scaffolding, backup/restore, emergency stop, and verification. `pre-commit.yml:61-69` syntax-checks all of them.

🔴 `TN-9.5` — halt semantics are **partially** documented but not as a control. `emergency-stop.sh:71-76` states memory and host remain intact and gives resume steps, which is the right instinct. What is undocumented: that default container logs are lost on `docker compose down` (see `TN-7.4`), what happens to an in-flight tool invocation on `pause` versus `stop`, and what is *not* rolled back. Given `TN-9.3` treats teardown as routine, this gap has real operational cost.

🔴 `TN-9.7` — no evidence of a practised recovery drill. `AGENTS.md:161` asserts the "GX10 Reproducibility Guarantee" and `verify-hermes.sh` / `verify-memories.sh` exist, but nothing records an actual destroy-and-rebuild having been executed and verified. The capability is 🟢; the *practice* is unevidenced, which is precisely the distinction `TN-9.7` exists to draw.

---

## Part 5 — Tenet Status at a Glance

Changes from the v2 draft are marked. Overall markers reflect the weakest unmet MUST in each tenet.

| Tenet | Draft | **Verified** | One-line why |
|---|---|---|---|
| TN-1 Input boundary | 🔴 | **🔴** | Worse than drafted — Signal doesn't exist; real channel is an unauthenticated HTTP console |
| TN-2 Tool authorization | 🔴 | **🔴** | Worse than drafted — unauthenticated `/api/terminal` shell bypasses every model-level control |
| TN-3 Autonomy budget / circuit breaking | 🟡 | **🟡** | Composition corrected — `TN-3.4` out-of-band halt is already 🟢; no loop exists to budget yet |
| TN-4 Memory integrity | 🟢 | **🟡** ↓ | Purity is strong and triple-enforced; provenance and version history — both MUSTs — absent |
| TN-5 Execution isolation | 🟢 | **🟡** ↓ | `cap_drop: ALL` is asserted project-wide but absent from every manifest |
| TN-6 Egress control | 🟢* | **🟡** ↓ | No cloud *inference* tier, but the agent has ungoverned WAN egress today |
| TN-7 Observability | 🔴 | **🔴** | Confirmed — largest gap; no action log at all, blocking verification of TN-1–TN-4 |
| TN-8 Supply chain | 🟡 | **🟡** | Code governance solid; images unpinned (`silverbullet:latest`), no lockfile, and this doc is untracked |
| TN-9 Operational discipline | 🟢 | **🟢** | Strong; backups are verifiable but unscheduled, and drills are unevidenced |

**Net effect of verification: three tenets moved down, none moved up.** The pattern is consistent and worth internalising — every marker that proved optimistic was a control described in prose (`SOUL.md`, `AGENTS.md`, this document's own diagram) but not enforced in code. Every marker that held up was enforced in `docker-compose.yml`, a script, or CI. **When setting a marker, cite the enforcing line or mark it 🔴.**

### Revised priority order

The draft proposed `TN-2` → `TN-3` → `TN-7`. Two items now precede that, because they are small, they are already-false claims rather than unbuilt features, and each currently nullifies controls elsewhere:

1. **`TN-2.12` — authenticate `/api/terminal`, `/api/skills`, `/api/memories/note`; drop wildcard CORS.** Unauthenticated RCE reachable via Caddy. Nullifies TN-1, TN-2, and part of TN-5 regardless of what else is built. *(GitHub issue drafted — Appendix B.)*
2. **`TN-5.2` — add `cap_drop: [ALL]` to the Hermes service.** Two lines. Closes a claim the project already makes to clients in its own advisory checklist.
3. **Commit this document (`TN-8.8`).** An untracked baseline has already been lost once, and Antigravity cannot generate against a spec it cannot read.
4. **Pin `zefhemel/silverbullet` by digest (`TN-8.4`).** One line; it has the memory plane mounted into it.
5. **`TN-2.1` — tool inventory**, then `TN-2.3`/`TN-2.5` gating ahead of FD-5 (#33).
6. **`TN-7.1` — append-only action log** (Sprint 0 / #28). Sequence before further TN-1/TN-3 work, since their verification steps depend on it.
7. **`TN-3.1`/`TN-3.2` — behavioural budgets, designed into the agent loop when that loop is built**, not retrofitted.
8. **`TN-4.3`/`TN-4.4` — provenance and localized git history** (FD-3 / #31), without weakening `pre-commit.yml:39-48`.

---

## Part 6 — Enterprise/Engineering Advisory Checklist

Unchanged from the draft, with one addition. Note that Titan itself currently answers **no** to 1.1–1.3, 2.1–2.3, 3.1–3.3, 4.2, 4.3, 5.2 (capabilities), 7.1, 7.2, 8.2, and 9.2 — worth knowing before handing this to a client.

1. **TN-1 / Input boundary**
   - [ ] Is every input channel enumerated in an inventory?
   - [ ] Is content assigned a trust tier at ingestion?
   - [ ] Is tool/external content structurally separated from instruction?
2. **TN-2 / Tool authorization**
   - [ ] Does a tool inventory exist with scope, reversibility, and blast radius per tool?
   - [ ] Is authorization enforced outside the agent runtime?
   - [ ] Do irreversible actions require an explicit gate?
   - [ ] **Does every management and execution endpoint on the agent container authenticate its caller?**
3. **TN-3 / Autonomy budget**
   - [ ] Are behavioural budgets (steps, tool calls, wall-clock) defined and enforced?
   - [ ] Does budget exhaustion halt automatically, without a human?
   - [ ] Does the halt path work if the policy plane is down?
4. **TN-4 / Memory integrity**
   - [ ] Is memory human-readable and human-editable?
   - [ ] Does memory carry provenance metadata?
   - [ ] Is there a version history, not just a snapshot backup?
5. **TN-5 / Execution isolation**
   - [ ] Non-root, capability-dropped, socket-excluded? *(Verify capabilities empirically — `capsh --print` inside the container — not from the manifest's reputation.)*
   - [ ] Is the agent's own system prompt free of infrastructure names and credentials?
6. **TN-6 / Egress control**
   - [ ] Is there currently any path for content to leave the appliance — including the agent's own shell and browser, not just the inference tier? If not yet — is a plan in place for when there is?
7. **TN-7 / Observability**
   - [ ] Are tool calls, memory writes, and policy decisions logged?
   - [ ] Are logs exported off-appliance and protected from the agent itself?
8. **TN-8 / Supply chain**
   - [ ] Is every code change reviewed by a human before merge?
   - [ ] Are base images digest-pinned, and is there a dependency lockfile?
   - [ ] Are third-party tools/connectors reviewed and pinned before being granted to the agent?
   - [ ] **Is the security baseline document itself under version control?**
9. **TN-9 / Operational discipline**
   - [ ] Can the appliance be destroyed and rebuilt from manifests with zero data loss?
   - [ ] Has that recovery actually been drilled, not just assumed?

---

## Appendix A — Evidence Table

Every non-🔴 marker above traces to a line here. Verified against the working tree at `da882a8`.

| Claim | Verdict | Evidence |
|---|---|---|
| Old "Tenet 1–8" numbering referenced in code/scripts/CI | **FALSE** | `tenet` matches only this file and its own remediation drafts under `docs/`; zero hits in code, scripts, CI, or `AGENTS.md` |
| `README.md` forward-references TN- IDs | **TRUE** | `README.md:199` (`TN-1.8`), `:205` (`TN-6`) — uncommitted |
| This document is tracked in git | **FALSE** | `git status`: `?? docs/reference-architecture-tenets.md`; no history on any branch |
| Antigravity left plan/task/session artifacts | **FALSE** | No `*antigravity*`, `GEMINI.md`, `.idx*`, plan, or session files exist |
| Antigravity co-authored the implementation | **TRUE** | `Co-authored-by` trailer on 10 of 18 commits on `main` (19 across all refs) incl. `c212840`, `ca57a21`, `710013b`, `7a6a7e6`, `120004d`, `da8543b`, `da882a8` |
| **TN-2**: tool inventory or authorization gate exists | **FALSE** | Only `SOUL.md:24-26` prose + `config.json:55-58` (4 booleans, all `true`) |
| **TN-2**: `/api/terminal` unauthenticated shell | **TRUE** | `server.py:1095` handler, `subprocess.run(["/bin/bash","-c",command])` at `:1103-1108`; `do_POST:999` dispatches with no authN; `get_auth_key():818` called only at `:911` and `:1012`, both forward-only; CORS `*` at `:829`; proxied via `Caddyfile:10-20` |
| **TN-2**: `/api/skills` unauthenticated code write | **TRUE** | `server.py:1078` handler, `chmod 0o755` at `:1087`; `/workspace` host-mounted at `compose:104` |
| **TN-3.1/3.2**: step/tool-call/wall-clock cap with auto-halt | **FALSE** | No agent loop — `server.py:856,999` are request/response handlers |
| **TN-3**: `max_parallel_requests: 1` is the only limit | **FALSE** | Also `timeout: 300` (`litellm:14,23,31`), `request_timeout: 300` (`:37`), 30 s subprocess (`server.py:1108`), 30 s LLM call (`:1046`) |
| **TN-3.4**: `emergency-stop.sh` has a container-stop path independent of LiteLLM | **TRUE** | `emergency-stop.sh:43-49` (container halt, first); `:54-69` (LiteLLM, best-effort second); `:67` confirms container halt is the guarantee |
| **TN-4.1**: memory purity runtime-enforced | **TRUE** | `hermes_okf.py:255-256`, `:259-260`, `:189`, `:412-436`, `:37-40`; `config.json:32,36-41`; `AGENTS.md:127` |
| **TN-4.3**: provenance metadata on memory writes | **FALSE** | `OKFNote` carries only title/tags/active/priority — `hermes_okf.py:52-58`, `:144-148`, `:244` |
| **TN-4.4**: `/memories` under git or versioned history | **FALSE** | Not a git repo; `.gitignore:10` excludes it (`git check-ignore -v` confirms); CI enforces exclusion at `pre-commit.yml:39-48`; only tarballs — `snapshot-memories.sh:75,83`, `backup.sh:160,56` |
| **TN-5.1**: non-root UID 1000 | **TRUE** | `Dockerfile:18-19,33` (image, not compose `user:`) |
| **TN-5.2**: `cap_drop: ALL` | **FALSE** | Absent from every manifest (`docker-compose.yml`, `Dockerfile`); Hermes has only `security_opt` at `compose:91-92`. Falsely asserted as fact in `README.md:70` |
| **TN-5.3**: `no-new-privileges` | **TRUE** | `compose:91-92` |
| **TN-5.4**: docker socket excluded | **TRUE** | Absent from all volume blocks; `AGENTS.md:139` |
| **TN-5.5**: DB isolation | **TRUE** | `compose:40,47-48`; CI guardrails `pre-commit.yml:78-110` |
| **TN-5.5**: agent network partitioned | **PARTIAL** | Hermes on both networks — `compose:114-116`; WAN egress noted `compose:127` |
| **TN-5.6**: no host infra names in agent context | **TRUE** | `SOUL.md` names only `/workspace`, `/memories`, `litellm:4000/v1` (`:21`) — permitted by `AGENTS.md:152-155` |
| **TN-6**: inference loopback-bound, no cloud tier | **TRUE** | `litellm:10-11,20-21,28-29`; `setup-host.sh:299`; `AGENTS.md:132-135` |
| **TN-6**: agent has ungoverned WAN egress | **TRUE** | `config.json:56,58`; `compose:127`; `Dockerfile:9-15` (curl, git) |
| **TN-7**: log export off appliance | **FALSE** | No `logging:` block in `compose`; `server.py:1123` → stderr; `Caddyfile:12-15,27-30,41-44` → stdout |
| **TN-7.1**: action log of tool calls | **FALSE** | No audit write in `/api/terminal` (`server.py:1095`), `/api/skills` (`:1078`), or `write_note` (`hermes_okf.py:244`) |
| **TN-8.1–8.3**: ticket scoping, human gate, CI enforcement | **TRUE** | Issue-prefixed commits; `AGENTS.md:48,67-71,109`; `pre-commit.yml:24,29,39,50,61,71,78` |
| **TN-8.4**: base images pinned | **FALSE** | `compose:60` (`:latest`), `:13`, `:36`; `Dockerfile:6`; no lockfile exists |
| **TN-8.5**: connector review process | **FALSE** | No `mcp`/`connector` concept in repo |
| **TN-9.2**: backup verifiable | **TRUE** | `backup.sh:146-157` (manifest), `:180-193` (retention), `:209-213` (integrity test) |
| **TN-9.2**: backup scheduled | **FALSE** | No cron/systemd/launchd/timer anywhere |
| **TN-9.4**: script-first discipline | **TRUE** | `AGENTS.md:157` (Rule 8 header), reproducibility guarantee at `:161`; 9 scripts; `pre-commit.yml:61-69` |

---

## Appendix B — Open Remediation Items

| # | Control | Item | Effort |
|---|---|---|---|
| 1 | `TN-2.12` | Authenticate all `POST` handlers in `server.py`; remove wildcard CORS. **GitHub issue drafted — see `docs/issue-draft-unauthenticated-terminal.md`.** | S |
| 2 | `TN-5.2` | Add `cap_drop: [ALL]` to the `hermes` service in `docker-compose.yml`; correct the false assertion at `README.md:70`; add a CI assertion so the claim cannot drift again | S |
| 3 | `TN-8.8` | Commit this document; add it to the pre-commit review scope | S |
| 4 | `TN-8.4` | Digest-pin `zefhemel/silverbullet`; then `caddy`, `postgres`, `python`; add a lockfile | S |
| 5 | `TN-9.5` | Document halt semantics, including container-log loss on `down` | S |
| 6 | `TN-1.1` | Publish the input-channel inventory (the TN-1 table is the draft) | S |
| 7 | `TN-3.6` | Measure and record the basis for `max_parallel_requests: 1` | M |
| 8 | `TN-2.1` | Tool inventory with scope, reversibility, blast radius | M |
| 9 | `TN-7.1` | Append-only action log (Sprint 0 / #28) | M |
| 10 | `TN-6.1` | Network-layer egress mediation for agent shell and browser | M |
| 11 | `TN-3.1`/`TN-3.2` | Behavioural budgets with automatic halt, built into the agent loop | L |
| 12 | `TN-4.3`/`TN-4.4` | Provenance fields and localized git history (FD-3 / #31, `README.md:190`) | L |
| 13 | `TN-1.2`/`TN-1.3` | Trust-tiering and structural instruction separation | L |

---

*This document is the active architectural benchmark for Project Titan and the spec Gemini/Antigravity should generate code against. Status markers reflect what's actually implemented, not what's planned — update them in the same PR that closes a gap, not separately. **A marker may only be set to 🟢 with a citable enforcing `file:line`;* otherwise mark it 🔴 and add it to Appendix B.*
