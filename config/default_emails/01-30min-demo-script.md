---
id: 01-30min-demo-script
from_name: brainsOS Demo Playbook
from_user: playbook
reply_to_user: bawtford
subject: 🎬 The 30-Minute Member Demo Script (Run of Show & Pre-Flight Checklist)
preheader: Running back-to-back 30-minute member sessions? Follow this exact run-of-show: pre-flight container update, deep-dive permission, live Bawtford research, and under-the-hood tour.
badge: PRESENTER PLAYBOOK // 30-MIN MEMBER MEETING SCRIPT
accent: #eab308
footer: brainsOS Presenter Playbook • Reply directly to route your live demo prompt to bawtford@{local_domain}
age_minutes: 1
---

# 🎬 The 30-Minute Member Demo Playbook

Running back-to-back 30-minute member meetings on **{unit_name}**? Keep this playbook handy. It turns a 30-minute conversation into a live, interactive under-the-hood tour while **Bawtford** researches your guest in real time.

> [!IMPORTANT] Pre-Flight Checklist (10 Minutes Before Your First Meeting)
> **Update your containers first!** Press `Alt+8` (or open [System Manager (`/system`)]({base_url}/system)) and click **Update All Containers / Check Updates** so your appliance is running the latest images and warm before your first call starts.

## ⏱️ Minute-by-Minute Run of Show (30 Mins)

| Time | Beat & Subsystem | What to Say & Show |
| :--- | :--- | :--- |
| **00–05m** | **1. Permission & Slides** (`Help ? → Architecture`) | Ask *"Can I get your permission to do a live under-the-hood deep dive?"* Walk through the **Enterprise Agent in a Box** slides (or the **Architecture** tab in the Help menu). |
| **05–08m** | **2. Kick Off Bawtford** (`Alt+1` Webmail) | Ask the member for their name, hit **Reply** on this email, paste the prompt below with their name, and hit **Send**. Don't wait in the inbox—immediately go under the hood! |
| **08–13m** | **3. Live Network Traffic** (`Alt+5` Egress Proxy) | While Bawtford is working, switch to `Alt+5` ([Egress Proxy]({base_url}/efw/)). Show live outbound search queries in `mitmweb`, destination allowlists, and zero ambient container secrets. |
| **13–18m** | **4. Routing & Guardrails** (`Alt+3` LiteLLM) | Switch to `Alt+3` ([LiteLLM Gateway]({base_url}/proxy/ui/usage)). Show per-agent virtual key attribution (`brainsos-bawtford`), policy guardrails, spend caps, and serialized inference. |
| **18–23m** | **5. Decision & Tool Trace** (`Alt+4` Langfuse) | Switch to `Alt+4` ([Langfuse Observatory]({base_url}/langfuse/)). Open the active `mail-bawtford-...` session trace to show the exact prompt, web search tool calls, token breakdown, and latency. |
| **23–30m** | **6. The Reveal, Memory & Q&A** (`Alt+1` & `Alt+6`) | Return to `Alt+1` ([Webmail]({base_url}/mail/)) to read Bawtford's summary (and the dog question!), peek at the pure Markdown note in `Alt+6` ([Code Console]({base_url}/editor/)), and open up for **Q&A**. |

## 📋 Copy-Paste Live Meeting Prompt (Min 05–08)

Hit **Reply** on this email (it automatically addresses `bawtford@{local_domain}`), swap `[Member Name]` with your guest's name, and hit **Send**:

```prompt
Hi Bawtford,

Do research on [Member Name]. Find obscure facts, hobbies and their career trajectory. Put what you learn into memory and send me a summary. What do you think of the brand?

Try to answer this question: has [Member Name] ever had a dog? What's the name?

Cheers,
{user}
```

## 💡 Presenter Pro-Tips for Back-to-Back Sessions

1. **Hotkey Flow (`Alt+1` → `Alt+5` → `Alt+3` → `Alt+4` → `Alt+1`):** You never need to hunt for browser tabs during screen-share—just use `Alt+1..8` (or the left icon spine) to glide between planes while Bawtford works in the background.
2. **Show, Don't Just Tell (Readable Memory):** In the final 5 minutes, pressing `Alt+6` ([Code Console]({base_url}/editor/)) or `Alt+7` ([Gitea]({base_url}/git/)) to show the human-readable Markdown file Bawtford just wrote into `/memories` is always the "aha!" moment for technical and executive members alike.
