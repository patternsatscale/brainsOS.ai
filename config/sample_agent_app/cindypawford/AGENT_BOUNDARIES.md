# Cindy Pawford: Autonomous Agent Boundary & Operating Guardrails

This document establishes the mandatory operational boundaries and permissions for autonomous agents working on **Cindy Pawford** (`data/agent_apps/cindypawford/`).

---

## 1. Permitted Scope of Work

Autonomous agents operating on Cindy Pawford have write access strictly to the web canvas directory:
- **Allowed Path**: `data/agent_apps/cindypawford/site/**` (mounted into the agent container as `/app/html/`).
- **Permitted File Types**: HTML (`.html`), CSS (`.css`), client-side JavaScript (`.js`), and static media assets (`.svg`, `.png`, `.jpg`, `.webp`).
- **Development Goal**: Maintain and evolve the Cindy Pawford web atelier, enhance UI components, implement responsive styling, and author interactive features.

---

## 2. Forbidden Directories & Files

Autonomous agents are strictly forbidden from inspecting, modifying, moving, or deleting the following paths:

| Forbidden Target | Location | Rationale |
| :--- | :--- | :--- |
| **Pipeline & IaC** | `pipeline/**`, `sst.config.ts`, `*.ts` | Host-executed AWS infrastructure. Isolated from container mounts. |
| **Protected Subpaths** | `site/.github/**` | Read-only mount. Agent cannot alter CI/CD actions or deployment triggers. |
| **Platform Shell** | `site/_platform/**` | Injected by host deployer. Contains closed Shadow DOM bridge. |
| **Docker & System Configs** | `docker/**`, `config/**`, `scripts/**` | Host-level daemon, reverse proxy, and fleet lifecycle files. |
| **Root Environment Files** | `.env`, `.env.*` | Secret storage; strictly protected under Rule 5. |

---

## 3. Autonomous Deployment Protocol

1. **Local Canvas Modification**:
   - Write all code changes directly to `/app/html/` (`data/agent_apps/cindypawford/site/`).
   - Validate HTML5 semantic correctness, CSS styling, and client-side JavaScript in browser or via local test suites.

2. **Git Commit & Egress**:
   - Stage changes using `git add` within the canvas git repository.
   - Commit changes with descriptive messages adhering to project format.
   - Push to branch `main` via `git push origin main`. Outbound git traffic routes through `brainsos-net-egress-proxy:8082`, which injects the authenticated egress token in transit.

3. **Blind Deployment & CDN Invalidation**:
   - Upstream GitHub Actions (`.github/workflows/deploy-sst.yml`) and host deployment scripts automatically trigger on commit detection.
   - Host infrastructure stages `_platform/shell.js` and `_platform/config.js`, verifies TypeScript types, compiles CloudFront distributions, invalidates CDN edge caches, and publishes live to [cindypawford.com](https://cindypawford.com).
   - **Do not attempt to execute manual AWS CLI commands or SST deploy commands from inside the agent container.**
