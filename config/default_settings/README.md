# brainsOS: Default Settings & Manifest Templates

This directory houses the version-controlled canonical default configuration manifests and settings for **brainsOS**.

---

## Architectural Context: Defaults vs. Runtime State

brainsOS enforces a strict architectural boundary between **version-controlled default templates** in `config/` and **live runtime state** in `data/`:

| Path | Purpose | Version Controlled? | Description |
|---|---|:---:|---|
| `config/default_settings/` | **Default Manifests** | **YES** | Authoritative baseline configurations tracked in Git. |
| `config/default_runners/`  | **Default Runner Templates** | **YES** | Starter execution scripts and runner configs (Hermes, Claude SDK, OpenAI SDK). |
| `config/default_memories/` | **Default Memory Structure** | **YES** | Starter Open Knowledge Format (OKF) Markdown note templates and rules. |
| `data/settings/`           | **Live Runtime Settings** | **NO** (Gitignored) | Local manifest overrides populated on bootstrap; protected from upstream `git pull` overwrites. |
| `data/runners/`            | **Live Runner Files** | **NO** (Gitignored) | Live agent scripts and runtime runner sandboxes. |
| `data/agent_memories/`     | **Live Memory Plane** | **NO** (Gitignored) | Active OKF Markdown memories, audit logs, and thread histories. |

---

## File Manifest

### 1. `agents.yaml`
- **Purpose**: The Declarative Multi-Agent Fleet Manifest Authority (Rule 9).
- **Scope**: Declares all autonomous agent units in the fleet (`terrastella`, `marvin`, `bawtford`, `ping`, `claude`, `gpt`), their communication channels (Email, Signal, Telegram), assigned runtime substrates (`hermes`, `claude`, `openai`, `autoresponder`), and memory/workspace paths.
- **Dynamic Resolution**: `packages/brainsOS-agent` loads `agents.yaml` without requiring container rebuilds or Docker daemon restarts.

### 2. `runners.yaml`
- **Purpose**: The Cognitive Compute & Runner Fleet Manifest Authority.
- **Scope**: Declares all execution backends—whether resident Warm HTTP runner daemons (`hermes-warm`, `openai-warm`, `claude-warm`) or Ephemeral Docker Sandboxes (`openhands-sandbox`).
- **Dynamic Resolution**: `packages/brainsOS-runner` (`RunnerRegistry`) loads `runners.yaml` to dynamically dispatch cognitive turns and enforce hardware/security constraints.

---

## Seeding & Bootstrap Lifecycle

When a developer or production host provisions brainsOS via `./scripts/control/bootstrap-env.sh`:
1. Host runtime directories in `./data/` are scaffolded (`data/settings/`, `data/runners/`, `data/agent_memories/`, etc.).
2. Default configurations from `config/default_settings/` are seeded into `data/settings/` using non-destructive copy (`cp -n`):
   ```bash
   cp -n -R "${REPO_ROOT}/config/default_settings/"* "${REPO_ROOT}/data/settings/"
   ```
3. Runtime loaders (`AgentProfile.from_manifest_yaml`, `RunnerRegistry.load_from_yaml`) check for active configurations in `data/settings/` first, seamlessly falling back to `config/default_settings/`.
4. Local customizations made in `data/settings/` remain strictly private, uncommitted, and un-clobbered by git pulls.
