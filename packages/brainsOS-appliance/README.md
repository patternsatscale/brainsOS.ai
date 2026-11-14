# brainsOS-appliance

**Appliance Packaging, HashiCorp Packer AMI Pipelines & Cloud-Init Lifecycle Engine**

`brainsOS-appliance` contains everything needed to build, harden and package brainsOS as a turnkey AWS appliance:

- **AWS Community AMI**: Ubuntu 24.04 ARM64 (Graviton). All platform images are pre-built, and first boot runs IMDSv2 automation.
- **Clean artifacts only**: every AMI is baked from a git ref staged by `scripts/control/build-ami.sh`, never from a working tree. A fail-closed scan aborts the build if any `.env`, runtime data, generated key, SSH key or host key is present.
- **Per-instance secrets**: first boot generates every secret with `scripts/control/generate-env.sh`.
  - Operator login uses the EC2 instance ID (AWS Marketplace convention). The operator should rotate it at first login.
  - Every service credential is independent and random.
- **Perimeter hardening**: UFW default-deny with only 80/443 exposed (port 22 closed), SSH password authentication disabled, and bounded Docker logging. If your `.env` sets `BRAINSOS_SYSTEM_API_HOST`, remove it with `scripts/control/env-upsert.sh --unset BRAINSOS_SYSTEM_API_HOST` and restart `brainsos-system-api`.
- **Log management & disk retention**: the systemd journal is capped at 500 MB, with daily logrotate and a daily prune timer.
- **Ambient Bedrock**: LiteLLM uses the EC2 instance role through IMDSv2. There are no API keys in `.env`.
- **IMDS isolation**: `scripts/setup/imds-guard.sh` manages the `BRAINSOS-IMDS` iptables chain (jumped from `DOCKER-USER` for `169.254.169.254/32`), allowing only the LiteLLM control-plane container to reach EC2 IMDSv2 and dropping all other containers (including agent runners). Verify at any time with `sudo scripts/setup/imds-guard.sh --check`.
- **Zero-inbound remote access**: the AWS SSM Agent is installed. Packer also builds over Session Manager by default.

## Layout

| Path | Purpose |
|------|---------|
| `packer/brainsos-ami.pkr.hcl`, `packer/variables.pkr.hcl` | Packer templates. `source_dir` is the staged artifact; `imds_support = "v2.0"`; SSM communicator. |
| `packer/provision.sh` | Build-time provisioner: packages, units, hardening, image pre-build, `.venv`, sanitization, `--scan-only`. |
| `scripts/firstboot.sh` | Per-instance init: IMDSv2 → `generate-env.sh` → appliance overrides → `bootstrap-env.sh` (data seed) → portal. |
| `scripts/harden-host.sh` | UFW, sshd, Docker daemon, journald and logrotate enforcement. |
| `configs/` | systemd units (`brainsos`, `brainsos-firstboot`, `brainsos-prune-logs`) and host config templates. |
| `iam/instance-policy.json` | Least-privilege instance-role policy (Bedrock invoke + SSM core). |

## Building & Publishing an AMI

The private-first release flow:

```bash
# 1a. Fast incremental delta AMI (~5 min): builds atop newest self-owned brainsos-* AMI
./scripts/control/build-ami.sh --incremental --ref v0.5.1
# Or pin a specific base AMI explicitly:
./scripts/control/build-ami.sh --from-ami ami-0eac84eb9a9415531 --ref v0.5.1

# 1b. Clean-room baseline AMI (~35-40 min): builds from Canonical Ubuntu 24.04 LTS ARM64
./scripts/control/build-ami.sh --ref v0.5.1
make build-ami ARGS="--incremental --ref v0.5.1"

# Inspect the staged artifact and the exact Packer command without touching AWS
./scripts/control/build-ami.sh --from-ami ami-0eac84eb9a9415531 --ref v0.5.1 --dry-run

# 2. Rehearse the private AMI (launch, first boot, login, Bedrock completion)

# 3. Promote to public (checks AMI Block Public Access + unencrypted snapshots first)
./scripts/control/build-ami.sh --region us-east-1 --promote ami-0123456789abcdef0
```

**Build host requirements:**

- Packer
- AWS CLI v2 with valid credentials
- [`session-manager-plugin`](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html), unless you pass `--ssh-interface public_ip`

`build-ami.sh` refuses to run on a dirty working tree; pass `--allow-dirty` to override. Even then, local edits are never included in the AMI.

## Instance Role (IAM)

Launch the AMI with an instance profile whose role attaches [`iam/instance-policy.json`](iam/instance-policy.json):

```bash
aws iam create-role --role-name brainsos-appliance \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam put-role-policy --role-name brainsos-appliance --policy-name brainsos-appliance \
  --policy-document file://packages/brainsOS-appliance/iam/instance-policy.json
aws iam create-instance-profile --instance-profile-name brainsos-appliance
aws iam add-role-to-instance-profile --instance-profile-name brainsos-appliance --role-name brainsos-appliance
```

The policy grants:

- Bedrock invoke/converse on Anthropic and Amazon Nova foundation models and on `us.*` inference profiles
- read-only model discovery
- SSM Session Manager core actions

