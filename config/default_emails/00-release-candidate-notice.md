---
id: 00-release-candidate-notice
from_name: brainsOS Release Engineering
from_user: release
reply_to_user: bawtford
subject: ⚠️ Release Candidate Notice: Report Bugs & Feature Requests (Instances Destroyed in 1 Week)
preheader: You are testing a brainsOS Release Candidate build. All test instances will be automatically destroyed in 7 days—please break things and file bugs!
badge: RELEASE CANDIDATE // 7-DAY EPHEMERAL TEST INSTANCE
accent: #f43f5e
footer: brainsOS Release Engineering • Ephemeral RC Preview (Auto-terminates in 7 days)
age_minutes: 0
---

# ⚠️ Release Candidate Preview: Break Things & Report Bugs!

Welcome, **{user}**!

You are driving a **brainsOS v0.1.5 Release Candidate (RC)** appliance on `{domain}`. This environment is spun up specifically for hands-on testing, evaluation, and bug hunting.

> [!WARNING] Ephemeral Instance Notice — Destroyed in 1 Week
> **This is a Release Candidate test environment.** All RC test instances and their volumes will be **automatically destroyed in one week (7 days)**. Do not store permanent production secrets or unbacked-up work on this instance without exporting it first.

## 🐛 Found a Bug or Rough Edge? Tell Us!

We want your honest feedback—whether a container hiccups, a UI button feels clunky, an agent prompt misbehaves, or you think of a feature that would make **brainsOS** 10x better:

1. **In-Portal Bug & Feature Composer:** Click the **Help (`?`)** icon in the bottom-left spine of the Portal and open the **Bugs & Features** tab to draft a pre-filled issue in seconds.
2. **Direct GitHub Bug Report:** [Open a Bug Report on GitHub](https://github.com/patternsatscale/brainsOS.ai/issues/new?template=bug_report.md)
3. **Direct GitHub Feature Request:** [Request a Feature or Agent on GitHub](https://github.com/patternsatscale/brainsOS.ai/issues/new?template=feature_request.md)
4. **Issue Tracker & Roadmap:** [Browse Open Issues on brainsOS.ai](https://github.com/patternsatscale/brainsOS.ai/issues)

## What to Test During Your 7-Day Window

- **Email Bawtford (`bawtford@{local_domain}`):** Check out the *"Try This First"* email right below this one and send **Bawtford** (Chief Paw-ficer to **Cindy Pawford**) a research task.
- **Inspect the Traces (`Alt+3` & `Alt+4`):** Verify that your agent runs light up **LiteLLM** virtual key usage and **Langfuse** OpenTelemetry session traces.
- **Audit the Sandbox (`Alt+5`, `Alt+6`, `Alt+7`):** Check outbound traffic in the **Egress Proxy**, read `/memories` in the **Code Console**, and inspect commit history in **Gitea**.

Thank you for helping us harden **brainsOS** before final general availability!
