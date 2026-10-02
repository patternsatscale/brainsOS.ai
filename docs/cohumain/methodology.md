# Methodology, Sources & Glossary

## Methodology
- **Control derivation.** Each control begins from a named risk in the MIT AI Risk Repository, is given a testable objective and pointed requirements, and is paired with tight, named evidence so conformance is verifiable.
- **Control typing.** *AI-Native* = no analog in traditional IT/security; must be built new. *Adapted* = extends established IT/ML/security practice with AI-specific requirements.
- **Risk mapping.** MIT subdomains (primary = core purpose; secondary = additional coverage). Macro/societal subdomains are intentionally out of scope (policy-level, not solution-level).
- **Adversarial mapping.** MITRE ATLAS for adversarial-ML techniques; MITRE ATT&CK (via the Anthropic LLM ATT&CK Navigator) for the cyber techniques a compromised/weaponised agent would execute.
- **Regulatory mapping.** Indicative crosswalk to EU AI Act, NIST AI RMF and ISO/IEC 42001; verify against current texts at adoption.

## Sources
| Source | Detail |
|---|---|
| MIT AI Risk Repository | V4, [airisk.mit.edu](https://airisk.mit.edu/) (CC BY). 1,700+ risks, 7 domains, 24 subdomains |
| MITRE ATLAS | v5.1.0, [atlas.mitre.org](https://atlas.mitre.org/) |
| MITRE ATT&CK | [attack.mitre.org](https://attack.mitre.org/) |
| Anthropic LLM ATT&CK Navigator | [red.anthropic.com](https://red.anthropic.com/2026/attack-navigator/) (2026), ARiES scoring; agentic-orchestration finding |
| Regulatory | EU AI Act (Reg. 2024/1689); NIST AI RMF 1.0; ISO/IEC 42001:2023 |

## Glossary
- **Agentic AI**, AI that plans and acts autonomously, selecting actions, invoking tools, and pursuing goals with limited human input.
- **Agentic orchestration**, an AI autonomously chaining multiple attack/operation stages together; the behaviour most predictive of severe real-world risk, with no ATT&CK ID yet.
- **Prompt injection**, an attack delivering malicious instructions through natural-language input (direct) or retrieved/tool content (indirect).
- **Kill switch / containment**, a mechanism to immediately halt, contain and isolate an AI system on a safety or security trigger.
- **AI-native control**, a control with no analog in traditional IT or security.
- **Conformance tier**, declared adoption level (Foundational / Managed / Assured) defining which controls are required.
