# brainsOS Security Policy & Threat Model

Patterns at Scale and the brainsOS maintainers take the security and governance of autonomous agent systems seriously. As an edge agent runtime and Agentic Cybersecurity Governance (ACSG) reference implementation managing process boundaries, virtual API gateways, and emergency kill switches, robust security is central to our mission.

---

## 1. Threat Model

brainsOS assumes a zero-trust execution model where autonomous agents and external tool integrations are untrusted entities operating on local physical hardware:

| Threat Category | Potential Vector | Mitigation & Enforcement |
|---|---|---|
| **Prompt Injection & Hijack** | Malicious content ingested from web pages, emails, or user input commanding tool execution. | Ephemeral container sandboxing, read-only root filesystems, and strict tool capability whitelisting. |
| **Container Escape & Host Compromise** | Agent attempting Linux kernel exploits, container breakout, or host daemon takeover. | Complete capability dropping (`cap_drop: [ALL]`), `no-new-privileges:true`, non-root execution (`PUID/PGID=1000`), zero access to host Docker socket (`/var/run/docker.sock`). |
| **Credential Harvesting & Exfiltration** | Rogue code attempting to inspect environment variables, read disk secrets, or exfiltrate tokens. | **Zero ambient secrets** in containers. Outbound traffic routes via Tool Egress Gateway (`mitmproxy`); credentials are dynamically injected in transit based on client IP. |
| **Hardware Starvation & Thermal Thrashing** | Runaway inference loops exhausting unified LPDDR5x memory bandwidth or overheating bare-metal silicon. | Cgroups CPU (`cpus: 2.0`), memory (`memory: 4096M`), and PID limits (`pids: 200`); LiteLLM hardware request serialization (`max_parallel_requests: 1`). |
| **Lateral Network Movement** | Agent probing local network, databases, or neighboring agent containers. | Network segmentation (`brainsos-ingress`, `brainsos-internal`, `brainsos-litellm-net`). Database port bound strictly to host loopback (`127.0.0.1:5432`). |
| **Memory Poisoning & Binary Drops** | Agent writing persistent backdoors, SQLite databases, or compiled binaries into long-term storage. | Strict Open Knowledge Format (OKF) memory purity validation. `/memories` mount accepts only human-auditable Markdown files. |

---

## 2. Multi-Layer Security Architecture

### A. Host Sandboxing & Resource Caps
- **Linux Capability Stripping**: All agent containers enforce `cap_drop: [ALL]` with `no-new-privileges:true`. Elevated capabilities cannot be gained at runtime.
- **Read-Only Root Filesystem**: Containers run with `read_only: true`. Dynamic writes are strictly constrained to volatile memory mounts (`tmpfs: /tmp, /run`) and dedicated bind-mount workspaces.
- **Strict Process Caps**: Cgroups limits enforce `cpus: 2.0`, `memory: 4096M`, and `pids: 200` to prevent fork bombs or compute starvation.
- **Docker Socket Isolation**: The host Docker socket (`/var/run/docker.sock`) is never mounted into agent runtimes. Containers cannot manage sibling or parent containers.

### B. Tool Egress Credential Injection via Proxy
- **Zero Ambient Secrets**: Agent containers hold no raw GitHub tokens (`GH_TOKEN`, `GITHUB_TOKEN`), personal access tokens (PATs), or third-party API keys in environment variables or on disk.
- **In-Transit Injection**: Outbound traffic is proxied through the dedicated Tool Egress Gateway (`brainsos-net-egress-proxy:8082` via `HTTPS_PROXY`).
- **IP-Based Tenant Isolation**: The proxy's custom addon (`config/egress/addons/github_auth.py`) verifies caller container IP on `brainsos-internal`. Authorized tenants have authentication headers injected dynamically in transit (`Authorization: Bearer` or `Basic`); unauthorized requests are rejected (`403 Forbidden`).
- **Flow Display Redaction**: Inspection consoles (`mitmweb`) automatically redact injected tokens as `[INJECTED_CINDY_TOKEN]`, preventing credential leakage in operational logs.

