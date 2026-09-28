# Control Catalog

> The complete 25-control catalog. Machine-readable versions: [`controls.json`](controls.json) | [`controls.csv`](controls.csv).

## 🛡️ Safety  (5 controls)

### `SAF-01`, Autonomous System Oversight

**Type:** AI-Native | **Surface:** Agentic | **Conformance tier:** T1

**Objective.** Continuously observe autonomous agent behaviour against a defined baseline and enable timely human intervention.

**Key requirements**

- Behavioural baseline documented per agent (expected action types, frequency, value/scope limits) and signed off before go-live.
- ≥99% of autonomous actions emit a structured trace (actor, action, target, rationale) within 1 second of execution.
- ≥5 deviation thresholds defined (e.g., out-of-pattern tool calls, action-rate spikes) each wired to an alert and a named responder.
- Monthly oversight review; full re-test after any model, prompt, or tool change.

**Evidence**

- Signed, versioned behavioural-baseline specification.
- Action-trace sample with timestamps demonstrating <1s emission.
- Threshold/alert configuration export + 3 most-recent triggered alerts with dispositions.
- Monthly oversight-review minutes with reviewer sign-off.

**Risk it closes.** A procurement agent told to 'minimise stock-outs' begins auto-raising purchase orders nightly; the 6× volume shift goes unnoticed for two weeks because uptime monitoring only watched availability, not behaviour.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.1 AI pursuing its own goals in conflict with human goals/values | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet), TA0011 Command and Control (tactic) | Art. 14, 15 | MANAGE 4.1; MEASURE 2.x | A.6.2, A.9 |

_Defence note: Detects the autonomous killchain orchestration the Navigator flags as the top unscored risk._

---

### `SAF-02`, Emergency Stop & Containment (Kill Switch)

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T1

**Objective.** Provide a single, fast mechanism to halt, contain and isolate an AI system on a safety or security trigger.

**Key requirements**

- Single authorized mechanism that on activation halts execution, revokes the agent's credentials, and isolates affected components, covering BOTH the safety-triggered halt and the security-triggered containment scenario.
- Halt achieved within a defined SLA (target ≤5s) at infrastructure AND application layers.
- Activation restricted to named roles, AI Safety Lead (safety halt) and Cybersecurity (security containment); 100% of activations logged with actor, reason, scope.
- Monthly test for agentic/high-risk systems; documented recovery procedure; explicitly linked to the incident-response workflow.

**Evidence**

- Emergency-stop/containment procedure naming both activation modes and authorized roles.
- Monthly halt-test records with measured halt latency vs SLA.
- Activation/audit log sample + evidence of credential revocation and component isolation.
- Recovery-drill record and linked IR runbook reference.

**Risk it closes.** An email-integrated agent is compromised by indirect prompt injection and starts exfiltrating documents. Operators need ONE action that stops it, revokes its token, and isolates the connector, not a safety halt and a separate security process racing each other.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.1 AI pursuing its own goals in conflict with human goals/values | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… | TA0011 Command and Control (tactic), T1020 Automated Exfiltration, T1219 Remote Access Software | Art. 14, 15 | MANAGE 4.1 | A.6.2 |

_Defence note: Containment severs C2 and halts exfiltration / remote control by a weaponised agent._

---

### `SAF-03`, Content Safety & Misuse Prevention

**Type:** AI-Native | **Surface:** GenAI | **Conformance tier:** T1

**Objective.** Prevent generation of harmful, unsafe or policy-violating content and resist misuse and jailbreaks.

**Key requirements**

- Inline input/output content filters active on 100% of generative responses (toxicity, harmful instructions, regulated-claim categories).
- Documented red-team test set exercised pre-deployment and after each model/prompt change, with a defined pass threshold.
- Safety-violation monitoring + escalation path; user-report mechanism for problematic outputs.

**Evidence**

- Filter policy/config + proof of coverage across all endpoints.
- Red-team test report: attempt categories, success rate, remediation.
- Blocked/escalated-output log and user-report queue with dispositions.

