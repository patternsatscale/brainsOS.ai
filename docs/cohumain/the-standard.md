# The Standard

**Agentic Governance & Security Controls** is an open, vendor-neutral control standard for governing *and* securing agentic and generative AI systems. It is the catalog of **what** to control and **why**, unifying the governance spine (accountability, oversight, lifecycle) with the security spine (the adversarial and runtime defence of autonomous systems).

![One-page overview](assets/COHUMAIN_AGSC_v1.png)

## The core argument

In conventional IT, governance and security are different disciplines run by different teams. For an autonomous agent they collapse into a single problem: the autonomy that creates the **governance** question, *what may the agent decide and do?*, is the same autonomy that creates the **security** question, *what can a compromised agent be made to do?* A standard that answers only one answers neither.

## What ships with the standard

| Artifact | Contents |
|----------|----------|
| `controls/CONTROLS.md` | The full human-readable catalog, by pillar |
| `controls/controls.json` | Machine-readable catalog, full detail |
| `controls/controls.csv` | Machine-readable catalog, flat |
| `frameworks/mit-ai-risk.md` | Each control traced to the MIT AI Risk Repository |
| `frameworks/mitre-atlas.md` | Adversarial-ML technique per control |
| `frameworks/mitre-attack.md` | Cyber techniques a weaponised agent would run |
| `frameworks/regulatory-crosswalk.md` | EU AI Act, NIST AI RMF, ISO 42001 per control |

## Design principles

1. **Risk-first.** Every control begins from a named risk in the MIT AI Risk Repository.
2. **Testable.** Each control has a pointed objective and tight, named evidence, conformance is verifiable, not assertional.
3. **Unified.** Governance and security controls live in one catalog, one schema, one conformance model.
4. **Mapped.** Adversarial (ATLAS, ATT&CK) and regulatory (EU/NIST/ISO) mappings ship with each control.
5. **Scoped, not exhaustive.** Macro/societal risks are explicitly out of scope, policy-level, not solution-level.
6. **Open.** CC BY 4.0, vendor-neutral, community-governed.

## Contact

For further details and collaboration, contact [info@cohumain.ai](mailto:info@cohumain.ai).
