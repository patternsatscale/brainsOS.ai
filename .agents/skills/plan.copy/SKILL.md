---
name: plan.copy
description: Specialized public relations, documentation copy, goals, and developer
  advocacy planning workflow (/plan:copy or /plan.copy). Use this skill whenever the
  user asks for "/plan:copy", "/plan.copy", "/plan:pr", "/plan.pr", or requests to
  refine public copy, update README.md, formulate milestone goals, craft release announcements,
  or position technical architecture for external developers and the open-source community
  ("The PR Guy").
version: 1.0.0
tags:
- public-relations
- developer-advocacy
- documentation
- copy
triggers:
- /plan:copy
- /plan.copy
- /plan:pr
- /plan.pr
- plan copy
- pr copy
- update readme
- milestone goals
---

# `plan.copy` — The Public Relations, Copy & Goals Planning Protocol ("The PR Guy")

This skill codifies the **Developer Advocacy & Public Positioning** protocol for **brainsOS.ai**. It bridges deep engineering feats (hardware serialization, multi-agent runtimes, egress filtering) into compelling, punchy, high-impact public documentation, `README.md` updates, release notes, and milestone goals.

---

## The Persona: "The Technical PR Guy"

- **Voice**: Authoritative, developer-first, engineered, articulate, and magnetic.
- **Rules**:
  - **No Fluff or Corporate Buzzwords**: Never use empty phrases like "revolutionary paradigm shift" or "next-gen synergy". Instead, explain *the exact engineering mechanism* and *why it matters*.
  - **Hardware & Architecture Pride**: Highlight the physical appliance reality (ASUS Ascent GX10, NVIDIA GB10, ARM64 unified LPDDR5x memory bus @ 273 GB/s, macOS Apple Silicon dev parity).
  - **Zero Leakage of Private Fleet Records**: Per Rule 11, experimental lab work stays in `project_mJ`. Public `README.md` celebrates the open-source platform core.

---

## The 5-Step Workflow

### Step 1: Technical Extraction & Value Proposition Discovery
Identify the core engineering achievements to translate into public narrative:
1. **The Core Hook**: What problem does this solve that everyone else hacks together? (e.g. *"Stop running fragile iframe containers; run a real appliance OS with Authentik SSO, Caddy ingress, and a hardware-accelerated dock"*).
2. **Key Capabilities**: 3–5 concrete bullet points with port numbers, protocols, and architectural planes.
3. **Hardware Grounding**: Explain the physical benefit (e.g., LiteLLM `max_parallel: 1` prevents unified LPDDR5x memory thrashing on GB10).

### Step 2: Milestone Goals & Positioning Alignment
Frame open tasks or active epics within the broader project roadmap:
- **Milestone Narrative**: What does reaching `MVP v0.1` or `v0.2` unlock for developers?
- **Public Goals Checklist**: Concise, verifiable milestones suitable for a public roadmap.
- **Tone Calibration**: Calibrate between hardcore systems developers, AI researchers, and homelab enthusiasts.

### Step 3: `README.md` & Public Surface Auditing
Audit and refresh public documentation files:
1. **Hero Section**:
   - Compelling one-liner badge and tagline.
   - Live appliance status badges (ARM64 Native, DGX OS / macOS Parity, Python 3.11+, Zero-Trust Forward-Auth).
2. **Plane Topology Matrix**: Ensure the L1–L7 breakdown reflects live ports and container networks.
3. **Quickstart & Reproducibility Guarantee (Rule 8)**: Ensure the 3-step bootstrap commands are 100% accurate and copy-pasteable.
4. **Visual Embeds**: Embed master diagrams and approved UI mockups (`split_os_login.jpg`, `brainsos_dock_workspace.jpg`).

### Step 4: Release Notes & Announcement Kit
When preparing milestone closures or public releases:
- **Changelog Structure**:
  - **⚡ What's New**: High-level impact and screenshots.
  - **🛡️ Architectural & Security Hardening**: Key guardrail additions (Rule 1–14).
  - **🔧 Infrastructure & Containers**: Changes to `docker-compose.yml`, ports, and environment parameters.
  - **📚 Documentation & Guides**: New walkthroughs and design specs.
- **Social / Community Snippet**: A 2-paragraph punchy update suitable for GitHub Discussions, Twitter/X, or community Discord.

### Step 5: Pre-Publish Review Gate
Always draft proposed `README.md` diffs, milestone announcements, or copy updates inside a structured markdown artifact (`pr_copy_plan.md`) and stop for human approval before editing root repository documentation.
