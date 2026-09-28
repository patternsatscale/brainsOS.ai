# Security Policy

Patterns at Scale and the brainsOS maintainers take the security and governance of autonomous agent systems seriously. As an edge agent runtime and Agentic Cybersecurity Governance (ACSG) reference implementation managing process boundaries, virtual API gateways, and emergency kill switches, robust security is central to our mission.

## Supported Versions

We provide security updates and patches for the following versions of brainsOS:

| Version | Supported | Status |
|---|---|---|
| `0.1.x` (main branch) | :white_check_mark: | Active Alpha / Development |
| `< 0.1.0` | :x: | Legacy / Project Titan Prototype |

## Reporting a Vulnerability

If you discover a security vulnerability, security boundary bypass, unauthorized container privilege escalation, or sensitive token leak within brainsOS, please **do not open a public issue**.

Instead, report the issue responsibly via one of the following methods:

1. **Private GitHub Security Advisory**: Navigate to the [Security Advisories tab](https://github.com/patternsatscale/brainsOS/security/advisories) on GitHub and click **"Report a vulnerability"**.
2. **Direct Email**: Send encrypted or plain-text details to:
   - **`security@patternsatscale.com`**

### What to Include in Your Report

To help us triage and remediate the issue rapidly, please provide:
- A description of the vulnerability, including the architectural plane (L1–L7) affected.
- Detailed step-by-step reproduction steps or a minimal proof-of-concept (PoC).
- Potential impact (e.g. host filesystem access, bypass of `emergency-stop.sh`, unauthorized LiteLLM key generation, egress proxy token extraction).
- Your proposed fix or remediation, if you have one.

### Response & Disclosure Timelines

- **Initial Acknowledgment**: Within **48 hours** of receiving your report.
- **Triage & Severity Assessment**: Within **5 business days**, with CVSS scoring and reproduction verification.
- **Fix & Patch Release**: Within **14–30 business days**, depending on complexity and upstream dependencies.
- **Public Disclosure**: Coordinated disclosure after patches are merged and release notes are staged.

## Security Architecture & Boundaries

brainsOS enforces several non-negotiable operational boundaries (consult [README.md](README.md) and [docs/cohumain/CONTROLS.md](docs/cohumain/CONTROLS.md) for architectural details):
- **Host Sandboxing (Rule 4)**: Agent containers drop all Linux capabilities (`cap_drop: [ALL]`) and must never mount the host Docker socket (`/var/run/docker.sock`).
- **Inference Boundary (Rule 2)**: Raw host inference engines (`127.0.0.1:11434`) are loopback-only; agents must route completions strictly through LiteLLM.
- **Control Plane Database Isolation (Rule 6)**: The PostgreSQL database (`titan-infra-litellm-db`) is isolated from agent networks and accessible only via LiteLLM on loopback.
- **In-Transit Egress Credential Injection (Rule 10)**: Containers must not store raw GitHub tokens or API keys on disk or in environment variables; credentials are dynamically injected in transit by the egress proxy.
- **Memory Plane Purity (Rule 1)**: Memory mounts are strictly reserved for human-auditable flat-file Markdown (Open Knowledge Format); executable code, binaries, or caches in `/memories` are treated as security violations.

---

Our security policies, boundary enforcements, and incident disclosures are formally guided by the Agentic Governance & Security Controls (AGSC v1.0.0) standard established by [COHUMAIN Labs](https://www.cohumain.ai/research) and [SafeAlign AI](https://safealignai.io/). For full control specifications and conformance mappings, see [docs/cohumain/](docs/cohumain/).
