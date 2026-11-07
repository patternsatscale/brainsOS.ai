---
name: COHUMAIN Control Implementation & Verification
about: Propose or claim a COHUMAIN AGSC (Tier 1 / Tier 2) control implementation, audit artifact, or verification script
title: "[COHUMAIN <Control-ID>] <Control Name>: <Concise Deliverable>"
labels: ["task", "governance", "cohumain:tier1"]
assignees: []
---

## 1. Control Identification & Conformance Tier
<!-- Reference the canonical catalog in docs/cohumain/CONTROLS.md and docs/cohumain/conformance.md -->
- **Control ID & Name**: `e.g., SAF-01 — Autonomous System Oversight`
- **AGSC Pillar**: `Safety (SAF) | Alignment (ALN) | Governance (GOV) | Security (SEC)`
- **Target Conformance Tier**:
  - [ ] **Tier 1 — Foundational (8 Controls)** (`cohumain:tier1`: `SAF-01`, `SAF-02`, `SAF-03`, `ALN-01`, `ALN-02`, `SEC-02`, `SEC-03`, `SEC-04`)
  - [ ] **Tier 2 — Managed (+10 Controls, 18 Cumulative)** (`cohumain:tier2`: `SAF-04`, `SAF-05`, `ALN-05`, `GOV-01`, `GOV-02`, `GOV-05`, `SEC-01`, `SEC-05`, `SEC-06`, `SEC-07`)
  - [ ] **Tier 3 — Assured (+7 Controls, 25 Cumulative)** (`ALN-03`, `ALN-04`, `GOV-03`, `GOV-04`, `GOV-06`, `GOV-07`, `GOV-08`)
- **Contributor Scope Label**: `cohumain:tier1` / `cohumain:tier2` / `good-first-issue`

## 2. Threat Mitigated & Risk Closed
<!-- Describe the real-world failure mode or adversarial vector this implementation addresses -->
- **Normative Objective**: <!-- Copy or summarize the Objective from docs/cohumain/CONTROLS.md -->
- **Primary Threat / Failure Mode Mitigated**: <!-- What autonomous failure, prompt injection, or boundary breach does this prevent? -->
- **Framework Crosswalk**: <!-- e.g., MIT AI Risk Taxonomy, MITRE ATLAS, MITRE ATT&CK, EU AI Act Art. 14/15, NIST AI RMF, ISO 42001 (see docs/cohumain/frameworks/) -->

## 3. Implementation Plane (BRAINS L1–L7 Architecture)
<!-- Check the architectural planes and standalone packages modified by this control -->
- [ ] **L7: Communications, Ingress & Operator Console** (`config/caddy/`, Authentik SSO, SOGo/Postfix, Gitea, Operator IDE)
- [ ] **L6: Autonomous Agent Execution Plane** (`packages/brainsOS-agent`, `packages/brainsOS-runner`, `config/default_settings/agents.yaml`)
- [ ] **L5: Memory Plane & Tool Sandbox** (`packages/brainsOS-memory`, `packages/brainsOS-queue`, `packages/brainsOS-mcp`, `packages/brainsOS-telemetry`)
- [ ] **L4: Routing, Security & ACSG Control Plane** (`config/litellm/`, `config/egress/`, `brainsos-control-litellm-db`)
- [ ] **L3: Host Inference Plane** (Loopback-bound `127.0.0.1:11434` Ollama / vLLM guardrails)
- [ ] **L2: Virtualization & Isolated Bridge Networks** (`docker-compose.yml`, `docker/compose/`, network segmentation)
- [ ] **L1: Physical & Hardware Layer** (`packages/brainsOS-appliance`, host scripts, thermal/energy telemetry)

## 4. Acceptance Criteria & Audit Evidence
<!-- Map directly to the 'Key requirements' and 'Evidence' sections of the control in docs/cohumain/CONTROLS.md -->
- [ ] **Requirement 1**: <!-- e.g., Codified configuration or runtime guardrail implemented -->
- [ ] **Requirement 2**: <!-- e.g., Audit log / OpenTelemetry trace / OKF evidence emitted -->
- [ ] **Automated Verification Script**: Idempotent test script added or updated under `scripts/verify/` (or `pytest` suite under `packages/`).
- [ ] **Documentation & Tracker Update**: Conformance status updated in `README.md` and `docs/cohumain/README.md`.

## 5. Plane Separation & Zero-Trust Constraints
<!-- Mandatory brainsOS architectural guardrails (AGENTS.md Rules 1–14) -->
- [ ] **Memory Plane Purity (`SEC-07` / Rule 1)**: Strictly pure OKF Markdown in `/memories`. Zero SQLite `.db`, binary, or cache files in `/memories`.
- [ ] **Inference Boundary & Serialization (`ALN-01` / Rule 2 & 3)**: Agents never route directly to host inference (`127.0.0.1:11434`); all completions route via LiteLLM (`:4000`) with `max_parallel_requests: 1`.
- [ ] **Least-Privilege Host Sandboxing (`SEC-02` / Rule 4)**: Unprivileged execution (`PUID=1000`, `cap_drop: [ALL]`), zero `/var/run/docker.sock` mounts, and no `network_mode: host`.
- [ ] **Zero Ambient Secrets (`SEC-02` / Rule 10)**: No raw tokens in agent containers; outbound credentials injected in transit via `brainsos-agent-egress-proxy:8082`.

## 6. Verification Steps
<!-- Exact commands a maintainer or CI pipeline runs to verify conformance -->
```bash
# 1. Shell script syntax validation
find scripts -type f -name "*.sh" -exec bash -n {} +

# 2. Control-specific verification script or pytest suite
# e.g., ./scripts/verify/verify-<control-id>.sh
# e.g., make test && make lint
```
