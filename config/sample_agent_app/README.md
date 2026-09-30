# brainsOS: Sample Agent Applications (`config/sample_agent_app/`)

This directory houses declarative template seeds, baseline digital canvases, and public web application blueprints for autonomous agents on **brainsOS** ([brainsOS.ai](https://brainsos.ai)).

During environment initialization (`scripts/control/bootstrap-env.sh`), templates from `config/sample_agent_app/` are seeded into `data/agent_apps/` to provide editable runtime application workspaces for agent fleets.

---

## 1. The Blind Deployer & Workspace Isolation Architecture

To ensure zero trust and prevent hostile or hallucinatory compromise of cloud infrastructure, `data/agent_apps/` strictly decouples untrusted agent-authored code from host-executed deployment pipelines:

```text
data/agent_apps/<app_id>/
├── site/                     # UNTRUSTED AGENT OUTPUT
│   ├── index.html            # - Mounted into agent container at /app/html
│   ├── styles.css            # - Agents have write access strictly here
│   ├── app.js                # - Pure HTML/CSS/JS only (no backend secrets)
│   └── _platform/            # - Host-injected platform shell & runtime configs
│
├── pipeline/                 # PROTECTED HOST INFRASTRUCTURE
│   ├── sst.config.ts         # - SST Ion / AWS CloudFormation IaC
│   ├── package.json          # - Host deployment scripts & dependencies
│   └── src/                  # - Protected platform serverless handlers & shell
│
├── archive/                  # HISTORICAL ARTIFACT VAULT
│   ├── eras.json             # - Sealed weekly era snapshots
│   └── logbook.json          # - Declassified execution records
│
├── assets/                   # STATIC DESIGN & GRAPHICAL ASSETS
├── clean-slate/              # REPRODUCIBLE INITIAL CANVAS SEEDS
└── info/                     # PUBLIC REPOSITORY & SPECIFICATION OVERVIEWS
```

---

## 2. Operator Security Guidelines

1. **Untrusted Agent Territory (`site/`)**:
   - Everything inside `data/agent_apps/<app_id>/site/` is considered autonomous agent output.
   - The agent container binds `./data/agent_apps/<app_id>/site` to `/app/html` with restricted file permissions (`PUID:PGID 1000:1000`).
   - Protected subpaths (such as `.github/` inside `site/`) are mounted read-only (`:ro`) to prevent agents from modifying GitHub Actions workflows.

2. **Protected Host Infrastructure (`pipeline/`)**:
   - `pipeline/` contains the SST Ion TypeScript definitions, AWS Lambda handlers, DynamoDB schemas, and CloudFront CDN distribution settings.
   - **Agent containers are never granted mounts or read/write access to `pipeline/`**.
   - Cloud deployment credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) exist exclusively on the host or inside GitHub Actions secrets, never inside agent environments.

3. **Autonomous Deployment Workflow**:
   - When an autonomous agent completes an iteration on `site/`, it commits and pushes to `main` via git (routed through the authenticated Tool Egress Gateway).
   - GitHub Actions (`deploy-sst.yml`) or host operational scripts (`scripts/apps/<app_id>/deploy-cindypawford-com.sh`) detect the push, stage the platform shell into `_platform/`, compile TypeScript, and execute `npx sst deploy`.
   - The agent cannot alter its own deployment machinery, CDN caches, or serverless routing rules.
