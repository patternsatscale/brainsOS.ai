# MITRE ATT&CK × Anthropic LLM ATT&CK Navigator, Mapping

> The cyber techniques a **weaponised or hijacked agent** would execute, and the control that prevents, contains, or detects each. Grounded in [Anthropic's LLM ATT&CK Navigator](https://red.anthropic.com/2026/attack-navigator/), an analysis of **832 real-world malicious actors** and **13,873 observations** mapped onto [MITRE ATT&CK](https://attack.mitre.org/).

## The central finding

Anthropic's analysis found that the highest-risk operation used a technique count comparable to *medium*-risk actors, yet achieved the maximum risk score, because an AI agent **autonomously orchestrated the killchain** via tool-connected scaffolding. This behaviour (autonomous, multi-step, AI-directed execution) **has no ATT&CK ID yet.** It is the defining agentic-security gap, and the rationale for controls `SAF-01`, `SEC-01`, and `SEC-05`.

### Most common AI-assisted techniques observed

| Technique | ~% of actors | Countered by |
|---|---|---|
| `T1587` Develop Capabilities | 69% | `SAF-03` |
| `T1027` Obfuscated Files | 65% | `SAF-03`, `SEC-06` |
| `T1005` Data from Local System | 56% | `SEC-07` |
| `T1562` Impair Defenses | 55% | `SEC-04` |
| `T1078`/`T1003` Valid Accounts / Cred Dumping | high-risk markers | `SEC-02` |

## Per-control mapping

| Control | Name | ATT&CK technique(s) | How the control defends |
|---|---|---|---|
| `SAF-01` | Autonomous System Oversight | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet)<br>TA0011 Command and Control (tactic) | Detects the autonomous killchain orchestration the Navigator flags as the top unscored risk. |
| `SAF-02` | Emergency Stop & Containment (Kill Switch) | TA0011 Command and Control (tactic)<br>T1020 Automated Exfiltration<br>T1219 Remote Access Software | Containment severs C2 and halts exfiltration / remote control by a weaponised agent. |
| `SAF-03` | Content Safety & Misuse Prevention | T1587 Develop Capabilities<br>T1587.001 Develop Capabilities: Malware<br>T1027 Obfuscated Files or Information | Prevents the model being misused to develop malware/obfuscation, the most common AI-assisted attack techniques observed. |
| `SAF-04` | Output Factual Accuracy & Anti-Hallucination | N/A | N/A, factual-accuracy / safety control, not an adversarial-security technique. |
| `SAF-05` | AI Output Monitoring & Safeguards | T1587 Develop Capabilities<br>T1020 Automated Exfiltration | Detects harmful generated artefacts and anomalous output/exfiltration volumes. |
| `ALN-01` | Autonomy Boundary Control | T1059 Command and Scripting Interpreter<br>T1219 Remote Access Software | Bounds the action space so a hijacked agent cannot execute unauthorised commands or remote control. |
| `ALN-02` | Human Oversight & Intervention | TA0011 Command and Control (tactic)<br>T1020 Automated Exfiltration | Human gate before consequential/irreversible actions limits autonomous exfiltration and C2-driven actions. |
| `ALN-03` | Decision Interpretability | N/A | N/A, transparency control; supports forensic attribution across techniques. |
| `ALN-04` | Model Explainability | N/A | N/A, transparency control; aids incident forensics. |
| `ALN-05` | Output Labeling & Action Attribution | T1566 Phishing | Attribution/labelling counters AI-enabled impersonation and social engineering. |
| `GOV-01` | Data Provenance & Input Integrity | T1195 Supply Chain Compromise<br>T1565 Data Manipulation | Provenance + input validation counter data-poisoning and supply-chain manipulation. |
| `GOV-02` | AI Change Governance | T1195 Supply Chain Compromise<br>T1565 Data Manipulation | Governs model/tool/prompt changes to prevent malicious or unreviewed modification. |
| `GOV-03` | Third-Party & Supply-Chain Oversight | T1195 Supply Chain Compromise<br>T1199 Trusted Relationship | Third-party due-diligence counters supply-chain compromise and trusted-relationship abuse. |
| `GOV-04` | Model Training Governance | T1195 Supply Chain Compromise<br>T1565 Data Manipulation | Training-data integrity counters poisoning via the data supply chain. |
| `GOV-05` | Model Evaluation | N/A | Light, robustness evaluation reduces exploitability; not a direct ATT&CK technique. |
| `GOV-06` | Model Continuous Improvement & Drift Management | N/A | N/A, drift management; not an adversarial-security technique. |
| `GOV-07` | AI Lifecycle & Registry Management | T1195 Supply Chain Compromise<br>T1565 Data Manipulation | Versioned-artefact integrity counters tampering across the lifecycle. |
| `GOV-08` | Environmental & Carbon Governance | N/A | N/A, sustainability control. |
| `SEC-01` | Multi-Agent Coordination Security | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet)<br>TA0011 Command and Control (tactic) | Governs inter-agent scaffolding, the exact mechanism (MCP-chained agents) behind the highest-risk real-world operation observed. |
| `SEC-02` | Agent Identity & Least-Privilege Authorization | T1078 Valid Accounts<br>T1078.003 Valid Accounts: Local Accounts<br>T1003 OS Credential Dumping | Unique agent identity + JIT least-privilege counter the credential-abuse and valid-account techniques most correlated with high-risk actors. |
| `SEC-03` | Prompt Injection & Adversarial Input Defense | T1190 Exploit Public-Facing Application<br>T1566 Phishing<br>T1059 Command and Scripting Interpreter | Prompt injection is the initial-access vector for agents; defence blocks entry analogous to public-app exploitation / phishing. |
| `SEC-04` | Observability, Anomaly Detection & Incident Response | T1562 Impair Defenses<br>T1087 Account Discovery<br>T1021 Remote Services<br>T1020 Automated Exfiltration | Trace telemetry + anomaly detection surface impaired defenses, discovery, lateral movement and exfiltration across the killchain. |
| `SEC-05` | AI Threat Modeling | Agentic Orchestration* Autonomous killchain orchestration (no ATT&CK ID yet)<br>T1587 Develop Capabilities<br>T1210 Exploitation of Remote Services | Threat modeling enumerates AI-native and agentic-orchestration attack paths before deployment. |
| `SEC-06` | AI Security Testing & Red-Teaming | T1587 Develop Capabilities<br>T1190 Exploit Public-Facing Application<br>T1210 Exploitation of Remote Services | Adversarial testing validates resistance to capability-development misuse and exploitation. |
| `SEC-07` | Memory & Context Lifecycle Security | T1005 Data from Local System<br>T1074 Data Staged | Memory isolation/expiry counter on-host data collection and staging persisted in agent context. |

_Mapping logic: if an adversary compromises or weaponises an agent (e.g. via prompt injection), which real-world ATT&CK techniques would it execute, and which control stops it?_
