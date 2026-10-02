---
name: Feature / Agent Proposal
about: Propose a new capability, agent persona, skill, or hardware telemetry adapter
title: "[Feature] <Concise Title>"
labels: ["type:feat"]
assignees: []
---

## 1. Problem Statement or Opportunity
<!-- What problem does this solve? What capability or efficiency does this unlock? -->

## 2. Proposed Solution & Architectural Plane
<!-- How should this be implemented? Which plane in the BRAINS L1–L7 architecture does this touch? -->
- [ ] **L7: Communications & Operator IDE** (Caddy, SOGo, Signal, code-server)
- [ ] **L6: Agent Core Units & Fleet** (`config/agents.yaml`, personas, sub-agents)
- [ ] **L5: Memory Plane & Tool Sandbox** (`packages/titan_memory`, OKF, workspaces)
- [ ] **L4: Routing & Security Control Plane** (LiteLLM, mitmproxy, PostgreSQL)
- [ ] **L3: Inference Plane** (Ollama, vLLM, host loopback models)
- [ ] **L2: Virtualization & Isolated Networks** (Docker Compose, bridge networks)
- [ ] **L1: Hardware, Microgrid & Sensory Plane** (Host scripts, telemetry, thermal sensors)

## 3. Physical & Governance Impact
- **Energy / Concurrency Impact**: Does this require LLM request serialization (`max_parallel_requests: 1`) or asynchronous queue handling?
- **COHUMAIN ACSG Controls Touched**: Which controls in `docs/cohumain/` are relevant? (e.g. `SAF-02` Kill Switch, `SEC-02` Least Privilege, `GOV-08` Environmental Governance).
- **Security Boundaries**: Does this respect host sandboxing and zero ambient secrets?

## 4. Alternatives Considered
<!-- Any other approaches or existing tools evaluated? -->
