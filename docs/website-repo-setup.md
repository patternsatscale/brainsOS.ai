# Website-Style Repository & Domain Setup Guide (`brainsos.ai`)

> **Target Domain**: [brainsos.ai](https://brainsos.ai) & `www.brainsos.ai`  
> **Canonical Repository**: [github.com/patternsatscale/brainsOS.ai](https://github.com/patternsatscale/brainsOS.ai)  
> **Initiative**: [Patterns at Scale](https://patternsatscale.com)

This playbook documents the configuration required to operate the **brainsOS** GitHub repository as a high-converting, website-style landing page, documentation hub, and community certification portal with `brainsos.ai` routing directly to GitHub.

---

## 1. Domain Redirection Playbook (`brainsos.ai` → GitHub)

To point `brainsos.ai` and `www.brainsos.ai` directly to the GitHub repository (`https://github.com/patternsatscale/brainsOS.ai`) with edge TLS termination and HTTP `301` permanent redirection:

### Step 1: Cloudflare DNS Records (Proxied / Orange Cloud)
Configure proxied DNS records at the Cloudflare zone root so edge redirect rules execute before traffic leaves the edge:

| Type | Name | Target / Content | Proxy Status | TTL |
|---|---|---|---|---|
| `A` | `@` (`brainsos.ai`) | `192.0.2.1` *(RFC 5737 dummy origin for edge redirect)* | 🟠 **Proxied** | Auto |
| `AAAA` | `@` (`brainsos.ai`) | `100::` *(IPv6 discard prefix for edge redirect)* | 🟠 **Proxied** | Auto |
| `CNAME` | `www` | `brainsos.ai` | 🟠 **Proxied** | Auto |

*(Note: Subdomains used by local appliances such as `*.local.brainsos.ai` remain governed by their dedicated Route 53 / local DNS zones and are unaffected by apex/www HTTP redirects).*

### Step 2: Cloudflare Edge Redirect Rule (HTTP 301 Wildcard Forward)
In **Cloudflare Dashboard → Rules → Redirect Rules → Create Rule**:

1. **Rule Name**: `Redirect brainsos.ai and www.brainsos.ai to GitHub Repo`
2. **When incoming requests match** (Custom Filter Expression):
   ```text
   (http.host eq "brainsos.ai" or http.host eq "www.brainsos.ai")
   ```
3. **Then — Type**: `Static` (or `Dynamic` for deep-link subpaths)
   - **Landing Redirect (Recommended)**:
     - **URL**: `https://github.com/patternsatscale/brainsOS.ai`
     - **Status Code**: `301` (Permanent Redirect)
     - **Preserve query string**: Enabled
   - **Optional Deep-Link Wildcard Expression** (forwards `brainsos.ai/issues` → `github.com/patternsatscale/brainsOS.ai/issues`):
     ```text
     concat("https://github.com/patternsatscale/brainsOS.ai", http.request.uri.path)
     ```
     *(When using deep-link forwarding, visiting `https://brainsos.ai` resolves to `https://github.com/patternsatscale/brainsOS.ai/`, and visiting `https://brainsos.ai/issues/257` redirects directly to Issue #257).*

### Step 3: Verify Redirection via CLI
```bash
curl -ILs https://brainsos.ai | grep -E "^(HTTP/|location:)"
curl -ILs https://www.brainsos.ai | grep -E "^(HTTP/|location:)"
```
Expected response: `HTTP/2 301` with `location: https://github.com/patternsatscale/brainsOS.ai`.

---

## 2. GitHub Repository "About" Metadata & Topic Tags

Configure the top-right **About** panel on GitHub (**Repository → ⚙️ Gear Icon next to About**):

- **Description** (≤160 characters):
  ```text
  Sovereign "Enterprise Agent in a Box" appliance OS & COHUMAIN governance runtime. Run in your AWS VPC (Graviton AMI + Bedrock) or on bare-metal silicon.
  ```
- **Website**:
  ```text
  https://brainsos.ai
  ```
- **Include in the home page**:
  - [x] Releases
  - [ ] Packages *(unchecked unless publishing GHCR images publicly)*
  - [ ] Environments *(unchecked to keep the right sidebar clean)*
- **Curated Topic Tags** (14 high-discovery tags):
  ```text
  agentic-ai, ai-governance, ai-safety, cohumain, sovereign-ai, edge-ai, aws-graviton, aws-bedrock, arm64, dgx-os, apple-silicon, litellm, langfuse, mcp
  ```

---

## 3. Social Open Graph Preview Card (`1280 × 640 px`)

Upload a custom Social Preview image under **Settings → General → Social preview** so links shared on X/Twitter, LinkedIn, Slack, Discord, and Hacker News render as a high-contrast product card:

- **Dimensions**: `1280 × 640 px` (2:1 aspect ratio, PNG or JPG `< 1 MB`).
- **Safe Margin**: Keep all text and badges inside the central `1120 × 480 px` safe zone (`80 px` horizontal / `80 px` vertical inset) to avoid cropping across mobile feeds.
- **Visual Spec**:
  - **Background**: Deep slate `#0f172a` with subtle architectural grid and `#38bdf8` / `#818cf8` accent glow.
  - **Primary Headline**: `brainsOS.ai` — *The Sovereign "Enterprise Agent in a Box" Appliance OS*
  - **Sub-Headline**: *"Safe, secure, private, and asynchronous. Run your own single-tenant AI appliance in your AWS VPC or on bare-metal silicon."*
  - **Bottom Pillar Pills**:
    - `🛡️ COHUMAIN ACSG 25-Control Harness`
    - `☁️ AWS Graviton AMI (Ambient Bedrock) & ⚡ Bare-Metal GX10 / Apple Silicon`
    - `🔒 5 Isolated Bridge Nets • Gitea SCM • Zero-Trust SSO`

---

## 4. Interactive HTML Reference Architecture Blueprints (`docs/`)

Two self-contained, zero-dependency interactive HTML reference architecture decks reside in `docs/` and are linked directly from the top navigation bar and Section 4 of [`README.md`](../README.md):

1. **[`docs/brainsos-reference-architecture.html`](brainsos-reference-architecture.html)** — *Appliance Reference Architecture & Network Topology ("Enterprise Agent in a Box", 5 interactive views)*
   - Live browser preview URL: `https://htmlpreview.github.io/?https://github.com/patternsatscale/brainsOS.ai/blob/main/docs/brainsos-reference-architecture.html`
2. **[`docs/brainsos-network-architecture-diagram.html`](brainsos-network-architecture-diagram.html)** — *Enterprise Network Bus & Container NIC Attachment Matrix (3 orthogonal schematic views)*
   - Live browser preview URL: `https://htmlpreview.github.io/?https://github.com/patternsatscale/brainsOS.ai/blob/main/docs/brainsos-network-architecture-diagram.html`

---

## 5. GitHub Discussions Categories & Community Funnel

Enable **GitHub Discussions** under **Settings → General → Features → Discussions** and configure four focused categories to channel community contributions toward COHUMAIN certification:

| Category | Format | Purpose & Pin Strategy |
|---|---|---|
| **📢 Announcements** | *Announcement* (Maintainers post) | Milestone releases (`MVP v0.1`, `v0.2`), security advisories, and COHUMAIN conformance updates. |
| **🛡️ COHUMAIN Controls & PRs** | *Open Discussion / Q&A* | Coordinate implementation of Tier 1 (`cohumain:tier1`) and Tier 2 (`cohumain:tier2`) controls, audit evidence specs, and verification scripts (`scripts/verify/`). |
| **⚡ Edge & AWS Appliance Hardware** | *Open Discussion* | AWS ARM64 Graviton AMI deployments, Ambient Bedrock + IMDSv2 guard setups, ASUS Ascent GX10 (NVIDIA GB10) bare-metal benchmarks, Apple Silicon clusters, solar/battery telemetry, and `max_parallel_requests: 1` tuning. |
| **🚀 Showcase** | *Open Discussion* | Community-built autonomous agent personas (`SOUL.md`), FastMCP tool extensions, and sovereign self-hosted deployments. |

---

## 6. Community Contribution Labels for the COHUMAIN PR Drive

Ensure the following labels exist in the repository issue tracker to coordinate the open community drive:

| Label | Color | Description |
|---|---|---|
| `cohumain:tier1` | `#0E8A16` (Green) | COHUMAIN Tier 1 (Foundational — 8 core safety & security controls) |
| `cohumain:tier2` | `#1D76DB` (Blue) | COHUMAIN Tier 2 (Managed — +10 governance, alignment & red-team controls) |
| `good-first-issue` | `#7057FF` (Violet) | Self-contained control verification script, test harness, or guardrail suitable for new contributors |
| `governance` | `#0075CA` (Ocean) | AI Agentic Governance and Safety Controls (AGSC) |
| `security` | `#EE0701` (Red) | Zero-trust isolation, sandboxing, and egress security |
