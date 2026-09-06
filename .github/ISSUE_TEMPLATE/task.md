---
name: Engineering Task / Unit of Work
about: Standard engineering ticket with strict acceptance criteria and security constraints
title: "[Phase X] <Title>"
labels: ["type:task"]
assignees: []
---

## 1. Objective & Context
<!-- Describe what this unit of work accomplishes and why it is needed -->

## 2. Acceptance Criteria
<!-- Verifiable definition of done. Every checkbox must be validated -->
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## 3. Plane Separation & Security Constraints
<!-- Ensure no architectural boundaries are violated -->
- [ ] **Memory Plane**: Strictly pure OKF Markdown only. Zero binary/DB/cache files in `/memories`.
- [ ] **Inference Boundary**: Raw inference engine (`ollama`) must remain unreachable to external/agent layers. All LLM calls route through `litellm`.
- [ ] **Host Sandboxing**: No exposure of `/var/run/docker.sock` and no `--privileged` mode.

## 4. Verification Steps
<!-- Commands and automated checks the agent or developer must execute -->
```bash
# e.g., docker compose config
# e.g., ./scripts/...
```
