# brainsOS Fleet Settings & Manifest Authority

Welcome to the **brainsOS** fleet configuration authority. This directory contains the declarative manifests, compute runner topologies, and modular prompt injection templates that govern the autonomous agent fleet.

---

## Architectural Context: Defaults vs. Live State

brainsOS enforces a strict boundary between **version-controlled default templates** in the platform core repository and **live runtime state** in the private data repository:

| Path | Purpose | Git Tracked? | Description |
|---|---|:---:|---|
| `config/default_settings/` | **Default Manifest Templates** | **YES** (Core Repo) | Canonical baseline configurations tracked in Git. |
| `data/settings/` | **Live Fleet Settings** | **YES** (Data Repo) | Appliance-specific configurations, customized manifests, and live prompt overrides. |

When a new appliance or developer workstation is initialized via `./scripts/control/bootstrap-env.sh`, files in `config/default_settings/` are seeded non-destructively into `data/settings/`.

---

## Directory Overview

```text
settings/
├── README.md               # This operator handbook
├── agents.yaml             # Declarative fleet manifest (agents, emails, models, runtimes)
├── runners.yaml            # Compute runners manifest (warm HTTP daemons, sandboxes)
└── prompts/                # Modular prompt injection hierarchy
    ├── global/             # Injected into EVERY agent turn across the entire fleet
    │   └── 00_manifesto.md # Patterns at Scale Manifesto (resource awareness & discipline)
    ├── channels/           # Injected based on the active communication channel
    │   └── email.md        # Email instructions (HTML format, pacing, curiosity, memory)
    └── envelopes/          # Message formatting templates for incoming turns
        └── email.md        # RFC header envelope wrapping incoming email turns
```

---

## 1. Fleet Manifest: `agents.yaml`

The declarative single source of truth for all autonomous agent units in the fleet.

```yaml
agents:
  - id: "terrastella"
    name: "Terrastella - Primary Operations Agent"
    enabled: true

    # Communications (Universal Message Bus)
    email:
      enabled: true
      address: "terrastella@brainsos.local"

    # L2: Agent Core Runtime
    runtime: "hermes"
    soul: "terrastella"
    persona: "agents/terrastella/SOUL.md"
    models:
      default: "brainsos-core"

    # L3: Memory Plane & Tool Sandbox
    memory:
      path: "agents/terrastella/memories"
    workspace:
      path: "agents/terrastella/workspace"
```

- **Dynamic Resolution**: Changes to `agents.yaml` are loaded on-the-fly by `packages/brainsOS-agent` without requiring container rebuilds or Docker daemon restarts.

---

## 2. Runner Manifest: `runners.yaml`

Declares all cognitive compute backends—whether resident Warm HTTP runner daemons (`hermes-warm`, `openai-warm`, `claude-warm`) or Ephemeral Docker Sandboxes (`openhands-sandbox`).

```yaml
runners:
  - id: "hermes-warm"
    name: "Nous Hermes Warm Runner"
    type: "warm_http"
    endpoint: "http://runner-hermes:8642"
    timeout_sec: 120
    concurrency_limit: 4
```

---

## 3. Modular Prompt Hierarchy (`prompts/`)

brainsOS assembles the cognitive context for every agent turn using a 5-layer hierarchy:

```text
[1. Global Directives]     settings/prompts/global/*.md (e.g. 00_manifesto.md)
        ↓
[2. Agent Persona]        agents/<id>/SOUL.md
        ↓
[3. Working Memory Rules] agents/<id>/memories/rules/*.md
        ↓
[4. Channel Directives]   settings/prompts/channels/<channel>.md (e.g. email.md)
        ↓
[5. Inbound Envelope]     settings/prompts/envelopes/<channel>.md (wrapping user turn)
```

### Global Prompts (`prompts/global/`)
- Any `.md` file in `prompts/global/` is automatically read in alphabetical/numerical order and injected into the system prompt of **every** agent turn across all channels and tools.
- `00_manifesto.md`: Injects the *Patterns at Scale Manifesto*, instilling environmental awareness, computational discipline, and energy stewardship into the model's baseline worldview.

### Channel Directives (`prompts/channels/`)
- Injected into the system prompt based on the communication channel handling the interaction.
- `email.md`: Instructs the model that it is communicating via asynchronous email, enforces clean semantic HTML formatting without markdown fences, and encourages curiosity and long-term memory formation.
- Future channels (e.g. `signal.md`, `telegram.md`, `portal.md`) can be added simply by dropping a new `.md` file into this directory.

### Inbound Envelopes (`prompts/envelopes/`)
- Defines how incoming user turns are wrapped with channel metadata before being sent to the model.
- `email.md`: Wraps the email body with RFC headers (`From`, `To`, `Subject`, `Date`, `Thread-ID`) so the model explicitly understands who sent the message, its subject line, and timing context.

---

## 4. Precedence & Customization Cascade

When resolving prompts, `brainsos_agent` applies a cascading search:

1. **Per-Agent Override**: `data/agents/<agent_id>/prompts/<category>/<file>.md` (if a specific agent requires customized channel rules).
2. **Live Fleet Setting**: `data/settings/prompts/<category>/<file>.md` (appliance-wide active configuration).
3. **Core Baseline Default**: `config/default_settings/prompts/<category>/<file>.md` (shipped default fallback).