You must also enable access to the models you plan to use in the Bedrock console. The model catalog lives in `config/litellm/config.bedrock.yaml` and uses `us.` cross-region inference profiles. Outside US regions, swap the prefix (`eu.`, `apac.`, `global.`).

## First Login & TLS Configuration

1. **Access Appliance**: Open `https://<public-dns>/` or `https://<public-ip>/`. The appliance runs with Caddy's internal CA (self-signed) by default.
2. **Trust Root CA (Optional)**: Download the internal root CA certificate directly from the authenticated endpoint `https://<public-dns>/system/ca.crt` (or run `scripts/setup/trust-caddy-ca.sh --export` on host) and import it into your browser trust store.
3. **Sign In**: Log in as `admin` with the **EC2 instance ID** as the initial password. Change the password immediately.
4. **Shell Access**: Use AWS SSM: `aws ssm start-session --target <instance-id>`. (Inbound SSH port 22 is closed by default).
5. **Bring Your Own Domain (BYOD)**:
   - **Interactive / Post-Boot CLI**:
     ```bash
     # Let's Encrypt / ZeroSSL public ACME:
     make set-domain ARGS="--domain brainsos.myorg.com --email ops@myorg.com"

     # Route 53 DNS-01 (uses ambient EC2 IAM role, zero static keys):
     make set-domain ARGS="--domain brainsos.myorg.com --email ops@myorg.com --dns route53"

     # Revert to Caddy internal self-signed CA:
     make set-domain ARGS="--internal"
     ```
   - **Launch-Time EC2 User-Data & Dynamic Fleet DNS (`v0.5.1` / #373)**:
     Supply cloud-config or `KEY=VALUE` pairs in EC2 User Data at launch. When `BRAINSOS_ROUTE53_ZONE_ID` (or `HOSTED_ZONE_ID`) is supplied alongside `BRAINSOS_DOMAIN` (or `BRAINSOS_BASE_DOMAIN` + EC2 `Name` tag), the appliance automatically:
     1. Registers/updates its Route 53 `A` record (`TTL=60`) and `_brainsos-owner.<fqdn>` `TXT` ownership lock on cold boot, reboot, stop/start, and hibernation wake-up (`scripts/control/sync-route53-ddns.py`), eliminating Elastic IP limits across 30+ instances.
     2. Provisions Let's Encrypt public ACME TLS (`BRAINSOS_TLS_MODE=acme`) automatically.
     3. Streamlines the First-Boot Setup Wizard into a **2-step flow** where end users create their personal Superuser account and Unit Name while keeping User-Data DNS + SSL locked in.
     ```yaml
     #cloud-config
     brainsos:
       domain: alice.demo.infotechlabs.io
       route53_zone_id: Z0123456789ABCDEFG
       email: ops@infotechlabs.io
     ```
     Or using a shared Launch Template across a multi-instance fleet (derives `<ec2-name-tag>.demo.infotechlabs.io` automatically):
     ```ini
     BRAINSOS_BASE_DOMAIN=demo.infotechlabs.io
     BRAINSOS_ROUTE53_ZONE_ID=Z0123456789ABCDEFG
     ```
     Attach [`iam/route53-ddns-policy.json`](iam/route53-ddns-policy.json) to the EC2 Instance Role to scope `route53:ChangeResourceRecordSets` strictly to your target subdomain wildcard. Caddy uses fallback-to-internal issuance, ensuring HTTPS remains available with zero downtime while ACME verification completes.
   - **Bulk Meeting-Roster Fleet Launcher (`/launch-fleet` Skill & `scripts/control/launch-fleet.sh` — #377)**:
     Drop a screenshot of meeting participants into VS Code (`/launch-fleet`) or invoke `scripts/control/launch-fleet.sh` directly to launch 5–30+ single-tenant appliances in one shot (or emit a zero-dependency AWS CloudShell script):
     ```bash
     # 1. Dry-run preview (sanitizes UI noise + disambiguates duplicate first names):
     ./scripts/control/launch-fleet.sh \
       --participants "Alice Morgan (Host), Alex Chen, Alex Rivera" \
       --base-domain demo.infotechlabs.io

     # 2. Emit self-contained AWS CloudShell script (or pass --apply to launch directly):
     ./scripts/control/launch-fleet.sh \
       --participants "Alice Morgan, Bob Patel, Charlie Kim" \
       --base-domain demo.infotechlabs.io \
       --fleet workshop-nov14 \
       --emit-script ./launch-workshop-nov14.sh

     # 3. Day-2 lifecycle (stop / hibernate / start / terminate by BrainsOSFleet tag):
     ./scripts/control/launch-fleet.sh --stop --fleet workshop-nov14
     ./scripts/control/launch-fleet.sh --terminate --fleet workshop-nov14 --yes
     ```

## CLI Usage

```bash
brainsos-appliance validate                 # packer validate (placeholder source_dir)
brainsos-appliance build --dry-run --ref v0.1.1   # delegates to scripts/control/build-ami.sh
brainsos-appliance build --promote ami-0123456789abcdef0
brainsos-appliance status [--json]          # first-boot state, .env permissions, IMDSv2
brainsos-appliance audit [--json]           # host hardening posture
```
