---
id: 06-appliance-cheat-sheet
from_name: brainsOS Appliance
from_user: system
reply_to_user: bawtford
subject: 🚀 Welcome to Your Sovereign AI Operating System ({domain})
preheader: Complete 7-Layer Architecture Directory, Keyboard Shortcuts (Alt+1..Alt+8), and Host Console Guide.
badge: OPERATOR CHEAT SHEET // 7-LAYER ARCHITECTURE
accent: #38bdf8
footer: brainsOS Sovereign Appliance ({domain}) • System Operator Quick Reference
age_minutes: 18
---

# 🚀 Welcome to Your Sovereign AI Operating System ({domain})

Hello **{user}**, and **Welcome to Your Sovereign AI Operating System**!

Your **{unit_name}** appliance is online at [{base_url}/]({base_url}/) with Single Sign-On active across all 7 architecture layers plus the System OS control center. Bookmark this cheat sheet for instant navigation:

## 7-Layer Architecture & Operator Shortcuts

| Shortcut | Architecture Layer / Subsystem | Direct URL | What You Can Do There |
| :--- | :--- | :--- | :--- |
| `Alt+1` | **1. Secure Communications (Webmail)** | [{base_url}/mail/]({base_url}/mail/) | Email **Bawtford** (`bawtford@{local_domain}`) & audit shared *Agent Fleet* mailboxes. |
| `Alt+2` | **2. Identity Management (Authentik)** | [{base_url}/auth/]({base_url}/auth/if/admin/#/events/log) | Govern SSO users, passkeys/MFA, tenant groups & security audit logs. |
| `Alt+3` | **3. Routing & Guardrails (LiteLLM)** | [{base_url}/proxy/ui/usage]({base_url}/proxy/ui/usage) | Manage model routing, virtual keys, budgets & serialized concurrency. |
| `Alt+4` | **4. Telemetry Data (Langfuse)** | [{base_url}/langfuse/]({base_url}/langfuse/) | Explore OpenTelemetry traces, prompt/completion tokens & latencies. |
| `Alt+5` | **5. Network Firewalls (Egress Proxy)** | [{base_url}/efw/]({base_url}/efw/) | Inspect outbound tool traffic & in-transit credential injection (`[INJECTED_CINDY_TOKEN]`). |
| `Alt+6` | **6. Readable Memory (Code Console)** | [{base_url}/editor/]({base_url}/editor/) | Inspect & edit `/memories` Markdown, `SOUL.md` & `agents.yaml` in VS Code. |
| `Alt+7` | **7. Source Control (Git Server)** | [{base_url}/git/]({base_url}/git/) | Browse local Gitea repositories, commit history & roll back agent state. |
| `Alt+8` | **8. System Manager & Host Console** | [{base_url}/system]({base_url}/system) | System Manager, TLS & domain config, updates & XTerm Host Console. |

> [!TIP] System Manager & XTerm Host Console (`/system`)
> Press `Ctrl+K` / `⌘K` (or click the top-left **☰** button) from anywhere in the portal to open the full 7-layer architecture drawer, or jump to [System (`/system`)]({base_url}/system) to launch the interactive host terminal.

## Quick Operator Commands

- **Subsystems Drawer:** Press `Ctrl+K` or `⌘K` anywhere in the portal to switch planes.
- **XTerm Host Console:** Open [System (`/system`)]({base_url}/system) to run `./scripts/control/show-urls.sh`, inspect `docker compose ps`, or tail live agent runner logs.
- **Domain & TLS Management:** Updating your appliance hostname or TLS mode automatically re-syncs SSO redirect URIs and refreshes these onboarding emails for your active domain.
