---
name: launch-fleet
description: Provision a bulk fleet of single-tenant brainsOS AWS EC2 appliances (or
  emit a self-contained AWS CloudShell script) directly from a screenshot or list
  of meeting participants (Zoom, Google Meet, Microsoft Teams), binding each participant
  to a permanent Route 53 URL (<user>.<base_domain>) with automatic Let's Encrypt
  TLS and 1-command Day-2 stop/hibernate/terminate. Use when the user drops a meeting
  participant screenshot, asks to spin up demo/workshop boxes for attendees, invokes
  /launch-fleet, or wants to stop/hibernate/terminate a launched fleet.
version: 1.0.0
tags:
- appliance
- aws
- fleet
- ec2
- route53
- demo
triggers:
- /launch-fleet
- launch-fleet
- launch fleet
- spin up demo
- participants screenshot
---

# `/launch-fleet` — Meeting-Screenshot Bulk EC2 Appliance Launcher

Turn a screenshot (or list) of meeting participants into dedicated, single-tenant **brainsOS ARM64 Graviton** appliances—each bound to a permanent `https://<user>.<base_domain>` URL that survives reboots, stop/start cycles, and hibernation without Elastic IPs.

---

## Step 1: Extract & Clean the Participant Roster

When the user provides a screenshot (Zoom, Google Meet, Microsoft Teams, Slack huddle, calendar invite) or text list:

1. **Read every visible participant name** using multimodal vision.
2. **Strip UI chrome & non-human entries**:
   - Remove suffixes like `(Host)`, `(Co-host)`, `(You)`, `(Guest)`, `(External)`, `(Presenter)`, pronouns, mute/camera labels, and dial-in phone numbers or meeting room bots (`Notetaker`, `Otter.ai`, `Fireflies`, `Room 4B`).
   - Ask whether to include the host (`(You)` / organizer) only if ambiguous; by default include human participants and note if the host was excluded or included.
3. **Determine the target `--base-domain`**:
   - Use the domain specified by the user (e.g. `demo.infotechlabs.io`).
   - If the user has not specified a `--base-domain` yet, ask once (e.g., *"Which base domain should I use (e.g. `demo.infotechlabs.io`)?"*).

---

## Step 2: Run Safe Dry-Run Preview & Confirm Before Launching

Always run `./scripts/control/launch-fleet.sh` in default `--dry-run` mode first so deterministic DNS slug disambiguation (`Alex Chen` + `Alex Rivera` → `alexc`, `alexr`) is verified:

```bash
./scripts/control/launch-fleet.sh \
  --participants "Alice Morgan, Alex Chen, Alex Rivera, Bob Patel" \
  --base-domain demo.infotechlabs.io \
  --fleet workshop-$(date +%Y%m%d-%H%M)
```

Present the preview table to the user and confirm whether they want to:
1. **Launch directly now (`--apply`)** — if their VS Code terminal has AWS CLI credentials configured for the target AWS account (`aws sts get-caller-identity`).
2. **Generate a self-contained AWS CloudShell script (`--emit-script`)** — if they want a single zero-dependency `.sh` file they can paste/upload into AWS CloudShell on another AWS account.

*(If the user explicitly said "go ahead and launch" or "give me the CloudShell script" upfront, check `aws sts get-caller-identity` to confirm the target AWS account ID before running `--apply`, or emit the script immediately for `--emit-script`.)*

---

## Step 3: Execute Launch (`--apply`) or Emit CloudShell Script (`--emit-script`)

### Option A — Direct Launch from VS Code Terminal (`--apply`)
```bash
./scripts/control/launch-fleet.sh \
  --participants "Alice Morgan, Alex Chen, Alex Rivera, Bob Patel" \
  --base-domain demo.infotechlabs.io \
  --fleet workshop-nov14 \
  --apply
```
*(Optional flags: `--hibernation-capable` to enable RAM-preserving EC2 hibernation, `--instance-type m7g.xlarge`, `--region us-east-1`, `--ami ami-...`, `--zone-id Z...`, `--profile-name instanceRoleBedrock`.)*

### Option B — Self-Contained AWS CloudShell Script (`--emit-script`)
```bash
./scripts/control/launch-fleet.sh \
  --participants "Alice Morgan, Alex Chen, Alex Rivera, Bob Patel" \
  --base-domain demo.infotechlabs.io \
  --fleet workshop-nov14 \
  --emit-script ./launch-workshop-nov14.sh
```
The emitted script has **zero repository dependencies**: it auto-discovers the Route 53 Hosted Zone ID, newest self-owned or shared `brainsos-*` ARM64 AMI, IAM Instance Profile (`instanceRoleBedrock` + inline Route 53 DDNS policy), and `80`/`443` Security Group (`brainsos-fleet-https-sg`, port `22` closed).

---

## Step 4: Participant Handoff & Onboarding Flow

Share the generated **Participant Handoff Roster** (`<fleet-id>-roster.md` / `.csv`) with attendees:

| Participant | Permanent Appliance URL | First-Boot Instance ID Key |
|---|---|---|
| Alice Morgan | `https://alice.demo.infotechlabs.io` | `i-0abc1234def567890` |

**What each participant experiences (~60–90s after launch)**:
1. Opens `https://<slug>.<base_domain>` (valid Let's Encrypt TLS certificate + Route 53 `A` record `TTL=60` already configured via EC2 User Data).
2. Unlocks first-boot onboarding with their `i-...` Instance ID key.
3. Completes the streamlined **2-step Wizard**: names their appliance and creates their personal Superuser username & password (provisioned across Authentik SSO, SOGo Webmail, Gitea, and LiteLLM). DNS & SSL steps are automatically skipped and locked in.

---

## Step 5: Day-2 Post-Meeting Fleet Lifecycle

Manage an entire workshop fleet in one command using its `BrainsOSFleet` tag:

```bash
# Inspect all active fleet instances & public IPs
./scripts/control/launch-fleet.sh --list
./scripts/control/launch-fleet.sh --list --fleet workshop-nov14

# Stop all instances after the session (preserves EBS; next --start auto-updates Route 53 IPs in ~60s!)
./scripts/control/launch-fleet.sh --stop --fleet workshop-nov14

# Hibernate all instances (if launched with --hibernation-capable)
./scripts/control/launch-fleet.sh --hibernate --fleet workshop-nov14

# Resume stopped/hibernated fleet before the next session (same URLs!)
./scripts/control/launch-fleet.sh --start --fleet workshop-nov14

# Permanently tear down the fleet when finished
./scripts/control/launch-fleet.sh --terminate --fleet workshop-nov14 --yes
```
