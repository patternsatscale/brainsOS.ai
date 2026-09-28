# brainsOS-mcp: Dynamic Agent Capabilities MCP Server

`brainsOS-mcp` is a standalone, decoupled [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server providing universal capability exposure for **brainsOS** agent fleets.

---

## 1. Architectural Philosophy

### A. Zero Direct Tool Injection (Protecting the Inference Budget)
Traditional agent runtimes inject large suites of tool definitions directly into the agent's system prompt. On edge appliances and unified memory hardware (such as the ASUS Ascent GX10 GB10 or Apple Silicon), injecting thousands of tokens of tool JSON schemas leads to:
1. **Severe Prompt Bloat**: Consumes substantial context window budget.
2. **KV Cache Memory Exhaustion**: Spikes VRAM consumption and memory bandwidth latency.
3. **Tool Selection Hallucinations**: Confuses the model with redundant or out-of-context parameters.

`brainsOS-mcp` encapsulates all brainsOS capabilities behind a standard MCP server boundary. The agent interacts with capabilities on-demand via standard JSON-RPC over `stdio`, keeping the active prompt lean and disciplined.

### B. Dynamic Capability Discovery
Rather than hardcoding static wrappers, `brainsOS-mcp` dynamically discovers and registers capability modules across installed `brainsOS-*` packages:
- **`brainsOS-memory`**: Open Knowledge Format (OKF) Markdown note reading, atomic persistence, note listing, and active rule synthesis.
- **`brainsOS-queue`**: Asynchronous FIFO background task queuing, status checking, and task retrieval.
- **`brainsOS-mail`**: RFC-compliant message drafting, IMAP mailbox searching, and email reading.
- **`brainsOS-telemetry`**: Synthetic energy consumption accounting (millijoules $mJ$) and telemetry event emission.

---

## 2. Installation & Quickstart

```bash
# Install in editable mode
pip install -e packages/brainsOS-mcp

# Launch stdio MCP server
brainsos-mcp
# or
python -m brainsos_mcp.server
```

### MCP Client Configuration

To integrate with Hermes Agent, Claude Code, Cursor, or OpenHands:
```json
{
  "mcpServers": {
    "brainsos": {
      "command": "python",
      "args": ["-m", "brainsos_mcp.server"]
    }
  }
}
```

---

## 3. Tool Surface

All tools expose lean, strictly typed JSON schemas (< 800 tokens total):

| Domain | Tool Name | Description |
|---|---|---|
| **Memory** | `read_memory` | Read an OKF Markdown note from `/memories`. |
| **Memory** | `write_memory` | Write or update an OKF note with purity enforcement. |
| **Memory** | `list_memory_notes` | List existing OKF notes across categories. |
| **Memory** | `synthesize_active_rules` | Synthesize active operational rules for prompt context. |
| **Queue** | `enqueue_task` | Submit a background task to the asynchronous FIFO queue. |
| **Queue** | `get_task_status` | Retrieve status and execution results for a queued task. |
| **Queue** | `list_queue_tasks` | List recent tasks in the work queue. |
| **Mail** | `send_email` | Compose and dispatch an RFC-compliant email message. |
| **Mail** | `search_emails` | Search mailbox messages via IMAP query. |
| **Mail** | `read_email` | Fetch a single email message by Message-ID or sequence number. |
| **Telemetry** | `get_energy_metrics` | Retrieve calculated energy expenditure ($mJ$) and thermals. |
| **Telemetry** | `emit_telemetry_event` | Dispatch an event through the decoupled TelemetryBus. |
