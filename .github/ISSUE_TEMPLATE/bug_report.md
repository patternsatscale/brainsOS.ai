---
name: Bug Report / Defect
about: Report a defect, capability crash, or security boundary failure in brainsOS
title: "[Bug] <Summary>"
labels: ["type:bug"]
assignees: []
---

## 1. Observed Behavior
<!-- What happened? Include error logs, docker compose logs, or unexpected agent action -->

## 2. Expected Behavior
<!-- What should have happened according to the brainsOS architecture and specs? -->

## 3. Environment & Hardware Context
- **Host OS**: macOS (Apple Silicon) / Linux (Ubuntu 24.04 / DGX OS on ASUS Ascent GX10)
- **Container Engine**: Docker Compose v2 (`docker compose version`)
- **Inference Runtime**: Ollama / vLLM (version, model name)

## 4. Affected Architectural Planes (BRAINS L1–L7)
- [ ] **L7: Communications, UX & Operator IDE** (Caddy, SOGo, Signal, code-server)
- [ ] **L6: Agent Core Units & Fleet** (`config/agents.yaml`, personas, sub-agents)
- [ ] **L5: Memory Plane & Tool Sandbox** (`packages/brainsOS-memory`, OKF, workspaces)
- [ ] **L4: Routing & Security Control Plane** (LiteLLM, mitmproxy, PostgreSQL)
- [ ] **L3: Inference Plane** (Host Ollama, loopback models)
- [ ] **L2: Virtualization & Isolated Bridge Networks** (Docker Compose, networks)
- [ ] **L1: Hardware, Microgrid & Sensory Plane** (Host scripts, telemetry, thermal sensors)

## 5. Steps to Reproduce
```bash
# Provide exact reproduction commands via repository scripts
```

## 6. Proposed Fix / Acceptance Criteria
- [ ] Root cause identified and codified in scripts/config
- [ ] Verification tests passing