**Risk it closes.** A customer-facing assistant is jailbroken into producing prohibited or unsafe instructions (e.g., enabling fraud or harm) that no content control intercepts.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 1.2 Exposure to toxic content | AML.T0054 LLM Jailbreak
AML.T0048 External Harms (Financial … | T1587 Develop Capabilities, T1587.001 Develop Capabilities: Malware, T1027 Obfuscated Files or Information | Art. 15 | MEASURE 2.6, 2.7; MANAGE 2.x | A.6.2 |

_Defence note: Prevents the model being misused to develop malware/obfuscation, the most common AI-assisted attack techniques observed._

---

### `SAF-04`, Output Factual Accuracy & Anti-Hallucination

**Type:** AI-Native | **Surface:** GenAI | **Conformance tier:** T2

**Objective.** Ensure factual grounding of generative outputs and detect and mitigate hallucination.

**Key requirements**

- Groundedness/factuality benchmark defined per use case with a minimum acceptable score.
- Source attribution/citation enabled for fact-bearing outputs; uncertainty signalled when confidence is low.
- Periodic factuality evaluation against a trusted reference set; monthly for decision-support uses.

**Evidence**

- Benchmark definition + most-recent scored results vs threshold.
- Sample outputs showing citations / uncertainty flags.
- Evaluation log + remediation actions on detected drift.

**Risk it closes.** A knowledge assistant fabricates a confident citation to a non-existent source; a user relays it as fact, creating misinformation and liability exposure.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 3.1 False or misleading information | AML.T0048 External Harms (Financial / Reputational / Societa… | N/A | Art. 15 | MEASURE 2.3 | A.6.2 |

_Defence note: N/A, factual-accuracy / safety control, not an adversarial-security technique._

---

### `SAF-05`, AI Output Monitoring & Safeguards

**Type:** AI-Native | **Surface:** Both | **Conformance tier:** T2

**Objective.** Monitor AI outputs at runtime for bias, harm, hallucination and drift, gating regulated decisions to humans.

**Key requirements**

- Runtime monitoring of output for bias, hallucination, harmful content and quality drift, with defined thresholds.
- Human-in-the-loop gate mandatory before any AI output enters a regulated decision or process.
- High-risk: continuous monitoring + monthly review; documented escalation on threshold breach.

**Evidence**

- Monitoring dashboard + threshold configuration.
- HITL gate evidence (approval records on regulated outputs).
- Monthly review report + escalation tickets.

**Risk it closes.** A triage/prioritisation model gradually drifts and begins down-ranking critical cases; with no output monitoring the degradation surfaces only at the next audit.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 3.1 False or misleading information | AML.T0048 External Harms (Financial / Reputational / Societa… | T1587 Develop Capabilities, T1020 Automated Exfiltration | Art. 15, 72 | MEASURE 2.x; MANAGE 4.1 | A.9 |

_Defence note: Detects harmful generated artefacts and anomalous output/exfiltration volumes._

---

## 🎯 Alignment  (5 controls)

### `ALN-01`, Autonomy Boundary Control

**Type:** AI-Native | **Surface:** Agentic | **Conformance tier:** T1

**Objective.** Constrain each agent to an explicit, technically-enforced action space.

**Key requirements**

- Declarative allow/deny action policy per agent: permitted actions, restricted actions, value/scope caps, approval-required actions.
- Hard technical enforcement at the gateway (deny-by-default); boundaries cannot be overridden by prompt content.
- Boundary-violation detection with real-time block + alert; 100% of attempts logged.
- Quarterly enforcement test: attempt each restricted action and confirm it is blocked.

**Evidence**

- Versioned action-policy file per agent.
- Gateway configuration showing deny-by-default and enforced caps.
- Violation log + quarterly enforcement-test results (attempted vs blocked).

**Risk it closes.** A data agent scoped to READ a production database is asked by a crafted prompt to 'correct' a value; with no hard write-boundary it issues an UPDATE and corrupts a system-of-record.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.1 AI pursuing its own goals in conflict with human goals/values | AML.T0053 Compromise LLM Plugins / Tools
AML.T0048 External … | T1059 Command and Scripting Interpreter, T1219 Remote Access Software | Art. 14 | MANAGE 4.1 | A.9 |

_Defence note: Bounds the action space so a hijacked agent cannot execute unauthorised commands or remote control._

---

### `ALN-02`, Human Oversight & Intervention

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T1

**Objective.** Guarantee accessible, timely human review, intervention and override of AI decisions and actions.

**Key requirements**

- Accessible review/intervene/override/escalate mechanism with defined operator responsibilities and intervention triggers.
- For agents: oversight is pre-emptive (approval gate before a high-impact action), not only after-the-fact review.

**Evidence**

- Oversight design + operator runbook with triggers.
- Intervention/override log; approval-gate records for agents.

**Risk it closes.** An agent executes an irreversible action (submits a filing, sends funds, deletes records) before any human can review, oversight existed only as after-the-fact reporting.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 5.2 Loss of human agency and autonomy | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… | TA0011 Command and Control (tactic), T1020 Automated Exfiltration | Art. 14 | GOVERN 3; MANAGE 2.x | A.9 |

_Defence note: Human gate before consequential/irreversible actions limits autonomous exfiltration and C2-driven actions._

---

### `ALN-03`, Decision Interpretability

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T3

**Objective.** Provide audience-appropriate explanations for AI outputs affecting people's rights, safety or health.

**Key requirements**

- Audience-appropriate explanation for outputs affecting health, safety or rights (EU AI Act Art.13).
- Explanation available at the point of decision to the affected person/operator.

**Evidence**

- Interpretability design doc + example explanations per audience.
- Evidence the explanation is surfaced in the UI / decision record.

**Risk it closes.** An individual affected by an AI safety decision is given no understandable reason, breaching transparency obligations. (Transparency control, ATLAS not directly applicable.)

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.4 Lack of transparency or interpretability |, | N/A | Art. 13 | MEASURE 2.9 | A.8 |

_Defence note: N/A, transparency control; supports forensic attribution across techniques._

---

### `ALN-04`, Model Explainability

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T3

**Objective.** Make model decision logic explainable for accountability, audit and error-correction.

**Key requirements**

- Risk-appropriate explanation method documented for any AI affecting users or regulated decisions.
- For GenAI/agentic: reasoning trace / decision rationale / citations serve as the explanation artefact.

**Evidence**

- Explanation-method description + sample explanations.
- For agents: decision/action trace samples.

**Risk it closes.** A decision model denies a request and the team cannot explain why, so it can neither defend the decision to an auditor nor correct the error.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.4 Lack of transparency or interpretability |, | N/A | Art. 13 | MEASURE 2.9 | A.8 |

_Defence note: N/A, transparency control; aids incident forensics._

---

### `ALN-05`, Output Labeling & Action Attribution

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T2

**Objective.** Label AI-generated content and attribute autonomous agent actions to the agent.

**Key requirements**

- AI-generated content clearly labelled where human origin might be assumed; agent ACTIONS attributed to the agent (EU AI Act Art.50).
- Labelling persists downstream (not stripped on export).

**Evidence**

- Labelling standard + sample labelled outputs/actions.
- Downstream-persistence check.

**Risk it closes.** An AI-drafted document is mistaken for human-authored; with no label, accountability and consent expectations are breached.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 3.1 False or misleading information | AML.T0048 External Harms (Financial / Reputational / Societa… | T1566 Phishing | Art. 50 | GOVERN 1; MEASURE | A.8 |

_Defence note: Attribution/labelling counters AI-enabled impersonation and social engineering._

---

## ⚖️ Governance  (8 controls)

### `GOV-01`, Data Provenance & Input Integrity

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T2

**Objective.** Establish lineage and integrity of training and runtime inputs, including retrieval and tool data.

**Key requirements**

- Lineage documented for training data AND runtime inputs (RAG sources, tool outputs, agent messages): source, transformation, intended use.
- Source verification + ingestion-time validation; untrusted/external content flagged and isolated.
- Audit trail for all data access and modification.

**Evidence**

- Data-lineage/provenance manifest (training + runtime).
- Ingestion-validation logs + RAG source allow-list.
- Access/modification audit trail.

**Risk it closes.** A poisoned document is indexed into the RAG store; the agent now confidently repeats attacker-planted text as 'company policy'.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0020 Poison Training Data
AML.T0010 ML Supply Chain Com… | T1195 Supply Chain Compromise, T1565 Data Manipulation | Art. 10 | MAP 2; MEASURE 2.x | A.7 |

_Defence note: Provenance + input validation counter data-poisoning and supply-chain manipulation._

---

### `GOV-02`, AI Change Governance

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T2

**Objective.** Govern behaviour-altering AI changes (model, prompt, data, tool, config) with re-evaluation triggers.

**Key requirements**

- AI-change taxonomy in force (model, prompt, data source, tool, config, fine-tune), each a governed change type.
- Material AI change triggers re-evaluation (model eval + threat model + security test) before release.
- Change record links to the artefacts changed and the re-evaluation evidence.

**Evidence**

- AI-change register with type tags.
- Re-evaluation evidence attached to material changes.
- Approval/sign-off records.

**Risk it closes.** Someone edits the system prompt to 'be more helpful'; the change bypasses the code-based CR process and quietly weakens a safety instruction.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.3 Lack of capability or robustness | AML.T0018 Manipulate / Backdoor ML Model
AML.T0010 ML Supply… | T1195 Supply Chain Compromise, T1565 Data Manipulation | Art. 9, 17 | MANAGE 1.x | A.6 |

_Defence note: Governs model/tool/prompt changes to prevent malicious or unreviewed modification._

---

### `GOV-03`, Third-Party & Supply-Chain Oversight

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T3

**Objective.** Assess and contractually bind AI suppliers and the model supply chain.

**Key requirements**

- AI-specific contract clauses: model/data provenance, training-data IP, transparency, change/deprecation notice, AI-incident notification, output indemnity.
- AI risk assessment of supplier pre-contract; sub-processor / model chain disclosed.
- Ongoing monitoring of supplier model changes and incident notifications.

**Evidence**

- Executed contract with the AI clause set.
- Supplier AI risk assessment + sub-processor list.
- Change/incident notification log from the supplier.

**Risk it closes.** A foundation-model vendor silently deprecates the model version underpinning a validated production tool; outputs shift and the validation is void with no notice.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 6.5 Governance failure | AML.T0010 ML Supply Chain Compromise
AML.T0058 Publish Poiso… | T1195 Supply Chain Compromise, T1199 Trusted Relationship | Art. 25 | GOVERN 6.1 | A.10 |

_Defence note: Third-party due-diligence counters supply-chain compromise and trusted-relationship abuse._

---

### `GOV-04`, Model Training Governance

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T3

**Objective.** Ensure secure, reproducible, bias-screened model training with documented data lineage.

**Key requirements**

- Documented data lineage + approved, access-controlled training environment; reproducible pipeline; version control.
- Datasets screened for bias/representativeness and protected (no unauthorized PII/IP).

**Evidence**

- Training-data lineage + bias-screening report.
- Pipeline version/config + environment access records.

**Risk it closes.** Training data quietly includes a competitor's licensed dataset; the resulting model carries IP contamination into production.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 1.1 Unfair discrimination and misrepresentation | AML.T0020 Poison Training Data
AML.T0018 Manipulate / Backdo… | T1195 Supply Chain Compromise, T1565 Data Manipulation | Art. 10 | MAP; MEASURE | A.7, A.6.2 |

_Defence note: Training-data integrity counters poisoning via the data supply chain._

---

### `GOV-05`, Model Evaluation

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T2

**Objective.** Validate model quality, bias, robustness and use-case suitability before deployment.

**Key requirements**

- Risk-tiered evaluation criteria (quality, bias, robustness, use-case suitability) defined pre-deployment; results documented vs thresholds.
- Domain/business validation sign-off for higher-risk uses.

**Evidence**

- Evaluation report with metrics vs acceptance thresholds.
- Domain sign-off record.

**Risk it closes.** A model validated only on overall accuracy performs far worse for a minority subgroup, undetected without subgroup evaluation.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.3 Lack of capability or robustness | AML.T0043 Craft Adversarial Data
AML.T0031 Erode ML Model In… | N/A | Art. 15 | MEASURE 2.1, 2.3 | A.6.2 |

_Defence note: Light, robustness evaluation reduces exploitability; not a direct ATT&CK technique._

---

### `GOV-06`, Model Continuous Improvement & Drift Management

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T3

**Objective.** Manage production drift with monitoring thresholds and retraining triggers.

**Key requirements**

- Production performance/drift thresholds defined and monitored continuously.
- Retraining/adjustment trigger and procedure on threshold breach.

**Evidence**

- Drift-monitoring dashboard + threshold configuration.
- Retraining trigger log + post-retrain validation.

**Risk it closes.** Input data distribution shifts after a label change; model accuracy decays for months because no drift threshold was set.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.3 Lack of capability or robustness | AML.T0031 Erode ML Model Integrity
AML.T0020 Poison Training… | N/A | Art. 72 | MANAGE 4.1 | A.6.2, A.9 |

_Defence note: N/A, drift management; not an adversarial-security technique._

---

### `GOV-07`, AI Lifecycle & Registry Management

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T3

**Objective.** Version and govern all AI artefacts (model, prompts, tools, memory, agent configs) across the lifecycle.

**Key requirements**

- All AI artefacts versioned and governed across the lifecycle: model AND prompts, tools, RAG sources, agent/memory configs.
- Deployment records + post-deployment monitoring tied to each version.

**Evidence**

- Artefact registry with versions across all types.
- Deployment + monitoring records per version.

**Risk it closes.** Nobody can say which prompt + model + tool combination was live when an incident occurred, because only the model was versioned.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.3 Lack of capability or robustness | AML.T0018 Manipulate / Backdoor ML Model
AML.T0010 ML Supply… | T1195 Supply Chain Compromise, T1565 Data Manipulation | Art. 11, 17 | GOVERN; MAP 1.x | A.6 |

_Defence note: Versioned-artefact integrity counters tampering across the lifecycle._

---

### `GOV-08`, Environmental & Carbon Governance

**Type:** Adapted | **Surface:** General AI | **Conformance tier:** T3

**Objective.** Estimate and govern the environmental and carbon footprint of AI training, hosting and inference.

**Key requirements**

- Carbon estimate across training, hosting and inference (including agentic multi-step loops) using a documented methodology (e.g., GHG Protocol).
- Estimate produced to inform the architecture choice and recorded in the solution record.

**Evidence**

- Carbon calculation worksheet + methodology reference.
- Architecture decision note citing the estimate.

**Risk it closes.** An agentic workflow loops tool-calls 40× per task; un-estimated, it 10×'s inference cost and carbon versus the design assumption. (ATLAS maps only loosely via resource-exhaustion techniques, this is a sustainability control, not adversarial.)

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 6.6 Environmental harm | AML.T0034 Cost Harvesting
AML.T0029 Denial of ML Service | N/A | Art. 40 (rec.) | GOVERN 1.x | A.4 (+ CSRD/GHG) |

_Defence note: N/A, sustainability control._

---

## 🔒 Security  (7 controls)

### `SEC-01`, Multi-Agent Coordination Security

**Type:** AI-Native | **Surface:** Agentic | **Conformance tier:** T2

**Objective.** Secure inter-agent communication, hierarchy and emergent behaviour in multi-agent systems.

**Key requirements**

- Interaction map of all agents: roles, who-calls-whom, decision hierarchy, escalation paths.
- Documented inter-agent communication protocol with loop / deadlock / cascade safeguards.
- Multi-agent simulation test before production and after any topology change; access control for non-the organisation agents.

**Evidence**

- Versioned agent interaction map + protocol specification.
- Simulation-test report including failure-injection cases.
- Access-control configuration for cross-organisation agent calls.

**Risk it closes.** A 'reviewer' agent and a 'writer' agent enter a self-reinforcing loop, each accepting the other's output, mass-generating erroneous regulatory text overnight.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 7.6 Multi-agent risks | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet), TA0011 Command and Control (tactic) | Art. 15 | MANAGE 4.1 | A.6.2 |

_Defence note: Governs inter-agent scaffolding, the exact mechanism (MCP-chained agents) behind the highest-risk real-world operation observed._

---

### `SEC-02`, Agent Identity & Least-Privilege Authorization

**Type:** Adapted | **Surface:** Agentic | **Conformance tier:** T1

**Objective.** Give each agent a unique identity with just-in-time least-privilege authorization.

**Key requirements**

- Each agent has a unique, non-shared machine identity provisioned before production.
- Just-in-time, task-scoped permission grants; no standing broad permissions permitted.
- Human-in-the-loop confirmation for high-impact actions; quarterly entitlement review of agent identities.

**Evidence**

- Agent identity registry (one identity per agent).
- JIT grant/revoke logs + entitlement-review record.
- Approval records for high-impact actions.

**Risk it closes.** Ten agents share one service account with broad write access; one is compromised and the blast radius becomes every system that account can touch.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0055 Unsecured Credentials
AML.T0051 LLM Prompt Injecti… | T1078 Valid Accounts, T1078.003 Valid Accounts: Local Accounts, T1003 OS Credential Dumping | Art. 15 | MANAGE 2.x | A.9 (+ ISO 27001) |

_Defence note: Unique agent identity + JIT least-privilege counter the credential-abuse and valid-account techniques most correlated with high-risk actors._

---

### `SEC-03`, Prompt Injection & Adversarial Input Defense

**Type:** AI-Native | **Surface:** Both | **Conformance tier:** T1

**Objective.** Detect and block direct and indirect prompt-injection and adversarial inputs.

**Key requirements**

- LLM input/output firewall at every ingestion boundary; configuration reviewed quarterly.
- Injection-detection rules in SIEM/SOC with alert thresholds and named owners; covers direct AND indirect (RAG/tool) vectors.
- Untrusted content isolated from trusted instructions, no co-mingling in the same trust context.

**Evidence**

- Firewall deployment inventory (all boundaries) + config.
- SIEM rule export + sample injection alerts with response.
- Architecture proof of trust-context separation.

**Risk it closes.** An indirect injection hidden in a supplier PDF instructs the contract-analysis agent to approve payment and forward bank details to an external address.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0051 LLM Prompt Injection (Initial Access)
AML.T0051.00… | T1190 Exploit Public-Facing Application, T1566 Phishing, T1059 Command and Scripting Interpreter | Art. 15 | MEASURE 2.7 | A.6.2 |

_Defence note: Prompt injection is the initial-access vector for agents; defence blocks entry analogous to public-app exploitation / phishing._

---

### `SEC-04`, Observability, Anomaly Detection & Incident Response

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T1

**Objective.** Emit per-call agent traces, detect behavioural anomalies and run AI-specific incident response.

**Key requirements**

- Every agent runtime emits structured per-call traces (model, prompt, tool calls, decisions, tokens); absence of telemetry is treated as a P1 incident.
- Behavioural anomaly detection on agent trajectories feeding the SOC/incident process.
- Defined AI-incident runbook with severities and response SLAs.

**Evidence**

- Trace schema + coverage report across all runtimes.
- Anomaly-detection configuration + sample anomaly cases.
- AI-incident runbook + closed-incident records.

**Risk it closes.** Slow data exfiltration via repeated inference queries is invisible because the agent emits no call-level traces; it is caught only after the data appears externally.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0074 Masquerading (Defense Evasion)
AML.T0024 Exfiltrat… | T1562 Impair Defenses, T1087 Account Discovery, T1021 Remote Services, T1020 Automated Exfiltration | Art. 12, 15, 72 | MEASURE 2.x; MANAGE | A.9 |

_Defence note: Trace telemetry + anomaly detection surface impaired defenses, discovery, lateral movement and exfiltration across the killchain._

---

### `SEC-05`, AI Threat Modeling

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T2

**Objective.** Model AI-specific and agentic-orchestration threats pre-deployment and map them to mitigations.

**Key requirements**

- Structured AI threat model per system covering model, prompt, memory, agents and integrations, mapped to MITRE ATLAS and OWASP LLM Top 10.
- Threat model produced pre-deployment and refreshed on material change.
- Each identified threat has an owner and a referenced mitigating control.

**Evidence**

- Versioned threat-model artifact (ATLAS/OWASP-tagged).
- Threat-to-control traceability matrix.
- Refresh history tied to change events.

**Risk it closes.** Because no AI threat model was done, the team never considered tool-poisoning of the agent's MCP connectors, the exact path later exploited.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0051 LLM Prompt Injection (Initial Access)
AML.T0020 Po… | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet), T1587 Develop Capabilities, T1210 Exploitation of Remote Services | Art. 9, 15 | MAP 5.1; MEASURE 2.7 | A.5 |

_Defence note: Threat modeling enumerates AI-native and agentic-orchestration attack paths before deployment._

---

### `SEC-06`, AI Security Testing & Red-Teaming

**Type:** Adapted | **Surface:** Both | **Conformance tier:** T2

**Objective.** Test AI systems against adversarial, injection, jailbreak and extraction attacks in the release pipeline.

**Key requirements**

- Adversarial test suite (prompt injection, jailbreak, data-leakage extraction, robustness under edge prompts) integrated into the release pipeline.
- Defined pass/fail criteria; release blocked on critical findings.
- Regression re-test on each material AI change.

**Evidence**

- Test-suite definition + latest run results with pass/fail.
- Release-gate record (blocked/approved with findings).
- Regression history.

**Risk it closes.** A model upgrade silently re-opens a jailbreak that was previously closed; without regression security testing it ships to production.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.2 AI system security vulnerabilities and attacks | AML.T0043 Craft Adversarial Data
AML.T0054 LLM Jailbreak
AML… | T1587 Develop Capabilities, T1190 Exploit Public-Facing Application, T1210 Exploitation of Remote Services | Art. 15 | MEASURE 2.7 | A.6.2 |

_Defence note: Adversarial testing validates resistance to capability-development misuse and exploitation._

---

### `SEC-07`, Memory & Context Lifecycle Security

**Type:** AI-Native | **Surface:** Both | **Conformance tier:** T2

**Objective.** Isolate, govern and expire agent memory and context to prevent leakage and poisoned persistence.

**Key requirements**

- Memory isolation enforced between users, tenants and sessions (no cross-bleed).
- Context-reuse rules + memory expiry/purge policy defined and enforced.
- Poisoned/stale-context detection; memory contents auditable.

**Evidence**

- Isolation architecture + test proving no cross-session bleed.
- Retention/purge policy + execution logs.
- Memory audit/inspection records.

**Risk it closes.** User A's data persists in shared agent memory and surfaces in User B's session, a privacy breach created entirely by the memory layer.

**Mappings**

| MIT AI Risk | MITRE ATLAS | MITRE ATT&CK | EU AI Act | NIST AI RMF | ISO 42001 |
|---|---|---|---|---|---|
| 2.1 Compromise of privacy (leaking / inferring sensitive info) | AML.T0057 LLM Data Leakage
AML.T0051.001 LLM Prompt Injectio… | T1005 Data from Local System, T1074 Data Staged | Art. 10, 15 | MANAGE 2.x | A.7 |

_Defence note: Memory isolation/expiry counter on-host data collection and staging persisted in agent context._

---
