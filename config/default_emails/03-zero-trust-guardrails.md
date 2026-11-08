---
id: 03-zero-trust-guardrails
from_name: Perimeter Gatekeeper
from_user: security
reply_to_user: bawtford
subject: 🛡️ Nobody leaves the box without a hall pass (Identity, Guardrails & Firewalls)
preheader: How Authentik Identity, LiteLLM Guardrails, Egress Firewalls, and Langfuse Telemetry protect your fleet.
badge: ZERO-TRUST SECURITY // OBSERVABILITY TOUR
accent: #10b981
footer: Perimeter Gatekeeper (security@{local_domain}) • Zero Ambient Secrets enforced
age_minutes: 8
---

# 🛡️ Nobody leaves the box without a hall pass

Halt! Who goes there? Oh—it's **{user}**. Carry on!

I am the **Perimeter Gatekeeper** (`security@{local_domain}`). Most AI setups hand agents a pile of raw API keys, wide-open internet access, and a polite wish that they "please behave." In **brainsOS**, nobody—not even **Bawtford** managing **Cindy Pawford**'s digital empire—leaves the box without a hall pass.

## Four Layers of Zero-Trust Defense

1. **Identity Management — [Authentik]({base_url}/auth/if/admin/#/events/log) (`Alt+2`):** The front-door bouncer. Every operator dashboard is protected by zero-trust Single Sign-On (OAuth2/OIDC + forward-auth) with FIDO2/WebAuthn passkey support and full login event auditing.
2. **Routing & Guardrails — [LiteLLM]({base_url}/proxy/ui/usage) (`Alt+3`):** The air-traffic controller. Agent containers can never call host inference engines directly (Rule 2). Every completion routes through LiteLLM using per-tenant virtual keys, budgets, and hardware concurrency serialization (`max_parallel_requests: 1`) so unified memory bandwidth never thrashes (Rule 3).
3. **Telemetry Data — [Langfuse]({base_url}/langfuse/) (`Alt+4`):** The flight data recorder. Every prompt, model call, tool invocation, token count, and latency span is captured via OpenTelemetry so you can audit every decision your agents make.
4. **Network Firewalls — [Egress Proxy]({base_url}/efw/) (`Alt+5`):** The hall-pass inspector. Agent containers hold **zero ambient GitHub tokens or third-party secrets** (Rule 10). All outbound HTTPS traffic flows through our `mitmproxy` Egress Gateway, which verifies container IP identity, injects credentials in transit only for approved hosts, and masks tokens as `[INJECTED_CINDY_TOKEN]` in the live traffic UI.

| Defense Plane | Portal Path | Shortcut | Core Guarantee |
| :--- | :--- | :--- | :--- |
| **Authentik SSO** | `/auth/` | `Alt+2` | Unified OAuth2/OIDC identity & MFA across all subsystems. |
| **LiteLLM Gateway** | `/proxy/ui/usage` | `Alt+3` | Per-agent virtual keys, budgets & serialized inference. |
| **Langfuse Traces** | `/langfuse/` | `Alt+4` | Full OpenTelemetry audit trail of prompts, tools & tokens. |
| **Egress Firewall** | `/efw/` | `Alt+5` | Zero ambient secrets; in-transit token injection & inspection. |

> [!TIP] Watch a Live Trace in Real Time
> After you email `bawtford@{local_domain}`, press `Alt+4` for [Langfuse]({base_url}/langfuse/) or `Alt+3` for [LiteLLM]({base_url}/proxy/ui/usage) in the left spine to watch the live trace and virtual key usage!
