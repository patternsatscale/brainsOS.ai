# Project Titan Historical Ticket & Walkthrough Archive

This directory archives the historical engineering tickets, feature walkthroughs, and verification records from the initial **Project Titan** development sprints (September 2026), prior to the open-source rebrand to **brainsOS** ([brainsOS.ai](https://brainsos.ai)).

## Context & Provenance

During the Project Titan era, the appliance architecture established the foundational L1–L7 reference model, host-sandboxed Hermes agent runtimes, LiteLLM gateway proxying, memory purity enforcement (Open Knowledge Format), in-transit credential injection, and decoupled Langfuse observability on the ASUS Ascent GX10 (NVIDIA GB10) appliance and Apple Silicon development workstations.

These 49 historical records are retained in their original form to preserve full auditability, commit provenance, and technical context:

| Category | Date Range | Tickets Covered | Focus Areas |
|---|---|---|---|
| **Phase 0 & 1** | 2026-09-06 | Tickets #1–#25 | Base host config, Caddy ingress, Ollama inference, LiteLLM control plane |
| **Phase 2** | 2026-09-08 to 2026-09-12 | Tickets #67–#87 | Multi-agent fleet manifest, Hermes runtime, Signal operator gateway |
| **Phase 3** | 2026-09-13 to 2026-09-19 | Tickets #88–#141 | OKF flat-file memory engine, Titan Operator IDE (code-server), canvas tooling |
| **Phase 4** | 2026-09-21 to 2026-09-24 | Tickets #144–#164 | Tool egress inspection proxy, in-transit GitHub auth injection, internal mail server |
| **Phase 5 & Comms** | 2026-09-24 to 2026-09-25 | Tickets #165–#168 | SOGo groupware, asynchronous work queue (FIFO), operator shell integration |

---

*Note: For the current open-source architecture, governance runtime specifications, and active issue templates, refer to the root [README.md](../../README.md) and [docs/cohumain/](../cohumain/README.md).*
