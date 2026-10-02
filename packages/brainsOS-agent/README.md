# brainsOS-agent

Decoupled autonomous agent runtime SPI, dynamic profile registry, and thread context assembly for brainsOS.

## Features
- **Abstract Runtime SPI (`AgentRuntime`)**: Standardized contract for message processing and email generation.
- **Manifest Profile Parser (`AgentProfile`)**: Validates agent declarations directly from `config/agents.yaml`.
- **Pure OKF Context Assembler**: Reconstructs dialog history from `/memories/threads/{thread_id}.md` in Open Knowledge Format without raw quote re-parsing.
- **Zero Cross-Tenant Leakage**: Enforces isolated persona, memory roots, and workspace partitions per agent profile.
