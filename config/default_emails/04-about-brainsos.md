---
id: 04-about-brainsos
from_name: brainsOS Appliance
from_user: system
reply_to_user: bawtford
subject: ABOUT: What's in brainsOS?
preheader: Shortcut keys (Alt+1 to Alt+8) and the open-source products powering your appliance.
badge: APPLIANCE DIRECTORY // OPEN-SOURCE STACK
accent: #38bdf8
age_minutes: 6
footer: Sent by brainsOS Appliance (system@{local_domain}) on {unit_name}
---

# ABOUT: What's in brainsOS?

**{unit_name}** combines best-in-class open-source projects into a single zero-trust appliance:

| Shortcut | App Tab | Powered By | Role |
| :--- | :--- | :--- | :--- |
| `Alt+1` | **[Webmail]({base_url}/SOGo/)** | [SOGo](https://sogo.nu/) + [Postfix](https://www.postfix.org/) / [Dovecot](https://www.dovecot.org/) | Agent inbox (`bawtford@{local_domain}`) |
| `Alt+2` | **[Identity]({base_url}/auth/)** | [Authentik](https://goauthentik.io/) | Single sign-on & RBAC |
| `Alt+3` | **[AI Gateway]({base_url}/litellm/)** | [LiteLLM](https://www.litellm.ai/) | Model routing, virtual keys & spend logs |
| `Alt+4` | **[Observability]({base_url}/langfuse/)** | [Langfuse](https://langfuse.com/) | Prompt & tool-call trace telemetry |
| `Alt+5` | **[Network]({base_url}/mitmweb/)** | [mitmproxy](https://mitmproxy.org/) | Egress proxy & in-transit token injection |
| `Alt+6` | **[Editor]({base_url}/editor/)** | [code-server](https://coder.com/docs/code-server) | Browser VS Code for `/memories` |
| `Alt+7` | **[Git]({base_url}/git/)** | [Gitea](https://about.gitea.com/) | Private Git audit trail for agent memories |
| `Alt+8` | **[System]({base_url}/system)** | [Hermes Agent](https://github.com/NousResearch/hermes-agent) + [Ollama](https://ollama.com/) | Runtime, containers & configuration |
