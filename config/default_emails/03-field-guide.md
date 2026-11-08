---
id: 03-field-guide
from_name: brainsOS Field Guide
from_user: guide
reply_to_user: bawtford
subject: ✅ Initial Setup Checklist: Update Containers & Run Your First Research Test
preheader: Step-by-step checklist to update daily containers (LiteLLM & Langfuse), send a self-research prompt to Bawtford, and tour your appliance.
badge: INITIAL SETUP CHECKLIST // FIRST-FLIGHT GUIDE
accent: #ec4899
footer: brainsOS Field Guide • Reply directly to route your message to bawtford@{local_domain}
age_minutes: 5
---

# ✅ Initial Setup & First-Flight Checklist

Welcome aboard, **{user}**! Follow this 5-step checklist to get your **{unit_name}** up to date, run your first autonomous research job on yourself, and familiarize yourself with every layer of the system.

## 1. `[ ]` Step 1: Update Your Containers (`Alt+8` System Manager)

Upstream containers (**LiteLLM**, **Langfuse**, and runner images) are updated daily. Before sending your first task, make sure your box is running the latest builds:

1. Press `Alt+8` (or click the **System** icon in the bottom-left spine to open [System Manager (`/system`)]({base_url}/system)).
2. Under **Container Fleet & OS Updates**, check for available updates and run **Update Containers**.
3. Confirm that **LiteLLM** (`brainsos-control-litellm`) and **Langfuse** (`brainsos-telemetry-langfuse-web`) show **Healthy / Up to Date**.

> [!IMPORTANT] Why Update First?
> Confirming **LiteLLM** and **Langfuse** are up to date ensures virtual key usage accounting and OpenTelemetry session traces capture your very first email run cleanly.

## 2. `[ ]` Step 2: Send Bawtford a Research Prompt on Yourself (`Alt+1` Webmail)

Once your containers are healthy, hit **Reply** on this email (it automatically addresses [bawtford@{local_domain}](mailto:bawtford@{local_domain})), replace `{user}` with your full name, and send this prompt:

```prompt
Hi Bawtford,

Do research on {user}. Find obscure facts, hobbies and their career trajectory. Put what you learn into memory and send me a summary. What do you think of the brand?

Try to answer this question: has {user} ever had a dog? What's the name?

Cheers,
{user}
```

## 3. `[ ]` Step 3: Watch Live Egress Traffic While He Works (`Alt+5` Egress Proxy)

Right after you click **Send**, don't just wait in your inbox—watch the box work in real time:

- Press `Alt+5` to open the [Egress Firewall (`mitmweb`)]({base_url}/efw/).
- Watch Bawtford's outbound search requests flow through the proxy while keeping zero raw API/GitHub secrets inside the agent container.

## 4. `[ ]` Step 4: Inspect LiteLLM Guardrails & Langfuse Traces (`Alt+3` & `Alt+4`)

- **`[ ]` Check LiteLLM (`Alt+3`):** Open [LiteLLM Usage (`/proxy/ui/usage`)]({base_url}/proxy/ui/usage) and verify activity under Bawtford's scoped virtual key (`brainsos-bawtford`).
- **`[ ]` Check Langfuse (`Alt+4`):** Open [Langfuse Sessions (`/langfuse/`)]({base_url}/langfuse/) and click into the `mail-bawtford-...` session to inspect every prompt, web search tool call, token count, and latency span.

## 5. `[ ]` Step 5: Read Your Summary & Audit `/memories` (`Alt+1`, `Alt+6` & `Alt+7`)

- **`[ ]` Read the Reply (`Alt+1`):** Jump back to [Webmail (`/mail/`)]({base_url}/mail/) to read Bawtford's research summary (and see if he found your dog!).
- **`[ ]` Audit Readable Memory (`Alt+6` & `Alt+7`):** Press `Alt+6` for the [Code Console (`/editor/`)]({base_url}/editor/) or `Alt+7` for [Gitea (`/git/`)]({base_url}/git/) to inspect the pure Markdown note Bawtford saved in `/memories`.

## On-Box Agent Fleet Reference

| Agent | Address | Role & Speciality |
| :--- | :--- | :--- |
| **Bawtford** | `bawtford@{local_domain}` | Chief Paw-ficer to **Cindy Pawford**, digital manager, web architect & research orchestrator. |
| **Ping** | `ping@{local_domain}` | Zero-GPU instant diagnostic echo & mail-queue latency probe (`1s` sanity check). |
| **Terrastella** | `terrastella@{local_domain}` | Primary operations coordinator & executive strategy synthesis. |
| **Marvin** | `marvin@{local_domain}` | Analytics, systems diagnostics & boundary verification. |
