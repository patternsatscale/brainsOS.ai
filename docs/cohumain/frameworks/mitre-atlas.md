# MITRE ATLAS, Mapping

> Adversarial-ML techniques ([MITRE ATLAS](https://atlas.mitre.org/) v5.1.0) addressed by each control. ATLAS is the AI-specific counterpart to ATT&CK, cataloguing tactics and techniques adversaries use against machine-learning systems.

| Control | Name | Pillar | ATLAS technique(s) |
|---|---|---|---|
| `SAF-01` | Autonomous System Oversight | Safety | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… |
| `SAF-02` | Emergency Stop & Containment (Kill Switch) | Safety | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… |
| `SAF-03` | Content Safety & Misuse Prevention | Safety | AML.T0054 LLM Jailbreak
AML.T0048 External Harms (Financial … |
| `SAF-04` | Output Factual Accuracy & Anti-Hallucination | Safety | AML.T0048 External Harms (Financial / Reputational / Societa… |
| `SAF-05` | AI Output Monitoring & Safeguards | Safety | AML.T0048 External Harms (Financial / Reputational / Societa… |
| `ALN-01` | Autonomy Boundary Control | Alignment | AML.T0053 Compromise LLM Plugins / Tools
AML.T0048 External … |
| `ALN-02` | Human Oversight & Intervention | Alignment | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… |
| `ALN-05` | Output Labeling & Action Attribution | Alignment | AML.T0048 External Harms (Financial / Reputational / Societa… |
| `GOV-01` | Data Provenance & Input Integrity | Governance | AML.T0020 Poison Training Data
AML.T0010 ML Supply Chain Com… |
| `GOV-02` | AI Change Governance | Governance | AML.T0018 Manipulate / Backdoor ML Model
AML.T0010 ML Supply… |
| `GOV-03` | Third-Party & Supply-Chain Oversight | Governance | AML.T0010 ML Supply Chain Compromise
AML.T0058 Publish Poiso… |
| `GOV-04` | Model Training Governance | Governance | AML.T0020 Poison Training Data
AML.T0018 Manipulate / Backdo… |
| `GOV-05` | Model Evaluation | Governance | AML.T0043 Craft Adversarial Data
AML.T0031 Erode ML Model In… |
| `GOV-06` | Model Continuous Improvement & Drift Management | Governance | AML.T0031 Erode ML Model Integrity
AML.T0020 Poison Training… |
| `GOV-07` | AI Lifecycle & Registry Management | Governance | AML.T0018 Manipulate / Backdoor ML Model
AML.T0010 ML Supply… |
| `GOV-08` | Environmental & Carbon Governance | Governance | AML.T0034 Cost Harvesting
AML.T0029 Denial of ML Service |
| `SEC-01` | Multi-Agent Coordination Security | Security | AML.TA0015 Command and Control (tactic, new in v5.1.0)
AML.T… |
| `SEC-02` | Agent Identity & Least-Privilege Authorization | Security | AML.T0055 Unsecured Credentials
AML.T0051 LLM Prompt Injecti… |
| `SEC-03` | Prompt Injection & Adversarial Input Defense | Security | AML.T0051 LLM Prompt Injection (Initial Access)
AML.T0051.00… |
| `SEC-04` | Observability, Anomaly Detection & Incident Response | Security | AML.T0074 Masquerading (Defense Evasion)
AML.T0024 Exfiltrat… |
| `SEC-05` | AI Threat Modeling | Security | AML.T0051 LLM Prompt Injection (Initial Access)
AML.T0020 Po… |
| `SEC-06` | AI Security Testing & Red-Teaming | Security | AML.T0043 Craft Adversarial Data
AML.T0054 LLM Jailbreak
AML… |
| `SEC-07` | Memory & Context Lifecycle Security | Security | AML.T0057 LLM Data Leakage
AML.T0051.001 LLM Prompt Injectio… |

Controls not listed (e.g. anti-hallucination, interpretability, carbon) are governance/transparency controls without a direct adversarial-ML technique.
