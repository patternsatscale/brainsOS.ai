"""Command-line interface for brainsOS appliance operations."""

import argparse
import json
import sys
from typing import Optional, Sequence

from .builder import build_ami, check_aws_context, validate_packer_templates
from .inspector import audit_host_hardening, inspect_firstboot_status, query_imdsv2_metadata


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brainsos-appliance",
        description="brainsOS: Appliance Packaging, Packer Pipeline & Cloud-Init Lifecycle Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Appliance subcommands")

    # validate
    subparsers.add_parser(
        "validate", help="Validate Packer HCL templates and plugins"
    )

    # build
    build_p = subparsers.add_parser(
        "build", help="Build or simulate brainsOS ARM64 golden AMI"
    )
    build_p.add_argument(
        "--region",
        default="us-east-1",
        help="Target AWS Region (default: us-east-1)",
    )
    build_p.add_argument(
        "--instance-type",
        default="c7g.xlarge",
        help="Packer builder EC2 instance type (default: c7g.xlarge)",
    )
    build_p.add_argument(
        "--volume-size",
        type=int,
        default=50,
        help="Root EBS volume size in GB (default: 50)",
    )
    build_p.add_argument(
        "--publish-community",
        action="store_true",
        help="Publish AMI publicly at build time (prefer --promote after rehearsal)",
    )
    build_p.add_argument(
        "--ref",
        default=None,
        help="Git tag/branch/commit to bake (default: latest v* tag)",
    )
    build_p.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit building while the working tree has local changes",
    )
    build_p.add_argument(
        "--promote",
        metavar="AMI_ID",
        default=None,
        help="Make an existing private AMI public (Block Public Access pre-flight)",
    )
    build_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage and scan the artifact without launching EC2 instances",
    )

    # status
    status_p = subparsers.add_parser(
        "status", help="Display appliance initialization and runtime status"
    )
    status_p.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON",
    )

    # audit
    audit_p = subparsers.add_parser(
        "audit", help="Audit appliance host hardening posture"
    )
    audit_p.add_argument(
        "--json",
        action="store_true",
        help="Output audit as JSON",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "validate":
        print("[INFO] Validating Packer ARM64 AMI templates...")
        success, output = validate_packer_templates()
        if success:
            print(f"[SUCCESS] {output or 'The configuration is valid.'}")
            return 0
        else:
            print(f"[ERROR] Validation failed:\n{output}", file=sys.stderr)
            return 1

    elif args.command == "build":
        print(f"[INFO] Initiating brainsOS ARM64 AMI build (region: {args.region})...")
        aws_ctx = check_aws_context()
        print(f"[INFO] AWS Context: region={aws_ctx['region']}, profile={aws_ctx['aws_profile']}")
        success, msg, cmd = build_ami(
            region=args.region,
            publish_community=args.publish_community,
            instance_type=args.instance_type,
            volume_size=args.volume_size,
            dry_run=args.dry_run,
            ref=args.ref,
            allow_dirty=args.allow_dirty,
            promote=args.promote,
        )
        if success:
            print(f"[SUCCESS] {msg}")
            return 0
        else:
            print(f"[ERROR] Build failed: {msg}", file=sys.stderr)
            return 1

    elif args.command == "status":
        firstboot = inspect_firstboot_status()
        imds = query_imdsv2_metadata()
        status_data = {
            "firstboot": firstboot,
            "imds": imds,
        }
        if getattr(args, "json", False):
            print(json.dumps(status_data, indent=2))
        else:
            print("==================================================")
            print(" brainsOS Appliance Status")
            print("==================================================")
            print(f" Initialized:       {firstboot['initialized']}")
            print(f" Timestamp:         {firstboot.get('initialization_timestamp')}")
            print(f" .env file exists:  {firstboot['env_file_exists']}")
            print(f" .env permissions:  {firstboot.get('env_permissions')} (secure: {firstboot['env_permissions_secure']})")
            print("--------------------------------------------------")
            print(f" IMDSv2 Available:  {imds['imds_available']}")
            if imds["imds_available"]:
                print(f" Instance ID:       {imds['instance_id']}")
                print(f" Public Hostname:   {imds['public_hostname']}")
                print(f" Local IPv4:        {imds['local_ipv4']}")
            print("==================================================")
        return 0

    elif args.command == "audit":
        audit_data = {
            "host_hardening": audit_host_hardening(),
            "firstboot": inspect_firstboot_status(),
        }
        if getattr(args, "json", False):
            print(json.dumps(audit_data, indent=2))
        else:
            print("==================================================")
            print(" brainsOS Appliance Host Hardening Audit")
            print("==================================================")
            hh = audit_data["host_hardening"]
            print(f" Docker Logging:    {hh.get('docker_daemon_logging')}")
            print(f" Journald Drop-in:  {hh.get('journald_dropin_present')}")
            print(f" Logrotate Present: {hh.get('logrotate_present')}")
            print(f" UFW Firewall:      {hh.get('ufw')}")
            print("==================================================")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
