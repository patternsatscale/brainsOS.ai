> 🤖 **brainsOS Contributor Pull Request**
> **Website**: [brainsOS.ai](https://brainsos.ai) • **Community**: [Patterns at Scale](https://patternsatscale.com)

### Linked Issue
Closes #<!-- issue number here, e.g. Closes #123 -->

---

### Summary of Changes
<!-- A clear, concise summary of what this pull request introduces, fixes, or refactors. -->
- 

---

### Architectural Planes Affected (BRAINS L1–L7)
- [ ] **L7: Communications, UX & Operator IDE** (Caddy, SOGo, Signal, code-server)
- [ ] **L6: Agent Core Units & Fleet** (`config/agents.yaml`, personas, sub-agents)
- [ ] **L5: Memory Plane & Tool Sandbox** (`packages/titan_memory`, OKF markdown, workspaces)
- [ ] **L4: Routing, Security & Control Plane** (LiteLLM, mitmproxy egress, PostgreSQL DB)
- [ ] **L3: Inference Plane** (Ollama, vLLM, host loopback models)
- [ ] **L2: Virtualization & Isolated Bridge Networks** (Docker Compose, bridge networks)
- [ ] **L1: Hardware, Microgrid & Sensory Plane** (Host scripts, telemetry, thermal sensors)

---

### Verification & Test Evidence
<!-- Provide terminal output and exact commands executed via repository scripts to prove functionality. -->

```bash
# Example verification script output:
find scripts -type f -name "*.sh" -exec bash -n {} +
docker compose config -q
./scripts/control/sync-agents.sh --check
```

---

### Contributor Checklist
- [ ] My code adheres to the [brainsOS Operating Discipline](AGENTS.md) and [Contributing Guidelines](CONTRIBUTING.md).
- [ ] I have used repository scripts (`./scripts/*`) for setup and validation rather than ad-hoc container commands.
- [ ] I have verified **Memory Plane Purity (Rule 1)**: Zero SQLite databases, binary indices, or caches committed to `/memories`.
- [ ] I have verified **Secret Protection (Rule 5)**: Zero API keys, passwords, or live `.env` files are tracked in Git.
- [ ] I have verified **Control Plane Database Isolation (Rule 6)**: The agent plane has zero routes or credentials to LiteLLM's PostgreSQL database.
- [ ] All shell scripts have passed syntax validation (`bash -n`).
- [ ] Any architectural changes, new services, or port additions are documented in [README.md](README.md).
