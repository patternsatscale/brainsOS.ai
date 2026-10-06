# Walkthrough: Issue Pruning, Lab Work Migration, and GitHub Epic Standard

## Summary of Accomplishments

In this session, we executed a complete review, reorganization, and pruning of the issue backlog across `patternsatscale/brainsOS.ai` and the private fleet repository. We established the 3-step GitHub-native Epic standard, migrated proprietary lab work to the private fleet repository, and resolved a critical decoupled path resolution bug (#243).

---

### 1. Lab Work & Private Fleet Migration (Rule 11 & Rule 14)
- **Private Fleet Migration**:
  - Transferred `docs/lab-work/` (presentations, architecture specs, Cindy Pawford lab documents, and orchestration guides) to the private fleet repository: `docs/lab-work/`.
  - Staged, committed, and pushed to the private fleet repository (`main` branch commit `3686878`).
  - Migrated all stranded thread memories from `settings/data/agent_memories/` to canonical `agent_memories/<agent_id>/threads/` (commit `8652a9f`).
- **Private Fleet Issue Tracker Initialization (3 Epics, 13 Child Tasks)**:
  - **Epic #6**: `[Epic] Cindy Pawford: Autonomous Publishing Pipeline & Promotion Circuit Breakers`
    - Sub-task #1: `[Publishing / Promotion] Deterministic Promotion Circuit Breakers (Staging to Prod)`
    - Sub-task #2: `[Publishing / Safety] Semantic Safety Circuit Breakers & Assertion Filtering`
    - Sub-task #3: `[Publishing / Review Gate] Secondary Multi-Agent Editorial Review Gate`
    - Sub-task #4: `[Publishing / Telemetry] Editorial KPI Grid & Performance Telemetry`
    - Sub-task #5: `[Comms / Inter-Agent] Inter-Agent Email Communication & Editorial Collaboration` *(replacing social arena)*
  - **Epic #11**: `[Epic] Cindy Pawford: Autonomous Comic Strip Generation`
    - Sub-task #7: `[Comic / Reader] Tool-Less Reader Context & Content Ingestion Engine`
    - Sub-task #8: `[Comic / Narrative] Script & Panel Dialogue Generation Engine`
    - Sub-task #9: `[Comic / Rendering] Panel Image Synthesis & SVG/HTML Comic Layout Engine`
    - Sub-task #10: `[Comic / Web] Web Archive Integration in agent_apps/cindypawford/site`
  - **Epic #16**: `[Epic] Physical Thermodynamic Computing: Baseline Power Telemetry & Stella 50 EM Integration`
    - Sub-task #12: `[Telemetry / Hardware] Stella 50 EM Energy Meter Setup & Local Ingress (MQTT/HTTP)`
    - Sub-task #13: `[Telemetry / Persistence] Winter Baseline Power Draw & Heating Degree Days (HDD) Logging`
    - Sub-task #14: `[Telemetry / Correlator] Compute Workload Energy Attribution (Joules per Agent Task)`
    - Sub-task #15: `[Telemetry / Dashboard] Real-Time Power & Thermal Metric Visualizer`
- **`brainsOS.ai` Cleanliness**:
  - Removed `docs/lab-work/` from `brainsOS.ai`.
  - Updated [`AGENTS.md`](file:///Users/pats/Development/brainsOS.ai/AGENTS.md) Section 0 and Rule 11 to record that all experimental documentation, persona critiques, and lab work reside exclusively within the private fleet repository.

---

### 2. GitHub Issue Pruning (53 Issues Closed with Audit Trail)
We reduced open issues from **99 to 46**, closing 53 stale, out-of-scope, or superseded issues with dedicated audit comments:
- **Category A (19 Lab Work & Persona Issues)**: #28–#35, #37–#41, #42–#45, #89, #96 closed with audit notes referencing relocation to the private fleet repository under Rule 14.
- **Category B (20 Phase 3 Forgejo/Silverbullet Micro-PRs)**: #46–#65 closed as superseded by the Two-Repository Git architecture.
- **Category C (5 Stale / Implemented Tickets)**: #158 (implemented by #206), #76, #77, #165, #196 closed.
- **Category D (9 Authelia / Iframe Shell Tickets)**: #226–#234 closed as superseded by the Dashy + Authentik + Caddy architecture.

---

### 3. Standardized Milestone & Epic Architecture

#### The 3-Step GitHub-Native Epic Standard
1. **`epic` Label**: Created `#3E1C87` (dark purple) for parent container tickets.
2. **Parent Issues with GFM Task Lists**: Formatted with `- [ ] #<issue_number>` to activate GitHub's native progress bar and bidirectional cross-referencing.
3. **Active Milestones**:
   - **`MVP v0.1 — Core Appliance & Unified Experience`**: 13 open issues (Portal, DLQ, Runner, Hermes WebUI).
   - **`v0.2 — Security & Sandboxing Hardening`**: 14 open issues (Capabilities, UID, key expiry, audit ledger).
   - **`v0.3 — Governance & ACSG Conformance`**: 8 open issues (Automated AGSC Auditor, attestation).
   - **`Backlog / Future Research`**: 13 open issues (vLLM, Whisper STT, comparative benchmarking).
   *(All 9 legacy empty milestones were closed).*

#### Epics Established:
- **Epic #247**: `[Epic] BrainsOS Unified Portal: Dashy Dashboard + Authentik SSO + Caddy Ingress`
  - Child task #245: `[Portal / SSO] Authentik Identity Provider & Caddy forward_auth Gateway`
  - Child task #246: `[Portal / UI] Dashy Unified Dashboard with BrainsOS Dark Theme, Plane Sections & Health Checks`
  - Child task #243: `[Memory Plane / Config] Fix Corrupted Relative Path Resolution` *(Completed!)*
  - Child task #207: `[Agent Plane] Expose Hermes WebUI via Caddy`
  - Child task #225: `[Fleet/Comms] Ingress DLQ Monitoring, Operator Alerting & Redrive Utility`
- **Epic #214**: `[Epic] Autonomous AGSC Conformance Auditor (AGENT.MD), Public Attestation, and CI/CD Verification Pipeline` (Sub-tasks #215–#221).
- **Epic #235**: `[Epic] BrainsOS System View & Fleet Operations Dashboard` (Sub-tasks #236–#242).

---

### 4. Critical Bug Remediation (#243)
- **Problem**: In decoupled mode (`BRAINSOS_DATA_DIR=/path/to/private-fleet`), `AgentProfile.from_manifest_yaml` evaluated manifest base incorrectly and failed to normalize `./data/agent_memories/...`, creating stranded nested directories like `fleet/settings/data/agent_memories/`.
- **Solution**:
  - Updated `from_agent_dict` in [`packages/brainsOS-agent/brainsos_agent/models.py`](file:///Users/pats/Development/brainsOS.ai/packages/brainsOS-agent/brainsos_agent/models.py) to resolve scoped paths against `get_memories_dir()` and `get_workspaces_dir()`, stripping redundant `./data/` prefixes.
  - Updated `from_manifest_yaml` base path resolution to recognize standalone `settings/` directories.
  - Normalized [`config/default_settings/agents.yaml`](file:///Users/pats/Development/brainsOS.ai/config/default_settings/agents.yaml) and private fleet `settings/agents.yaml`.
  - Migrated all stranded thread memory files in `settings/data/agent_memories/` to canonical `agent_memories/<agent_id>/threads/`.
  - Added regression test `test_decoupled_manifest_path_resolution_issue_243` in `packages/brainsOS-agent/tests/test_config.py`.
  - Closed issue #243 and checked off in Epic #247.

### 5. Backlog Grooming & Idea Registry Establishment (`Ideas ➔ Epics ➔ Sub-issues`)
- **The Core Maturation Flow**:
  Formally codified the 3-tier hierarchy in [`PLANNING.md`](file:///Users/pats/Development/brainsOS.ai/PLANNING.md) and [`PLAN.md`](file:///Users/pats/Development/brainsOS.ai/PLAN.md):
  `💡 Ideas (Backlog)` ➔ `📦 Epics (Active Milestones)` ➔ `🔨 Sub-issues (Execution via AGENTS.md)`
- **`idea` Label**: Created `#FBCA04` (warm gold) on both `patternsatscale/brainsOS.ai` and the private fleet repository.
- **Redundancy Closures (5 Issues Closed)**:
  - **#167**: Closed (implemented by Epic #206 Autoresponder).
  - **#15**: Closed (handled by `brainsOS-queue` and worker daemons).
  - **#86**: Consolidated into Idea #85.
  - **#83**: Consolidated into Idea #82.
  - **#23**: Consolidated into Idea #22.
- **Relocations to Private Fleet Repository**:
  - **#105**: Relocated appliance deploy runner & webhook listener to private fleet issue tracker.
- **Idea Registry Issues in `Backlog / Future Research` (11 Active Ideas)**:
  - **#251**: `[Idea] AWS Cloud Deployment Topology & SST Infrastructure (Container Parity vs. Managed Services)`
  - **#250**: `[Idea] Windows Subsystem for Linux (WSL 2) Host Development Support`
  - **#249**: `[Idea] Deep Observability: Langfuse Telemetry for mitmproxy HTTPS Traffic & Guarded Console Commands`
  - **#248**: `[Idea] Central Data Services for Agents: Multi-Tenant SQL & Vector Stores with Ephemeral Token Injection`
  - **#163**: `[Idea] AI Communications Gateway: Ingest Telegram / Signal Messages & Bridge to Agent Email`
  - **#85**: `[Idea] Dual Inference Engines: Compare vLLM vs. Ollama with Langfuse Telemetry Benchmarks`
  - **#82**: `[Idea] Multi-Runner Architecture: Support & Compare OpenHands, OpenClaw, and Hermes Runners`
  - **#27**: `[Idea] Vector Database Memory Acceleration: Semantic Retrieval Layer in Front of OKF Markdown Memories`
  - **#22**: `[Idea] Frontier Model Consultants: Gated Consultation Protocol for Complex Architectural Inquiries`
  - **#14**: `[Idea] Fleetwide Skills Registry: Shared & Discoverable Skill Catalog for All Agents`
  - **#13**: `[Idea] Audio Plane: Host Whisper STT & Kokoro TTS via LiteLLM`
### 6. Bug & Defect Protocol Establishment (`🐛 Bugs / Defects`)
- **Dedicated Milestone**: Reopened and configured milestone **`Bugs / Defects`** across both `patternsatscale/brainsOS.ai` and the private fleet repository.
- **Bug Tagging & Triage**:
  - Re-aligned issue **[#109](https://github.com/patternsatscale/brainsOS.ai/issues/109)** (`[Phase 4: Security] Remediate Live Process UID Checks & Cross-Tenant Storage Probes`) with the `bug` label and moved it to `Bugs / Defects`.
  - Codified the intake, reproduction, and mandatory regression gate in [`PLANNING.md`](file:///Users/pats/Development/brainsOS.ai/PLANNING.md) and [`PLAN.md`](file:///Users/pats/Development/brainsOS.ai/PLAN.md).

### 7. Two-Tier Label Taxonomy & Default Tag Purge
- **Unused Default GitHub Label Purge**:
  - Purged 7 cluttering default labels across both `brainsOS.ai` and the private fleet repository: `accessibility`, `duplicate`, `good first issue`, `help wanted`, `invalid`, `question`, `wontfix`.
- **Subsystem & Feature Labels Created**:
  - Created 6 dedicated subsystem labels in `brainsOS.ai`: `portal` (`#1D76DB`), `system-view` (`#5319E7`), `comms` (`#0E8A16`), `agent-plane` (`#F9D0C4`), `memory` (`#D93F0B`), `control-plane` (`#C2E0C6`).
- **Two-Tier Tagging Rollout**:
  - Applied the two-tier tagging discipline across all 46 open issues in `brainsOS.ai`:
    1. **Tier 1 (Work Type)**: Exactly one of `epic`, `feature`, `task`, `bug`, `idea`, or `docs`.
    2. **Tier 2 (Subsystem/Domain)**: Multi-dimensional filters (`portal`, `system-view`, `agent-plane`, `control-plane`, `comms`, `memory`, `security`, `governance`, `infra`, `UI/UX`).
- **Documentation Alignment**:
  - Updated [`PLANNING.md`](file:///Users/pats/Development/brainsOS.ai/PLANNING.md), [`PLAN.md`](file:///Users/pats/Development/brainsOS.ai/PLAN.md), and [`AGENTS.md`](file:///Users/pats/Development/brainsOS.ai/AGENTS.md) in `brainsOS.ai` and the private fleet repository to eliminate obsolete `type:*` references and codify the Two-Tier Tagging discipline.

---

## Verification Results

### 1. Test Suite Pass
```
.venv/bin/pytest packages/brainsOS-agent/tests/
============================== 27 passed in 0.98s ==============================
```

### 2. Shell Scripts Syntax Validation
```
find scripts -type f -name "*.sh" -exec bash -n {} +
# (0 errors)
```

### 3. Active GitHub Milestones & Label Count
```
MVP v0.1 — Core Appliance & Unified Experience: 13 open issues
v0.2 — Security & Sandboxing Hardening: 13 open issues
v0.3 — Governance & ACSG Conformance: 8 open issues
Bugs / Defects: 1 open issue
Backlog / Future Research: 11 open issues
Total Open Issues in brainsOS.ai: 46
Active Labels in brainsOS.ai: 16 (6 work types, 10 subsystems/domains)
Active Labels in private fleet repository: 12
```

