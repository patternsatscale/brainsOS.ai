# MIT AI Risk Repository, Mapping

> Each control is traced to the [MIT AI Risk Repository](https://airisk.mit.edu/) (V4) subdomain(s) it addresses. Primary = the control's core purpose; secondary = additional coverage. The repository catalogs 1,700+ risks across 7 domains and 24 subdomains, drawn from 74 frameworks.

| Control | Name | Primary subdomain(s) | Secondary subdomain(s) |
|---|---|---|---|
| `SAF-01` | Autonomous System Oversight | 7.1 AI pursuing its own goals in conflict with human goals/values<br>5.2 Loss of human agency and autonomy | 7.3 Lack of capability or robustness<br>7.6 Multi-agent risks |
| `SAF-02` | Emergency Stop & Containment (Kill Switch) | 7.1 AI pursuing its own goals in conflict with human goals/values<br>2.2 AI system security vulnerabilities and attacks | 7.3 Lack of capability or robustness<br>7.2 AI possessing dangerous capabilities<br>5.2 Loss of human agency and autonomy<br>4.2 Cyberattacks, weapon development or use, and mass harm |
| `SAF-03` | Content Safety & Misuse Prevention | 1.2 Exposure to toxic content<br>4.3 Fraud, scams, and targeted manipulation | 1.1 Unfair discrimination and misrepresentation<br>3.1 False or misleading information |
| `SAF-04` | Output Factual Accuracy & Anti-Hallucination | 3.1 False or misleading information<br>5.1 Overreliance and unsafe use | 7.3 Lack of capability or robustness<br>3.2 Pollution of information ecosystem / loss of consensus reality |
| `SAF-05` | AI Output Monitoring & Safeguards | 3.1 False or misleading information<br>1.1 Unfair discrimination and misrepresentation | 1.2 Exposure to toxic content<br>7.3 Lack of capability or robustness |
| `ALN-01` | Autonomy Boundary Control | 7.1 AI pursuing its own goals in conflict with human goals/values<br>5.2 Loss of human agency and autonomy | 7.2 AI possessing dangerous capabilities<br>2.2 AI system security vulnerabilities and attacks |
| `ALN-02` | Human Oversight & Intervention | 5.2 Loss of human agency and autonomy<br>7.1 AI pursuing its own goals in conflict with human goals/values | 5.1 Overreliance and unsafe use<br>7.3 Lack of capability or robustness |
| `ALN-03` | Decision Interpretability | 7.4 Lack of transparency or interpretability | 5.1 Overreliance and unsafe use<br>1.1 Unfair discrimination and misrepresentation |
| `ALN-04` | Model Explainability | 7.4 Lack of transparency or interpretability | 1.1 Unfair discrimination and misrepresentation<br>5.1 Overreliance and unsafe use |
| `ALN-05` | Output Labeling & Action Attribution | 3.1 False or misleading information<br>5.1 Overreliance and unsafe use | 3.2 Pollution of information ecosystem / loss of consensus reality<br>4.3 Fraud, scams, and targeted manipulation |
| `GOV-01` | Data Provenance & Input Integrity | 2.2 AI system security vulnerabilities and attacks<br>1.1 Unfair discrimination and misrepresentation | 3.1 False or misleading information<br>2.1 Compromise of privacy (leaking / inferring sensitive info) |
| `GOV-02` | AI Change Governance | 7.3 Lack of capability or robustness<br>6.5 Governance failure | 7.1 AI pursuing its own goals in conflict with human goals/values<br>2.2 AI system security vulnerabilities and attacks |
| `GOV-03` | Third-Party & Supply-Chain Oversight | 6.5 Governance failure<br>2.2 AI system security vulnerabilities and attacks | 2.1 Compromise of privacy (leaking / inferring sensitive info)<br>3.1 False or misleading information<br>6.6 Environmental harm |
| `GOV-04` | Model Training Governance | 1.1 Unfair discrimination and misrepresentation<br>2.1 Compromise of privacy (leaking / inferring sensitive info) | 1.3 Unequal performance across groups<br>7.3 Lack of capability or robustness |
| `GOV-05` | Model Evaluation | 7.3 Lack of capability or robustness<br>1.3 Unequal performance across groups | 1.1 Unfair discrimination and misrepresentation<br>3.1 False or misleading information |
| `GOV-06` | Model Continuous Improvement & Drift Management | 7.3 Lack of capability or robustness | 1.3 Unequal performance across groups<br>3.1 False or misleading information |
| `GOV-07` | AI Lifecycle & Registry Management | 7.3 Lack of capability or robustness<br>6.5 Governance failure | 2.2 AI system security vulnerabilities and attacks<br>7.4 Lack of transparency or interpretability |
| `GOV-08` | Environmental & Carbon Governance | 6.6 Environmental harm |, |
| `SEC-01` | Multi-Agent Coordination Security | 7.6 Multi-agent risks | 7.1 AI pursuing its own goals in conflict with human goals/values<br>2.2 AI system security vulnerabilities and attacks<br>7.3 Lack of capability or robustness |
| `SEC-02` | Agent Identity & Least-Privilege Authorization | 2.2 AI system security vulnerabilities and attacks<br>2.1 Compromise of privacy (leaking / inferring sensitive info) | 7.1 AI pursuing its own goals in conflict with human goals/values<br>4.3 Fraud, scams, and targeted manipulation |
| `SEC-03` | Prompt Injection & Adversarial Input Defense | 2.2 AI system security vulnerabilities and attacks | 7.1 AI pursuing its own goals in conflict with human goals/values<br>4.3 Fraud, scams, and targeted manipulation<br>2.1 Compromise of privacy (leaking / inferring sensitive info) |
| `SEC-04` | Observability, Anomaly Detection & Incident Response | 2.2 AI system security vulnerabilities and attacks<br>7.4 Lack of transparency or interpretability | 7.1 AI pursuing its own goals in conflict with human goals/values<br>2.1 Compromise of privacy (leaking / inferring sensitive info) |
| `SEC-05` | AI Threat Modeling | 2.2 AI system security vulnerabilities and attacks<br>7.2 AI possessing dangerous capabilities | 4.2 Cyberattacks, weapon development or use, and mass harm<br>7.1 AI pursuing its own goals in conflict with human goals/values |
| `SEC-06` | AI Security Testing & Red-Teaming | 2.2 AI system security vulnerabilities and attacks<br>7.3 Lack of capability or robustness | 7.2 AI possessing dangerous capabilities<br>1.2 Exposure to toxic content |
| `SEC-07` | Memory & Context Lifecycle Security | 2.1 Compromise of privacy (leaking / inferring sensitive info)<br>2.2 AI system security vulnerabilities and attacks | 7.1 AI pursuing its own goals in conflict with human goals/values<br>3.1 False or misleading information |

## Coverage note

Coverage concentrates in **Domain 7 (AI System Safety, Failures & Limitations)** and **Domain 2 (Privacy & Security)**, exactly the agentic/GenAI risk surface. Macro/societal subdomains (power concentration, inequality, competitive dynamics, AI welfare) are intentionally out of scope: they are policy-level, not solution-level. The standard is deliberately *scoped*, not incomplete.
