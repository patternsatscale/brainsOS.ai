---
name: launch-fleet
description: >-
  Provision a bulk fleet of single-tenant brainsOS AWS EC2 appliances (via interactive Launch-Template Wizard, direct CLI, or self-contained bundle) from a meeting participant screenshot, name list, or instance count, binding each box to a permanent Route 53 URL (<user>.<base_domain>) with automatic Let's Encrypt TLS and 1-command Day-2 stop/hibernate/terminate.
  Use when the user drops a meeting participant screenshot, asks to spin up demo/workshop boxes via an EC2 Launch Template or AMI, invokes /launch-fleet, or wants to stop/hibernate/terminate a launched fleet.
version: "1.1.0"
tags:
  - appliance
  - aws
  - fleet
  - ec2
  - launch-template
  - route53
  - demo
triggers:
  - "/launch-fleet"
  - "launch-fleet"
  - "launch fleet"
  - "spin up demo"
  - "participants screenshot"
---

# `/launch-fleet` — Bulk EC2 Appliance Launcher & Launch-Template Wizard

`scripts/control/launch-fleet.sh` is a **100% standalone, zero-repo-dependency CLI utility** (works on macOS Bash 3.2+, Linux, WSL, and AWS CloudShell) that provisions dedicated `brainsOS` ARM64 appliances bound to permanent `https://<slug>.<base_domain>` Route 53 URLs.

---

## Standalone Work-Laptop Quickstart (Interactive Launch-Template Wizard)

On any work computer with `aws` CLI + `python3` configured, download and run with zero arguments to enter the interactive menu & EC2 Launch Template picker:

```bash
curl -fsSL https://raw.githubusercontent.com/patternsatscale/brainsOS.ai/main/scripts/control/launch-fleet.sh -o launch-fleet.sh
chmod +x launch-fleet.sh
./launch-fleet.sh
```

Inside the interactive wizard:
1. **Pick your EC2 Launch Template** (`aws ec2 describe-launch-templates`) or Direct AMI mode.
2. **Confirm Base Subdomain** (auto-suggests `demo.<your-route53-zone>`).
3. **Enter a Count (e.g. `10` → `user01..user10`) OR Participant Names** (`Alice Morgan, Bob Patel`).
4. **Confirm & Launch** — prints and saves `<fleet-id>-roster.md` + `<fleet-id>-roster.csv`, then lets you list/stop/hibernate/start/terminate fleets or press `q` to exit cleanly.

---

## Multimodal Meeting-Screenshot Workflow (Claude / Gemini / Antigravity)

When the user drops a screenshot of Zoom / Google Meet / Microsoft Teams participants:

1. **Extract & Clean Human Names**:
   - Strip UI chrome (`(Host)`, `(Co-host)`, `(You)`, `(Guest)`, `(External)`, pronouns, mute labels) and exclude meeting bots (`Otter.ai`, `Fireflies`, `Notetaker`).
2. **Preview Deterministic Slugs (`--dry-run`)**:
   ```bash
   ./scripts/control/launch-fleet.sh \
     --participants "Alice Morgan, Alex Chen, Alex Rivera, Bob Patel" \
     --base-domain demo.infotechlabs.io \
     --dry-run
   ```
3. **Launch Directly (`--apply`) or Emit Pre-Baked Standalone Bundle (`--emit-script`)**:
   ```bash
   # Launch via an existing EC2 Launch Template:
   ./scripts/control/launch-fleet.sh \
     --launch-template brainsos-demo \
     --participants "Alice Morgan, Alex Chen, Alex Rivera, Bob Patel" \
     --base-domain demo.infotechlabs.io \
     --fleet workshop-nov14 \
     --apply

   # Or launch N numbered instances (user01..user10) from a Launch Template:
   ./scripts/control/launch-fleet.sh \
     --launch-template brainsos-demo \
     --count 10 --prefix user \
     --base-domain demo.infotechlabs.io \
     --apply

   # Or emit a pre-configured standalone script to copy-paste to a work laptop:
   ./scripts/control/launch-fleet.sh \
     --launch-template brainsos-demo \
     --participants "Alice Morgan, Bob Patel" \
     --base-domain demo.infotechlabs.io \
     --emit-script ./run-on-work-laptop.sh
   ```

---

## Day-2 Post-Meeting Fleet Lifecycle

```bash
./launch-fleet.sh --list
./launch-fleet.sh --stop --fleet workshop-nov14
./launch-fleet.sh --hibernate --fleet workshop-nov14
./launch-fleet.sh --start --fleet workshop-nov14
./launch-fleet.sh --terminate --fleet workshop-nov14 --yes
```
