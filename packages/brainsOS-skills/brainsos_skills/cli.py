"""
Command line interface for brainsOS Agent Skills.
"""

import argparse
import sys
from pathlib import Path

from brainsos_skills.loader import (
    discover_skills_in_dir,
    load_hierarchical_skills,
    load_workspace_skills,
    sync_skills_to_workspace,
)
from brainsos_skills.models import SkillSourceType
from brainsos_skills.registry import SkillRegistry


def cmd_list(args: argparse.Namespace) -> int:
    registry = SkillRegistry()
    repo_root = Path(args.repo) if args.repo else Path.cwd()
    data_dir = Path(args.data) if args.data else None

    load_hierarchical_skills(repo_root=repo_root, data_dir=data_dir, registry=registry)

    if args.workspace:
        load_workspace_skills(Path(args.workspace), registry)

    skills = registry.list_all()
    print(f"\n📦 brainsOS Skills Catalog ({len(skills)} registered):\n")
    print(f"{'NAME':<20} {'VERSION':<10} {'SOURCE':<10} {'DESCRIPTION'}")
    print("-" * 80)
    for skill in skills:
        desc = (skill.description[:45] + "...") if len(skill.description) > 45 else skill.description
        print(f"{skill.name:<20} {skill.metadata.version:<10} {skill.source_type.value:<10} {desc}")
    print()
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target_dir = Path(args.path)
    if not target_dir.exists():
        print(f"❌ Error: Path does not exist: {target_dir}", file=sys.stderr)
        return 1

    skills = discover_skills_in_dir(target_dir)
    print(f"\n🔍 Validating skills in {target_dir} ({len(skills)} found)...\n")

    if not skills:
        print("⚠️ No SKILL.md files found.")
        return 0

    for skill in skills:
        print(f"  ✅ {skill.name:<20} (v{skill.metadata.version}) — Valid")

    print(f"\n✨ All {len(skills)} skill(s) validated successfully.\n")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    target_dir = Path(args.target)
    registry = SkillRegistry()

    if args.source:
        source_dir = Path(args.source)
        skills = discover_skills_in_dir(source_dir, source_type=SkillSourceType.CUSTOM)
        for s in skills:
            registry.register(s, overwrite=True)
    else:
        repo_root = Path(args.repo) if args.repo else Path.cwd()
        data_dir = Path(args.data) if args.data else None
        load_hierarchical_skills(repo_root=repo_root, data_dir=data_dir, registry=registry)

    written = sync_skills_to_workspace(registry, target_dir)
    print(f"\n⚡ Synced {len(written)} canonical skill(s) to {target_dir}:\n")
    for path in written:
        print(f"  -> {path}")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="brainsOS Agent Skills Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List all available skills")
    p_list.add_argument("--repo", "-r", help="Repository root path")
    p_list.add_argument("--data", "-d", help="Data directory path (defaults to $BRAINSOS_DATA_DIR/skills or data/skills)")
    p_list.add_argument("--workspace", "-w", help="Workspace root to include workspace skills from")
    p_list.set_defaults(func=cmd_list)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate a directory of skills")
    p_val.add_argument("--path", "-p", default=".agents/skills", help="Directory containing skills")
    p_val.set_defaults(func=cmd_validate)

    # sync
    p_sync = subparsers.add_parser("sync", help="Sync skills to a workspace target")
    p_sync.add_argument("--source", "-s", help="Source directory containing skills (overrides hierarchical discovery)")
    p_sync.add_argument("--repo", "-r", help="Repository root path")
    p_sync.add_argument("--data", "-d", help="Data directory path")
    p_sync.add_argument("--target", "-t", default=".agents/skills", help="Target directory to sync skills into")
    p_sync.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
