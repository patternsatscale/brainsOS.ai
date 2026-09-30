# brainsOS Data Plane Backup & Restore Harness

This directory contains standalone, self-governing backup and restoration utilities for the brainsOS data repository. These scripts operate autonomously on the surrounding data plane without requiring the platform repository (`brainsOS.ai`).

---

## 1. Creating a Point-in-Time Backup

To create a timestamped, gzip-compressed archive of all data planes:
```bash
./backup.sh
```

### Options:
- `--list`, `-l`: List all available backup archives with file sizes and timestamps.
- `--retention <N>`: Set the maximum number of archives to retain (default: 14). Older backups beyond this threshold are automatically pruned.
- `--help`, `-h`: Show help documentation.

### Data Planes Archived:
- `agent_memories/`: Open Knowledge Format (OKF) Markdown files.
- `souls/`: Centralized agent personas and dot-namespaced sub-agent prompts.
- `settings/`: Multi-agent fleet manifests (`agents.yaml`, `runners.yaml`).
- `agent_workspaces/`: Per-agent sandboxes, scratchpads, and local tools.
- `agent_apps/`: Untrusted agent-authored application canvases (e.g. Cindy Pawford site).
- `comms/`: Email maildirs, spool, and SOGo groupware state.
- `control_plane/litellm_db`: LiteLLM PostgreSQL database with virtual keys and model aliases.

---

## 2. Restoring from a Backup

To restore data planes from a backup archive:
```bash
# Restore from a specific archive
./restore.sh brainsos_data_YYYYMMDD_HHMMSS.tar.gz

# Restore from the most recent archive
./restore.sh latest
```

### Options:
- `--dry-run`: Inspect archive contents without modifying live files.
- `--force`, `-f`: Bypass the interactive confirmation prompt.
- `--no-snapshot`: Skip the automated pre-restore safety backup.
- `--help`, `-h`: Show help documentation.

---

## 3. Disaster Recovery & Migration

To migrate this fleet to another machine or a fresh ASUS Ascent GX10 appliance:
1. Clone this repository (or copy the `backups/brainsos_data_*.tar.gz` archive).
2. Run `./restore.sh <archive>`.
3. In `brainsOS.ai`, configure `BRAINSOS_DATA_DIR=/path/to/this-repo` in `.env` and run `make setup`.
