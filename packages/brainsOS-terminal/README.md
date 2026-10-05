# brainsOS Terminal CLI (`packages/brainsOS-terminal`)

The **brainsOS Terminal CLI** provides platform operational commands and directory tools for the brainsOS appliance. It can run directly on the host development workstation or inside the containerized Operator IDE.

## Features
- `brainsos urls` / `brainsos-urls`: Displays public/LAN endpoints, localhost fallbacks, and credentials.
- `brainsos status` / `brainsos-status`: Probes health and connectivity of internal services (LiteLLM, Caddy, Tool Egress, Hermes/OpenAI runners, Mail server).
- `brainsos models` / `brainsos-models`: Queries and lists LLM models registered in LiteLLM.
- `brainsos chat` / `brainsos-chat`: Sends user prompts to fleet agents.

## Installation
```bash
pip install -e packages/brainsOS-terminal
```