### C. Inference Boundary & Hardware Serialization
- **Native Loopback Binding**: Host inference engines (`ollama` or `vLLM`) run natively on the host, bound strictly to loopback (`127.0.0.1:11434`), completely unreachable from external networks or container bridges.
- **LiteLLM Gateway**: Agents communicate exclusively with the LiteLLM control plane gateway (`http://litellm:4000/v1`). LiteLLM manages dynamic virtual keys, spend caps, and model routing.
- **Hardware Serialization**: LiteLLM enforces serialized execution (`max_parallel_requests: 1` or `2`) to protect the unified LPDDR5x memory bus on the ASUS Ascent GX10 (and Apple Silicon) from bandwidth saturation.

### D. Control Plane Database Isolation
- **Isolated Persistence**: The PostgreSQL database (`brainsos-infra-litellm-db`) stores LiteLLM virtual keys, spend tracking, and audit tables.
- **Network Demarcation**: The database resides exclusively on `brainsos-litellm-net`. It is strictly forbidden from attaching to `brainsos-ingress` or `brainsos-internal`.
- **Host Loopback**: Database ports are bound strictly to `127.0.0.1:${LITELLM_DB_PORT:-5432}` on the host for LiteLLM daemon use only.

### E. Memory Plane Purity (Open Knowledge Format)
- **Flat-File Markdown Only**: The `/memories` directory contains exclusively pure Markdown (`.md`) notes structured in Open Knowledge Format (OKF).
- **Prohibited Artifacts**: SQLite databases (`.db`), vector stores, pip caches, node modules, and binary artifacts are strictly rejected by the purity enforcer (`packages/brainsOS-memory`).

### F. Deterministic Emergency Kill-Switch
- In the event of divergent agent behavior or compromised state, execution can be halted instantly via:
  ```bash
  make emergency-stop
  # or
  ./scripts/control/emergency-stop.sh
  ```
- This deterministically terminates all agent containers, severs outbound network proxies, and invalidates active LiteLLM virtual keys without affecting host stability.

---

## 3. Supported Versions

We provide security updates and patches for the following versions of brainsOS:

| Version | Supported | Status |
|---|---|---|
| `0.1.x` (`main` / `rebrand-brainsos`) | :white_check_mark: | Active Alpha / Development |
| `< 0.1.0` | :x: | Legacy / Project Titan Prototype |

---

## 4. Reporting a Vulnerability

If you discover a security vulnerability, security boundary bypass, unauthorized container privilege escalation, or sensitive token leak within brainsOS, please **do not open a public issue**.

Instead, report the issue responsibly via one of the following methods:

1. **Private GitHub Security Advisory**: Navigate to the [Security Advisories tab](https://github.com/patternsatscale/project-titan/security/advisories) on GitHub and click **"Report a vulnerability"**.
2. **Direct Email**: Send details to:
   - **`security@patternsatscale.com`**

### What to Include in Your Report
To help us triage and remediate the issue rapidly, please provide:
- A description of the vulnerability and the architectural plane (L1–L7) affected.
- Detailed step-by-step reproduction steps or a minimal proof-of-concept (PoC).
- Potential impact (e.g. host filesystem breakout, egress proxy token extraction, bypass of emergency kill switch).
- Your proposed fix or remediation, if available.

### Response & Disclosure Timelines
- **Initial Acknowledgment**: Within **48 hours** of receiving your report.
- **Triage & Severity Assessment**: Within **5 business days**, with CVSS scoring and reproduction verification.
- **Fix & Patch Release**: Within **14–30 business days**, depending on complexity.
- **Public Disclosure**: Coordinated disclosure after patches are merged and release notes are staged.

---

Our security policies, boundary enforcements, and incident disclosures are formally guided by the Agentic Governance & Security Controls (AGSC v1.0.0) standard established by [COHUMAIN Labs](https://www.cohumain.ai/research) and [SafeAlign AI](https://safealignai.io/). For full control specifications, see [docs/cohumain/](docs/cohumain/).
