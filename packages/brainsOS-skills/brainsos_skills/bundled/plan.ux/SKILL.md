---
name: plan.ux
description: >-
  Specialized UI/UX prototype and visual mockup planning workflow (/plan:ux or /plan.ux).
  Use this skill whenever the user asks for "/plan:ux", "/plan.ux", "/plan:design",
  or requests to design, prototype, mock up, or visually iterate on web applications,
  canvases, dashboards, portals, or frontend interfaces before writing production code.
version: "1.0.0"
tags:
  - ui-ux
  - design-systems
  - prototyping
triggers:
  - "/plan:ux"
  - "/plan.ux"
  - "/plan:design"
  - "/plan.design"
  - "plan ux"
  - "design mockup"
  - "prototype portal"
---

# `plan.ux` — The UI/UX Prototype & Mockup Alignment Protocol

This skill codifies the disciplined 5-step UI/UX prototyping and mockup alignment workflow developed for **brainsOS.ai**. It ensures visual aesthetics, layout ergonomics, branding, and windowing paradigms are completely aligned with the user **before writing production code or modifying containers**.

---

## The 5-Step Workflow

### Step 1: Design Alignment & Interaction Interview
Before touching code or generating renders, conduct a focused interview with the operator:
1. **Target Viewports & Context**: Operating system desktop, mobile web, embedded dashboard, or fullscreen terminal.
2. **Windowing & Layout Paradigm**: Side-by-side split, floating application dock ("Dockey"), embedded iframes vs native pages, modal drawers, or tiled panels.
3. **Core Subsystems Taxonomy**: Determine the exact 4–6 core applications or modules (e.g. Console, Comms, Security, Network, Trace, Help).
4. **Distraction-Free Copy**: Strip unnecessary jargon, crypto-speak, or placeholder badges. Ensure headlines sound authentic to an appliance or operating system.

### Step 2: Design Token Codification & `DESIGN.md` Synchronization
All visual tokens must be documented in the feature or epic's canonical design specification (e.g. `docs/epics/<epic_name>/DESIGN.md`):
- **Obsidian Dark Substrate**: `#0B0E14` base with `#111622` and `#1D2026` glass layers.
- **Accents**: Cyber Cyan (`#00F2FE`), Neural Violet (`#7928CA`), Synthetic Emerald (`#10B981`).
- **Typography**: `Space Grotesk` (Headlines), `Geist` (Body), `JetBrains Mono` (Telemetry & Code).
- **Background Grid Substrates**: 3D perspective matrix cube vector grid, radial dot grids, or circuit traces.
- **No Mirror Artifacts**: Pure matte floating surfaces with zero bottom floor reflections (`-webkit-box-reflect: none`).

### Step 3: High-Fidelity Visual Mockup Generation (`generate_image`)
Use the `generate_image` tool to render photorealistic 16:9 or 1:1 UI design concepts:
- **Prompt Engineering Rules**:
  - Request ultra-clean dark mode UI with exact token colors and typography.
  - Explicitly mandate: *"NO mirror reflection, NO floor reflection, NO inverted text reflections beneath the dock shelf"*.
  - Include 3D perspective cyber grid vector lines in the background when matching the matrix room aesthetic.
  - Save to artifact directory, copy canonical asset to `docs/epics/<epic_name>/stitch/`, and embed in the implementation plan.

### Step 4: Live Interactive HTML/CSS/JS Prototype (`stitch/`)
Build a tactile, interactive prototype in `docs/epics/<epic_name>/stitch/`:
- **File Structure**:
  - `code.html`: Clean, standalone component/page implementation (e.g. side-by-side OS login).
  - `portal_prototype.html`: Complete multi-view interactive prototype (`#login`, `#dock`, `#help`).
  - `matrix_cube_bg.svg`: Dedicated SVG vector background for the 3D perspective cyber grid.
- **Windowing & Iframe Interaction**:
  - Floating persistent dock (`z-index: 50`) with frosted-glass blur hovering over the bottom of the active iframe.
  - OS window title bar with application name, status pill (`● SYSTEM NOMINAL`), Minimize, and Pop Out controls.
  - In-place iframe swapping without full page reloads, preserving active terminal and editor states.
  - Dock auto-hide / collapse toggle.

### Step 5: Local Preview Server & Human Walkthrough Gate
1. Ensure the background preview server is running on port `3033`:
   ```bash
   python3 -m http.server 3033 --directory docs/epics/<epic_name>/stitch
   ```
2. Verify all routes return `HTTP 200 OK`.
3. Provide clickable localhost links with exact anchor hashes:
   - Primary Workspace: `http://localhost:3033/portal_prototype.html#dock`
   - Authentication Screen: `http://localhost:3033/code.html`
   - Help / Architecture: `http://localhost:3033/portal_prototype.html#help`
4. **Mandatory Pre-Commit Review Gate**: Stop and gather human developer feedback on layout, copy, and interaction before touching production Dockerfiles or Compose configurations.
