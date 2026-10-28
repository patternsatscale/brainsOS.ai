# brainsOS-appliance

**Appliance Packaging, HashiCorp Packer AMI Pipelines & Cloud-Init Lifecycle Engine**

`brainsOS-appliance` contains everything needed to build, harden and package brainsOS as a turnkey AWS appliance:

- **AWS Community AMI**: Ubuntu 24.04 ARM64 (Graviton). All platform images are pre-built, and first boot runs IMDSv2 automation.
- **Clean artifacts only**: every AMI is baked from a git ref staged by `scripts/control/build-ami.sh`, never from a working tree. A fail-closed scan aborts the build if any `.env`, runtime data, generated key, SSH key or host key is present.
- **Per-instance secrets**: first boot generates every secret with `scripts/control/generate-env.sh`.
  - Operator login uses the EC2 instance ID (AWS Marketplace convention). The operator should rotate it at first login.
  - Every service credential is independent and random.
- **Perimeter hardening**: UFW default-deny with only 80/443 exposed (port 22 closed), SSH password authentication disabled, and bounded Docker logging.
- **Log management & disk retention**: the systemd journal is capped at 500 MB, with daily logrotate and a daily prune timer.
- **Ambient Bedrock**: LiteLLM uses the EC2 instance role through IMDSv2. There are no API keys in `.env`.
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
# 1. Build a PRIVATE AMI from a release tag (default: latest v* tag)
./scripts/control/build-ami.sh --ref v0.1.1
make build-ami ARGS="--ref v0.1.1"

# Inspect the staged artifact and the exact Packer command without touching AWS
./scripts/control/build-ami.sh --ref v0.1.1 --dry-run

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

## First Login

1. Open `https://<public-dns>/`. The certificate is self-signed until you configure a domain; bring-your-own-domain is tracked in #323.
2. Sign in as `admin` with the **EC2 instance ID** as the initial password.
3. Change the password immediately.
4. For shell access, use `aws ssm start-session --target <instance-id>`. Inbound SSH is closed.

## CLI Usage

```bash
brainsos-appliance validate                 # packer validate (placeholder source_dir)
brainsos-appliance build --dry-run --ref v0.1.1   # delegates to scripts/control/build-ami.sh
brainsos-appliance build --promote ami-0123456789abcdef0
brainsos-appliance status [--json]          # first-boot state, .env permissions, IMDSv2
brainsos-appliance audit [--json]           # host hardening posture
```
