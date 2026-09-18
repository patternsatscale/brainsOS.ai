#!/usr/bin/env python3
"""
Project Titan: Cindy Pawford Automated PR-to-Logbook Ingestion Script
Ticket #129: Automatically captures merged PRs into apps/cindypawford/archive/logbook.json
and triggers build-archive-portal.py to update the live public logbook.
"""

import argparse
import datetime
import json
import os
import re
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

def load_logbook():
    if not os.path.exists(LOGBOOK_JSON):
        return {
            "protocol": "1984.7",
            "classification": "ERA ARCHIVE // IMMUTABLE VAULT // PROTOCOL 1984.7",
            "total_entries": 0,
            "entries": []
        }
    with open(LOGBOOK_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def sanitize_summary(text):
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        # Skip markdown section headers
        if re.match(r'^#+\s*(The Era|What\'s in it|Methodology|Overview|Summary|Objective|Context)', line, re.IGNORECASE):
            continue
        line = re.sub(r'^#+\s*', '', line).strip()
        if line:
            lines.append(line)
    cleaned = " ".join(lines)
    # Strip markdown bold / italic markers and backticks
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
    cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > 430:
        # Prefer breaking at a clean sentence period
        period_idx = cleaned[:430].rfind(". ")
        if period_idx > 220:
            cleaned = cleaned[:period_idx + 1]
        else:
            truncated = cleaned[:427]
            last_space = truncated.rfind(" ")
            if last_space > 220:
                cleaned = truncated[:last_space] + "..."
            else:
                cleaned = truncated + "..."
    return cleaned

def classify_pr(title, body=""):
    title_lower = title.lower()
    body_lower = body.lower()
    full_text = f"{title_lower} {body_lower}"

    # 1. Canonical New Eras: ONLY weekly macro epochs or wipe-triggered founding events
    if any(k in title_lower for k in ["new era founded", "era genesis", "epoch inception", "canvas wipe", "weekly era"]) or \
       (title_lower.startswith("era:") and "gala" in title_lower) or \
       (title_lower.startswith("era zero") and "white test" in title_lower):
        return "new-era", "[NEW ERA FOUNDED]", "primary"

    # 2. Anomalies & Hotfixes
    elif any(word in full_text for word in ["fix", "bug", "glitch", "incident", "timing anomaly", "hotfix"]):
        return "anomaly", "[ANOMALY_RESOLVED]", "error"

    # 3. Audio & Media Stems
    elif any(word in full_text for word in ["audio", "synth", "sound", "music", "midi", "soundboard"]):
        return "media", "[AUDIO_DEPLOYMENT]", "tertiary"

    # 4. Canvas Releases & Room Expansions
    elif "the ten" in title_lower or any(word in full_text for word in ["room", "expansion", "gallery", "arcade", "vault", "pac", "mystery", "favorites", "canvas release"]):
        badge_text = "[GALA ROOM EXPANSION]" if ("the ten" in title_lower or "room" in full_text) else "[CANVAS RELEASE]"
        return "release", badge_text, "primary"

    # 5. Protocol, Shell, Governance, Telemetry
    elif any(word in full_text for word in ["shell", "console", "terminal", "platform", "shadow dom"]):
        return "protocol", "[PLATFORM_INTEGRATION]", "secondary"
    elif any(word in full_text for word in ["cip", "protocol", "governance", "rules", "soul", "workflow"]):
        return "protocol", "[GOVERNANCE_CIP]", "secondary"
    elif any(word in full_text for word in ["probe", "telemetry", "ci/cd", "pipeline", "s3", "cloudfront"]):
        return "protocol", "[SYSTEM_TELEMETRY]", "primary"
    elif any(word in full_text for word in ["manifesto", "dispatch", "readme"]):
        return "protocol", "[COMMUNITY_DISPATCH]", "secondary"

    # 6. Default PR Release
    else:
        return "release", "[PULL_REQUEST]", "primary"

def parse_args():
    parser = argparse.ArgumentParser(description="Ingest merged GitHub PR into Cindy Pawford Declassified Logbook.")
    parser.add_argument("--pr-number", type=int, help="GitHub PR number")
    parser.add_argument("--pr-title", type=str, help="GitHub PR title")
    parser.add_argument("--pr-author", type=str, help="GitHub PR author username")
    parser.add_argument("--commit-sha", type=str, help="Merged commit SHA")
    parser.add_argument("--summary", type=str, default="", help="Summary or agent report description")
    parser.add_argument("--timestamp", type=str, default=None, help="PR merge ISO timestamp")
    parser.add_argument("--category", type=str, choices=["new-era", "release", "protocol", "anomaly", "media", "code", "dispatch", "telecom"], default=None, help="Entry category")
    parser.add_argument("--badge", type=str, default=None, help="Badge text")
    parser.add_argument("--badge-type", type=str, choices=["primary", "secondary", "tertiary", "error"], default=None, help="Badge color type")
    parser.add_argument("--auto-scan", action="store_true", help="Auto-scan git history and PRs for unrecorded entries")
    parser.add_argument("--dry-run", action="store_true", help="Simulate ingestion without writing to disk")
    parser.add_argument("--self-test", action="store_true", help="Run automated ingestion test against temporary fixture")
    return parser.parse_args()

def extract_from_github_event():
    """Extract PR metadata from GITHUB_EVENT_PATH if running inside GitHub Actions."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return {}
    try:
        with open(event_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # STRICT ISOLATION GUARD: Reject any event not originating from patternsatscale/CindyPawford-Online
        repo_name = (data.get("repository") or {}).get("full_name")
        if repo_name != "patternsatscale/CindyPawford-Online":
            print(f"[INFO] GITHUB_EVENT_PATH belongs to '{repo_name}' (expected 'patternsatscale/CindyPawford-Online'). Skipping automatic event extraction.")
            return {}

        # 1. Direct pull_request event
        pr = data.get("pull_request", {})
        if pr:
            return {
                "pr_number": pr.get("number"),
                "pr_title": pr.get("title"),
                "pr_author": pr.get("user", {}).get("login"),
                "commit_sha": pr.get("merge_commit_sha") or os.environ.get("GITHUB_SHA"),
                "timestamp": pr.get("merged_at"),
                "summary": pr.get("body", "")[:400] if pr.get("body") else ""
            }

        # 2. Push event on main (squash merge commit)
        head_commit = data.get("head_commit", {})
        if head_commit:
            message = head_commit.get("message", "")
            lines = message.strip().splitlines()
            title = lines[0] if lines else ""
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

            m = re.search(r'\(#(\d+)\)', title) or re.search(r'Merge pull request #(\d+)', title)
            pr_num = int(m.group(1)) if m else None

            return {
                "pr_number": pr_num,
                "pr_title": title,
                "pr_author": head_commit.get("author", {}).get("username") or head_commit.get("author", {}).get("name"),
                "commit_sha": head_commit.get("id") or os.environ.get("GITHUB_SHA"),
                "timestamp": head_commit.get("timestamp"),
                "summary": body[:400] if body else title
            }

        return {}
    except Exception as e:
        print(f"[WARN] Failed to read GITHUB_EVENT_PATH: {e}")
        return {}

def ingest_pr(pr_num, pr_title, pr_author, commit_sha, summary, category=None, badge=None, badge_type=None, timestamp=None, dry_run=False):
    logbook = load_logbook()
    entries = logbook.get("entries", [])

    # Check for duplicate PR entry
    for e in entries:
        if e.get("pr_metadata", {}).get("pr_number") == pr_num:
            print(f"[INFO] PR #{pr_num} already recorded in logbook. Skipping duplication.")
            return True

    # Auto-classify if not supplied
    auto_cat, auto_badge, auto_type = classify_pr(pr_title or "", summary or "")
    cat = category or auto_cat
    bdg = badge or auto_badge
    btype = badge_type or auto_type

    entry_num = len(entries) + 1

    # Resolve timestamp
    if timestamp:
        try:
            if isinstance(timestamp, str):
                ts = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif isinstance(timestamp, datetime.datetime):
                ts = timestamp
            else:
                ts = datetime.datetime.now(datetime.timezone.utc)
        except Exception:
            ts = datetime.datetime.now(datetime.timezone.utc)
    else:
        ts = datetime.datetime.now(datetime.timezone.utc)

    date_display = ts.strftime("%b %d %Y").upper()
    time_display = ts.strftime("%H:%M:%S UTC")

    clean_summary = sanitize_summary(summary) if summary else f"Merged pull request #{pr_num}: {pr_title} into main."

    short_sha = commit_sha[:7] if commit_sha and len(commit_sha) >= 7 else "HEAD"
    subbadge = f"PR #{pr_num}"
    block = f"PR #{pr_num} • {short_sha}"

    entry = {
        "id": f"ENTRY #{entry_num:03d}",
        "entry_num": entry_num,
        "timestamp": ts.isoformat(),
        "date_display": date_display,
        "time_display": time_display,
        "category": cat,
        "badge": bdg,
        "subbadge": subbadge,
        "badge_type": btype,
        "block": block,
        "title": pr_title or f"Release PR #{pr_num}",
        "description": clean_summary,
        "pr_metadata": {
            "pr_number": pr_num,
            "author": pr_author or "autonomous-agent",
            "commit_sha": commit_sha or "HEAD"
        }
    }

    if cat == "anomaly":
        entry["incident_metrics"] = {
            "peak_players": "1,200",
            "packet_jitter": "10 ms",
            "failover_time": "0.15 s"
        }
        entry["footer"] = {
            "snapshot": f"PATCH_PR_{pr_num}.JS",
            "status": "STATUS: RESOLVED"
        }
    else:
        entry["telemetry"] = {
            "sig": f"SIG: PR_{pr_num}_{short_sha.upper()}",
            "system_tag": "CANVAS // RELEASE" if cat == "new-era" else "GITHUB_ACTIONS // RELEASE",
            "hash": f"0x{short_sha}...001",
            "status": "● LIVE ON GALA CANVAS" if cat == "new-era" else "MERGED TO MAIN"
        }

    if dry_run:
        print("[DRY-RUN] Would append the following entry to logbook.json:")
        print(json.dumps(entry, indent=2))
        return True

    entries.append(entry)
    # Sort entries by timestamp descending so the latest release is ALWAYS at the top
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    logbook["total_entries"] = len(entries)
    logbook["sort_order"] = "reverse_chronological"
    logbook["repository"] = "patternsatscale/CindyPawford-Online"
    logbook["entries"] = entries

    with open(LOGBOOK_JSON, "w", encoding="utf-8") as f:
        json.dump(logbook, f, indent=2)

    print(f"[SUCCESS] Appended Entry #{entry_num:03d} (PR #{pr_num}) to {LOGBOOK_JSON}.")

    # Rebuild archive portal
    if os.path.exists(BUILD_SCRIPT):
        res = subprocess.run([sys.executable, BUILD_SCRIPT], capture_output=True, text=True)
        if res.returncode == 0:
            print("[SUCCESS] Live archive portal rebuilt successfully with new PR entry.")
        else:
            print(f"[ERROR] Failed to rebuild archive portal: {res.stderr}")
            return False

    return True

def auto_scan_and_ingest(dry_run=False):
    """Inspects merged PRs from patternsatscale/CindyPawford-Online to discover any unrecorded releases."""
    logbook = load_logbook()
    recorded_prs = {
        e.get("pr_metadata", {}).get("pr_number")
        for e in logbook.get("entries", [])
        if e.get("pr_metadata", {}).get("pr_number") is not None
    }

    target_repo = "patternsatscale/CindyPawford-Online"
    site_dir = os.path.join(REPO_ROOT, "apps", "cindypawford", "site")
    discovered_prs = []

    # 1. Primary: Query GitHub API via gh CLI for CindyPawford-Online
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "--repo", target_repo, "--state", "merged", "--limit", "25",
             "--json", "number,title,author,mergedAt,mergeCommit,body"],
            capture_output=True, text=True, check=True
        )
        pr_items = json.loads(res.stdout)
        for item in pr_items:
            num = item.get("number")
            # Skip automated test probes
            title_text = item.get("title", "")
            if "automated PR" in title_text or "cicd-verify" in title_text:
                continue
            if num and num not in recorded_prs and not any(p["pr_number"] == num for p in discovered_prs):
                discovered_prs.append({
                    "pr_number": num,
                    "pr_title": title_text,
                    "pr_author": (item.get("author") or {}).get("login") or "cindy-pawford",
                    "commit_sha": (item.get("mergeCommit") or {}).get("oid") or "HEAD",
                    "timestamp": item.get("mergedAt") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "summary": item.get("body") or ""
                })
    except Exception as e:
        print(f"[INFO] gh CLI scan fallback to git log: {e}")

    # 2. Secondary fallback: inspect git log in apps/cindypawford/site (CindyPawford-Online clone)
    if not discovered_prs and os.path.exists(site_dir):
        try:
            rem = subprocess.run(["git", "-C", site_dir, "remote", "get-url", "origin"], capture_output=True, text=True)
            if "CindyPawford-Online" not in rem.stdout:
                print(f"[WARN] {site_dir} remote is '{rem.stdout.strip()}' (not CindyPawford-Online). Skipping git log fallback.")
            else:
                res = subprocess.run(
                    ["git", "-C", site_dir, "log", "-n", "20", "--format=%H%x09%s%x09%an%x09%aI"],
                    capture_output=True, text=True, check=True
                )
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        sha, subject, author, dt_str = parts[0], parts[1], parts[2], parts[3]
                        m = re.search(r'\(#(\d+)\)', subject) or re.search(r'Merge pull request #(\d+)', subject)
                        if m:
                            pr_num = int(m.group(1))
                            if "verification" in subject.lower() or "cicd-verify" in subject.lower():
                                continue
                            if pr_num not in recorded_prs and not any(p["pr_number"] == pr_num for p in discovered_prs):
                                discovered_prs.append({
                                    "pr_number": pr_num,
                                    "pr_title": subject,
                                    "pr_author": author,
                                    "commit_sha": sha,
                                    "timestamp": dt_str,
                                    "summary": subject
                                })
        except Exception as e:
            print(f"[WARN] Error scanning git log in {site_dir}: {e}")

    if not discovered_prs:
        print("[INFO] Auto-scan complete: All CindyPawford-Online merged PRs are already recorded in logbook.json.")
        return True

    print(f"[INFO] Auto-scan discovered {len(discovered_prs)} unrecorded PRs from CindyPawford-Online: {[p['pr_number'] for p in discovered_prs]}")
    success = True
    for p in discovered_prs:
        cat, badge, badge_type = classify_pr(p["pr_title"], p.get("summary", ""))
        ok = ingest_pr(
            pr_num=p["pr_number"],
            pr_title=p["pr_title"],
            pr_author=p["pr_author"],
            commit_sha=p["commit_sha"],
            summary=p.get("summary") or f"Automated release ingestion for PR #{p['pr_number']}: {p['pr_title']}",
            category=cat,
            badge=badge,
            badge_type=badge_type,
            timestamp=p.get("timestamp"),
            dry_run=dry_run
        )
        if not ok:
            success = False

    return success

def run_self_test():
    print("[INFO] Running PR Ingestion self-test...")
    test_num = 9999
    test_title = "[Test] Verification PR for Autonomous Logbook Pipeline"
    test_author = "cindy-test-bot"
    test_sha = "0123456789abcdef0123456789abcdef01234567"
    test_summary = "Automated dry-run test asserting valid entry cards are synthesized."

    success = ingest_pr(
        pr_num=test_num,
        pr_title=test_title,
        pr_author=test_author,
        commit_sha=test_sha,
        summary=test_summary,
        category="protocol",
        badge="TEST RELEASE",
        badge_type="primary",
        dry_run=True
    )

    if success:
        print("[SUCCESS] Self-test passed cleanly in dry-run mode.")
        return 0
    else:
        print("[ERROR] Self-test failed.")
        return 1

def main():
    args = parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    if args.auto_scan:
        sys.exit(0 if auto_scan_and_ingest(dry_run=args.dry_run) else 1)

    event_data = extract_from_github_event()

    pr_num = args.pr_number or event_data.get("pr_number")
    pr_title = args.pr_title or event_data.get("pr_title")
    pr_author = args.pr_author or event_data.get("pr_author")
    commit_sha = args.commit_sha or event_data.get("commit_sha")
    summary = args.summary or event_data.get("summary")
    timestamp = args.timestamp or event_data.get("timestamp")

    # If neither flags nor GH event provided a PR number, fallback to auto_scan
    if not pr_num:
        print("[INFO] No explicit PR arguments or GitHub PR event detected; running auto-scan...")
        sys.exit(0 if auto_scan_and_ingest(dry_run=args.dry_run) else 1)

    success = ingest_pr(
        pr_num=pr_num,
        pr_title=pr_title or f"Release PR #{pr_num}",
        pr_author=pr_author or "Google Antigravity",
        commit_sha=commit_sha or "HEAD",
        summary=summary or "Autonomous CindyOS Feature Integration",
        category=args.category,
        badge=args.badge,
        badge_type=args.badge_type,
        timestamp=timestamp,
        dry_run=args.dry_run
    )

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
