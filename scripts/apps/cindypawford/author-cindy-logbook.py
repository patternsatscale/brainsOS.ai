#!/usr/bin/env python3
"""
Project Titan: Autonomous Cindy Logbook Authoring Pipeline Tool
Ticket #129: Equips Cindy Pawford and sub-agents to author and commit structured
declassified operational records, incident telemetry, and CIP proposals to archive/logbook.json.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

def find_repo_root():
    d = os.path.abspath(os.path.dirname(__file__))
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, "config", "agents.yaml")) or os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

REPO_ROOT = find_repo_root()
ARCHIVE_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "archive")
LOGBOOK_JSON = os.path.join(ARCHIVE_DIR, "logbook.json")
BUILD_SCRIPT = os.path.join(REPO_ROOT, "scripts", "apps", "cindypawford", "build-archive-portal.py")

def parse_args():
    parser = argparse.ArgumentParser(description="Author a declassified logbook chronicle entry.")
    parser.add_argument("--title", required=True, help="Chronicle headline")
    parser.add_argument("--description", required=True, help="Operational summary or narrative")
    parser.add_argument("--category", choices=["dispatch", "code", "telecom"], default="dispatch", help="Log category")
    parser.add_argument("--badge", default="OPERATIONAL DROP", help="Tag badge text")
    parser.add_argument("--badge-type", choices=["primary", "secondary", "error"], default="secondary", help="Badge visual style")
    parser.add_argument("--peak-players", help="Incident metric: peak players")
    parser.add_argument("--packet-jitter", help="Incident metric: packet jitter")
    parser.add_argument("--failover-time", help="Incident metric: failover time")
    parser.add_argument("--hex-dump", help="Raw hex telemetry dump")
    parser.add_argument("--proof-of-bark", help="Proposal proof of bark percentage")
    parser.add_argument("--dry-run", action="store_true", help="Simulate authoring without writing")
    return parser.parse_args()

def main():
    args = parse_args()

    if not os.path.exists(LOGBOOK_JSON):
        logbook = {
            "protocol": "1984.7",
            "classification": "ERA ARCHIVE // IMMUTABLE VAULT // PROTOCOL 1984.7",
            "total_entries": 0,
            "entries": []
        }
    else:
        with open(LOGBOOK_JSON, "r", encoding="utf-8") as f:
            logbook = json.load(f)

    entries = logbook.get("entries", [])
    entry_num = len(entries) + 1
    now = datetime.datetime.now(datetime.timezone.utc)
    date_display = now.strftime("%b %d, %Y %H:%M:%S UTC").upper()

    entry = {
        "id": f"ENTRY #{entry_num:03d}",
        "entry_num": entry_num,
        "timestamp": now.isoformat(),
        "date_display": date_display,
        "category": args.category,
        "badge": args.badge,
        "badge_type": args.badge_type,
        "title": args.title,
        "description": args.description
    }

    if args.peak_players or args.packet_jitter or args.failover_time:
        entry["incident_metrics"] = {
            "peak_players": args.peak_players or "1,200",
            "packet_jitter": args.packet_jitter or "42 ms",
            "failover_time": args.failover_time or "0.15 s"
        }
        entry["footer"] = {
            "snapshot": f"INCIDENT_DUMP_{entry_num:03d}.TAR",
            "status": "TELEMETRY SECURED"
        }

    if args.hex_dump:
        entry["telemetry"] = {
            "sig": f"SIG: MERKLE_ROOT_{entry_num:03d}",
            "block": f"BLOCK #{entry_num:08d}",
            "hex_dump": args.hex_dump,
            "hash": f"0x{os.urandom(8).hex()}",
            "status": "AUTONOMOUS LOOP: ENGAGED"
        }

    if args.proof_of_bark:
        entry["proposal"] = {
            "prompt_lineage": "CIP_SYNTHESIS_V1",
            "proof_of_bark": args.proof_of_bark,
            "bars": [
                {"color": "secondary-container", "pct": 85},
                {"color": "primary-container", "pct": 14},
                {"color": "error", "pct": 1}
            ]
        }
        entry["footer"] = {
            "contract": f"0x{os.urandom(8).hex()}",
            "status": "CONSENSUS RATIFIED"
        }

    if args.dry_run:
        print("[DRY-RUN] Simulated authored entry:")
        print(json.dumps(entry, indent=2))
        return 0

    entries.append(entry)
    logbook["total_entries"] = len(entries)
    logbook["entries"] = entries

    with open(LOGBOOK_JSON, "w", encoding="utf-8") as f:
        json.dump(logbook, f, indent=2)

    print(f"[SUCCESS] Authored Entry #{entry_num:03d} to {LOGBOOK_JSON}.")

    # Compile portal
    if os.path.exists(BUILD_SCRIPT):
        res = subprocess.run([sys.executable, BUILD_SCRIPT], capture_output=True, text=True)
        if res.returncode == 0:
            print("[SUCCESS] Digital Museum Portal recompiled with newly authored chronicle.")
        else:
            print(f"[ERROR] Failed to compile portal: {res.stderr}")
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
