# Agentic Governance & Security Controls (AGSC v1.0.0)
### Created by COHUMAIN Labs & SafeAlign AI

[![Standard: v1.0.0](https://img.shields.io/badge/standard-v1.0.0-1F7DF0.svg)](https://himjoe.github.io/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI/)
[![License: CC BY 4.0](https://img.shields.io/badge/license-CC_BY_4.0-6A45C8.svg)](LICENSE)
[![Controls: 25 Unified Controls](https://img.shields.io/badge/controls-25-17A45A.svg)](CONTROLS.md)
[![Pillars: S | A | G | S](https://img.shields.io/badge/pillars-Safety%20|%20Alignment%20|%20Governance%20|%20Security-1F7DF0.svg)](pillars.md)

> **Official Standard Documentation**: [himjoe.github.io/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI](https://himjoe.github.io/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI/)  
> **Upstream Standard Repository**: [github.com/HimJoe/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI](https://github.com/HimJoe/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI)  
> **Authoring Organizations**: [COHUMAIN Labs](https://www.cohumain.ai/research) (Responsible-AI Research) & [SafeAlign AI](https://safealignai.io/) (Enterprise Agent Governance & Security)  
> **Implementation Target**: [brainsOS](https://brainsos.ai) • [Patterns at Scale](https://patternsatscale.com)

---

## 1. Attribution & Citation Statement

In compliance with the **Creative Commons Attribution 4.0 International License (CC BY 4.0)**, this directory contains the canonical specifications, catalog, and machine-readable data files of the **Agentic Governance & Security Controls (AGSC)** standard:

* **Copyright**: © 2026 **COHUMAIN Labs** & **SafeAlign AI**.
* **Authors**: COHUMAIN Labs ([cohumain.ai/research](https://www.cohumain.ai/research)) and SafeAlign AI ([safealignai.io](https://safealignai.io/)).
* **License**: [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE).
* **Citation Form**:
  > *"COHUMAIN Labs & SafeAlign AI — Agentic Governance & Security Controls (AGSC v1.0.0), 2026."*

**brainsOS** ([brainsOS.ai](https://brainsos.ai)) acknowledges and thanks COHUMAIN Labs and SafeAlign AI for their pioneering work in synthesizing agentic safety, alignment, governance, and threat modeling into an open, vendor-neutral standard. brainsOS adopts this framework as its **architectural North Star** for edge execution and bare-metal agent containment.

---

## 2. Why AGSC Matters: The Inverted Failure Mode

Traditional IT security assumes that when software fails, it *stops*. For autonomous agentic AI, **the failure mode inverts**:
1. **The agent fails by *continuing***: A compromised or looping agent operates fully functional, executing unauthorized actions at machine speed across internal tools and APIs before a human operator can react. The safe state must be deterministically **"stopped," not "restored."**
2. **The model itself is the attack surface**: Prompt injection is an exploit embedded directly in plain natural language inside data, completely invisible to static code scanners.
3. **Autonomous orchestration is the primary risk**: Threat intelligence across 832 malicious actors demonstrates that the highest-risk operations are distinguished not by individual exploits, but by agents **autonomously chaining multi-stage attack workflows together**.

The AGSC framework directly addresses these risks by unifying governance (*what is the agent allowed to decide and do?*) with security (*what can a compromised agent be forced to do?*).

---

## 3. brainsOS Implementation Nuance: Aspirational Conformance Roadmap

> [!NOTE]
> ### 🚧 Project Status: Active Development (Alpha)
> **brainsOS is an open-source alpha implementation.**
> Full certification across all 25 COHUMAIN controls is an **active engineering target and aspirational roadmap**, not a certified claim. We publish this complete catalog in the open to build transparently, benchmark progress against an established standard, and invite community contributions.

To maintain absolute engineering integrity, we track implementation across three transparent conformance tiers:

| Status Tier | Definition | brainsOS Implementation Examples Today |
|---|---|---|
| 🟢 **Implemented & Verified** | Codified in repository; covered by automated verification scripts. | • `SAF-02` (Emergency Stop / Kill Switch via `scripts/control/emergency-stop.sh`)<br>• `SEC-02` (Least-Privilege Authorization via `cap_drop: [ALL]` & proxy keys)<br>• `SEC-07` (Memory Lifecycle Security via `packages/brainsOS-memory` OKF purity engine) |
| 🟡 **In Active Development** | Functional tooling in place; end-to-end integration or automated tests ongoing. | • `SAF-01` (Autonomous System Oversight via Langfuse v4 OpenTelemetry tracing)<br>• `GOV-08` (Environmental & Carbon Governance via `packages/brainsOS-queue` & telemetry)<br>• `SEC-04` (Observability & Anomaly Detection via mitmproxy egress flow audits) |
| ⚪ **Aspirational / Roadmap** | Formal specification established; scheduled for future engineering phases. | • `SEC-06` (Automated Security Testing & Red-Teaming harness)<br>• `ALN-04` (Formal Model Explainability & Rationale validation)<br>• `ALN-05` (Cryptographic Action Attribution & Signature verification)<br>• `GOV-05` (Automated Continuous Model Evaluation pipeline) |

---

## 4. The 4 Control Pillars & 25-Control Catalog

The AGSC standard organizes 25 unified controls across four core domains:

```
┌────────────────────────────────────────────────────────────────────────┐
│               COHUMAIN ACSG UNIFIED CONTROLS FRAMEWORK                 │
├─────────────────────┬────────────────────┬─────────────────────────────┤
│ 🛡️ SAFETY (SAF)    │ ⚖️ ALIGNMENT (ALN) │ 🏛️ GOVERNANCE (GOV)         │
│ • SAF-01 Oversight  │ • ALN-01 Boundary  │ • GOV-01 Data Provenance    │
│ • SAF-02 Kill Switch│ • ALN-02 Oversight │ • GOV-02 Change Governance  │
│ • SAF-03 Misuse Prev│ • ALN-03 Interp.   │ • GOV-03 Supply Chain       │
│ • SAF-04 Accuracy   │ • ALN-04 Explain.  │ • GOV-04 Training Gov       │
│ • SAF-05 Safeguards │ • ALN-05 Attr.     │ • GOV-05 Model Eval         │
│                     │                    │ • GOV-06 Drift Management   │
│                     │                    │ • GOV-07 Lifecycle/Registry │
│                     │                    │ • GOV-08 Environmental/Carbon│
├─────────────────────┴────────────────────┴─────────────────────────────┤
│ 🔒 SECURITY & ISOLATION (SEC)                                          │
│ • SEC-01 Multi-Agent Coordination        • SEC-05 AI Threat Modeling   │
│ • SEC-02 Least-Privilege Authorization   • SEC-06 Security Testing     │
│ • SEC-03 Prompt Injection Defense        • SEC-07 Memory Purity Guard  │
│ • SEC-04 Observability & Incident Resp.                                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Catalog Contents & Canonical Files

All files in this directory are reproduced from the [canonical upstream repository](https://github.com/HimJoe/Agentic-governance-and-security-controls-by-COHUMAIN-Labs-and-Safealign-AI):

| File | Description |
|---|---|
| **[`CONTROLS.md`](CONTROLS.md)** | **The Complete 25-Control Catalog**: Detailed breakdown of objectives, key requirements, audit evidence, risks closed, and regulatory mappings for each control. |
| **[`LICENSE`](LICENSE)** | The Creative Commons Attribution 4.0 International License text. |
| **[`controls.json`](controls.json)** | Machine-readable full JSON dataset of all 25 controls, criteria, and crosswalk IDs for automated CI/CD compliance testing. |
| **[`controls.csv`](controls.csv)** | Tabular CSV export for compliance matrices, spreadsheet tracking, and auditor reviews. |
| **[`the-standard.md`](the-standard.md)** | Normative standard specifications, core definitions, and foundational principles. |
| **[`pillars.md`](pillars.md)** | Architectural deep dive into the four security and governance pillars. |
| **[`methodology.md`](methodology.md)** | Assessment, evidence verification, and audit methodology. |
| **[`conformance.md`](conformance.md)** | Conformance tier criteria (Tier 1 Baseline, Tier 2 Operational, Tier 3 Advanced). |
| **[`frameworks/`](frameworks/)** | Regulatory and taxonomy crosswalks: |
| ├── [`mit-ai-risk.md`](frameworks/mit-ai-risk.md) | Mapping to MIT AI Risk Taxonomy (v1.0). |
| ├── [`mitre-atlas.md`](frameworks/mitre-atlas.md) | Mapping to MITRE ATLAS Adversarial Threat Matrix. |
| ├── [`mitre-attack.md`](frameworks/mitre-attack.md) | Mapping to MITRE ATT&CK Enterprise Framework. |
| └── [`regulatory-crosswalk.md`](frameworks/regulatory-crosswalk.md) | Mapping to EU AI Act (Arts. 14, 15, 50), NIST AI RMF, and ISO 42001. |

---

## 6. How brainsOS Implements the Controls

### 1. Hard Physical Boundaries (`SAF-02`, `ALN-01`)
Traditional cloud AI relies on financial billing ceilings. When an agent loops destructively, it continues burning watts. brainsOS operationalizes `SAF-02` (Emergency Stop) through deterministic physical and network kill switches:
* Invalidating virtual proxy keys immediately freezes completions.
* Executing `./scripts/control/emergency-stop.sh <tenant_id>` terminates agent execution deterministically.
* Asynchronous queue management (`packages/brainsOS-queue`) pauses, drains, or drops runaway worker processes before silicon hits thermal limits or battery reserves collapse.

### 2. Zero-Trust Isolation & Identity Pinning (`SEC-02`, `SEC-07`)
* **Least-Privilege Host Sandboxing (`SEC-02`)**: Agents run in unprivileged containers with dropped Linux capabilities (`cap_drop: [ALL]`), zero Docker socket exposure, and no direct access to host inference or the control plane database.
* **Memory Plane Purity (`SEC-07`)**: Preserves long-term memory exclusively in human-auditable flat Markdown files using the Open Knowledge Format (OKF). Binary indices, SQLite databases, and packages are strictly forbidden in `/memories` and reside in `/workspace`.

### 3. In-Transit Egress Credential Injection (`SEC-02`, `SEC-03`)
* Containers never hold raw ambient secrets or GitHub tokens.
* All outbound traffic passes through the Tool Egress Gateway (`titan-net-egress-proxy:8082`), which intercepts requests, verifies container IP identity on `titan-internal`, injects credentials in transit, and redacts sensitive tokens from flow inspection logs (`mitmweb`).

### 4. Environmental & Carbon Governance (`GOV-08`)
* In tandem with **Project Millijoule (mJ)**, brainsOS modulates compute workloads to track real-time solar generation and battery state-of-charge, scaling compute down during grid stress or thermal saturation.
