# Project Titan: Platform Cloud Infrastructure (`infra/`)

This directory contains the decoupled **SST v3 (Ion)** cloud infrastructure for **Project Titan**. It provisions and manages platform-wide AWS cloud resources, including Route 53 DNS, public split-horizon HTTP redirects, least-privilege ACME DNS-01 challenge IAM credentials for local appliance Caddy ingress, and SES (Simple Email Service) domain identity building blocks.

---

## Architectural Principles & Boundaries

1. **Decoupled from Application Stacks**:
   - `infra/` is strictly for Project Titan platform-level cloud resources.
   - Application workspaces (e.g. `apps/cindypawford/infra/`) remain separate and independent.

2. **Strictly Local Operator Execution (Zero GitHub Triggers)**:
   - Platform cloud infrastructure is deployed **exclusively via local operator CLI** (`./scripts/setup/deploy-infra.sh` or `npx sst deploy`).
   - There are **no automated GitHub Actions deployment workflows** for `infra/`. This ensures high-privilege cloud administrator credentials never need to be uploaded to GitHub repository secrets.

3. **Zero Domain Leakage**:
   - In accordance with Project Titan's open-source requirements, production domain names are **never hardcoded in committed code**.
   - All domain names, hosted zones, and email identities are dynamically read from uncommitted local `.env` variables (`TITAN_ZONE_NAME`, `TITAN_SUBDOMAIN`, `SES_DOMAINS`) with generic fallbacks (`example.com`).

4. **Namespaced IAM Credential Isolation**:
   - Platform deployments consume `TITAN_INFRA_AWS_ACCESS_KEY_ID`, `TITAN_INFRA_AWS_SECRET_ACCESS_KEY`, and `TITAN_INFRA_AWS_REGION`.
   - This isolates Titan platform infrastructure operations and audits from tenant application keys (e.g. CindyPawford.com).

---

## Configuration (`.env`)

Copy the template to your local environment file:

```bash
cp infra/.env.example infra/.env
```

| Parameter | Description | Default Fallback |
| :--- | :--- | :--- |
| `TITAN_INFRA_AWS_ACCESS_KEY_ID` | AWS Access Key ID for platform infrastructure deployment | None |
| `TITAN_INFRA_AWS_SECRET_ACCESS_KEY` | AWS Secret Access Key for platform deployment | None |
| `TITAN_INFRA_AWS_REGION` | AWS Region for Route 53 & CloudFront certificates | `us-east-1` |
| `TITAN_ZONE_NAME` | Apex domain / Route 53 hosted zone | `example.com` |
| `TITAN_SUBDOMAIN` | Subdomain prefix for appliance routing | `titan` |
| `TITAN_CREATE_ZONE` | Set `true` to provision a new Route 53 zone, `false` to lookup existing | `false` |
| `TITAN_GITHUB_REDIRECT_URL` | Destination for public web visitors hitting `titan.<domain>` | `https://github.com/patternsatscale/project-titan` |
| `SES_DOMAINS` | Comma-separated list of domains to configure in SES | Value of `TITAN_ZONE_NAME` |

---

## Operational Commands

### 1. Validate TypeScript Configuration
```bash
npm run typecheck
```

### 2. Preview Cloud Changes (Dry Run / Diff)
```bash
./scripts/setup/deploy-infra.sh --dry-run
# or
npx sst diff --stage production
```

### 3. Deploy Platform Infrastructure
```bash
./scripts/setup/deploy-infra.sh --stage production
# or
npx sst deploy --stage production
```

### 4. Wire Caddy ACME Credentials into Appliance
Upon deployment, SST outputs `caddyAcmeAccessKeyId` and `caddyAcmeSecretAccessKey`. Place these into the repository root `.env` as:
```bash
AWS_ACCESS_KEY_ID=<caddyAcmeAccessKeyId>
AWS_SECRET_ACCESS_KEY=<caddyAcmeSecretAccessKey>
AWS_REGION=us-east-1
TITAN_DOMAIN=titan.<yourdomain>
ACME_DNS_PROVIDER=route53
```
Then reload the Caddy container:
```bash
docker compose up -d --build caddy
```
