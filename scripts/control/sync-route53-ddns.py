#!/usr/bin/env python3
"""brainsOS Route 53 Dynamic Fleet DNS Synchronizer (Ticket #373).

Idempotently registers or updates an AWS Route 53 A record (TTL=60) for an EC2
appliance instance using ambient IMDSv2 IAM instance-role credentials via boto3.

Guards against accidental cross-instance DNS hijacking using a companion TXT
ownership record (`_brainsos-owner.<fqdn>` -> `"instance-id=<id>"`). If the
attached IAM role strictly permits `route53:ChangeResourceRecordSets` without
`route53:ListResourceRecordSets`, gracefully falls back to direct UPSERT.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
from typing import Any, Optional, Tuple

FQDN_RE = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
ZONE_ID_RE = re.compile(r"^Z[A-Z0-9]{4,32}$")


def normalize_fqdn(raw: str) -> str:
    val = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        if val.startswith(prefix):
            val = val[len(prefix) :]
    val = val.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    return val


def normalize_zone_id(raw: str) -> str:
    val = (raw or "").strip()
    if "hostedzone/" in val:
        val = val.rsplit("hostedzone/", 1)[-1]
    return val.strip("/")


def validate_inputs(domain: str, ip: str, zone_id: str) -> Tuple[str, str, str]:
    fqdn = normalize_fqdn(domain)
    if not fqdn or not FQDN_RE.match(fqdn):
        raise ValueError(f"Invalid FQDN: {domain!r}")

    try:
        addr = ipaddress.IPv4Address((ip or "").strip())
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 address: {ip!r}") from exc

    clean_zone = normalize_zone_id(zone_id)
    if clean_zone and not ZONE_ID_RE.match(clean_zone):
        raise ValueError(f"Invalid Route 53 Hosted Zone ID: {zone_id!r}")

    return fqdn, str(addr), clean_zone


def discover_zone_id(route53_client: Any, fqdn: str) -> str:
    """Walk parent domain labels to auto-discover a matching public Route 53 Hosted Zone."""
    labels = fqdn.split(".")
    for idx in range(len(labels) - 1):
        candidate = ".".join(labels[idx:]) + "."
        resp = route53_client.list_hosted_zones_by_name(DNSName=candidate, MaxItems="10")
        for zone in resp.get("HostedZones", []):
            zname = (zone.get("Name") or "").lower()
            is_private = bool((zone.get("Config") or {}).get("PrivateZone", False))
            if zname == candidate and not is_private:
                return normalize_zone_id(zone["Id"])
    raise RuntimeError(
        f"No public Route 53 Hosted Zone found matching {fqdn!r}. "
        "Supply BRAINSOS_ROUTE53_ZONE_ID explicitly."
    )


def inspect_existing_records(
    route53_client: Any,
    zone_id: str,
    fqdn: str,
) -> Tuple[Optional[str], Optional[str], bool]:
    """Return (existing_ip, existing_owner_instance_id, list_succeeded)."""
    a_name = f"{fqdn}."
    txt_name = f"_brainsos-owner.{fqdn}."
    existing_ip: Optional[str] = None
    existing_owner: Optional[str] = None

    try:
        resp_a = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id,
            StartRecordName=a_name,
            StartRecordType="A",
            MaxItems="5",
        )
        for rr in resp_a.get("ResourceRecordSets", []):
            if (rr.get("Name") or "").lower() == a_name and rr.get("Type") == "A":
                recs = rr.get("ResourceRecords") or []
                if recs:
                    existing_ip = recs[0].get("Value")
                break

        resp_txt = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id,
            StartRecordName=txt_name,
            StartRecordType="TXT",
            MaxItems="5",
        )
        for rr in resp_txt.get("ResourceRecordSets", []):
            if (rr.get("Name") or "").lower() == txt_name and rr.get("Type") == "TXT":
                for rec in rr.get("ResourceRecords") or []:
                    raw_val = (rec.get("Value") or "").strip().strip('"')
                    for token in raw_val.split():
                        if token.startswith("instance-id="):
                            existing_owner = token.split("=", 1)[1].strip()
                            break
                break
        return existing_ip, existing_owner, True
    except Exception as exc:
        err_code = ""
        if hasattr(exc, "response") and isinstance(getattr(exc, "response"), dict):
            err_code = str(exc.response.get("Error", {}).get("Code", ""))
        if "AccessDenied" in err_code or "AccessDenied" in str(exc):
            return None, None, False
        raise


def sync_route53_record(
    route53_client: Any,
    domain: str,
    ip: str,
    zone_id: str = "",
    instance_id: str = "",
    ttl: int = 60,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronize A (+ TXT ownership) record in Route 53."""
    fqdn, clean_ip, clean_zone = validate_inputs(domain, ip, zone_id)
    clean_instance = (instance_id or "").strip()

    if dry_run:
        return {
            "status": "dry_run",
            "changed": False,
            "domain": fqdn,
            "ip": clean_ip,
            "zone_id": clean_zone or "auto-discover",
            "instance_id": clean_instance,
            "ttl": ttl,
        }

    if not clean_zone:
        clean_zone = discover_zone_id(route53_client, fqdn)

    existing_ip, existing_owner, list_ok = inspect_existing_records(route53_client, clean_zone, fqdn)

    if (
        list_ok
        and existing_owner
        and clean_instance
        and existing_owner != clean_instance
        and not force
    ):
        raise PermissionError(
            f"DNS record {fqdn!r} is already owned by EC2 instance {existing_owner!r} "
            f"(current instance: {clean_instance!r}). Refusing to overwrite without --force / BRAINSOS_ROUTE53_FORCE=true."
        )

    if list_ok and existing_ip == clean_ip and (not clean_instance or existing_owner == clean_instance):
        return {
            "status": "unchanged",
            "changed": False,
            "domain": fqdn,
            "ip": clean_ip,
            "zone_id": clean_zone,
            "instance_id": clean_instance,
            "ttl": ttl,
        }

    changes: list[dict[str, Any]] = [
        {
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": fqdn,
                "Type": "A",
                "TTL": int(ttl),
                "ResourceRecords": [{"Value": clean_ip}],
            },
        }
    ]
    if clean_instance:
        changes.append(
            {
                "Action": "UPSERT",
                "ResourceRecordSet": {
                    "Name": f"_brainsos-owner.{fqdn}",
                    "Type": "TXT",
                    "TTL": int(ttl),
                    "ResourceRecords": [{"Value": f'"instance-id={clean_instance}"'}],
                },
            }
        )

    resp = route53_client.change_resource_record_sets(
        HostedZoneId=clean_zone,
        ChangeBatch={
            "Comment": f"brainsOS dynamic DNS sync ({clean_instance or 'appliance'})",
            "Changes": changes,
        },
    )
    change_id = (resp.get("ChangeInfo") or {}).get("Id", "")
    return {
        "status": "updated",
        "changed": True,
        "domain": fqdn,
        "ip": clean_ip,
        "previous_ip": existing_ip,
        "zone_id": clean_zone,
        "instance_id": clean_instance,
        "ttl": ttl,
        "change_id": change_id,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="brainsOS Route 53 Dynamic DNS Synchronizer")
    parser.add_argument("--domain", default=os.environ.get("BRAINSOS_DOMAIN", ""), help="Target FQDN (e.g. alice.demo.infotechlabs.io)")
    parser.add_argument("--ip", default=os.environ.get("BRAINSOS_PUBLIC_IPV4", ""), help="Public IPv4 address")
    parser.add_argument("--zone-id", default=os.environ.get("BRAINSOS_ROUTE53_ZONE_ID", ""), help="Route 53 Hosted Zone ID (Z...)")
    parser.add_argument("--instance-id", default=os.environ.get("BRAINSOS_INSTANCE_ID", ""), help="EC2 Instance ID for TXT ownership lock")
    parser.add_argument("--ttl", type=int, default=int(os.environ.get("BRAINSOS_ROUTE53_TTL", "60")), help="DNS record TTL in seconds (default: 60)")
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.environ.get("BRAINSOS_ROUTE53_FORCE", "").strip().lower() in ("true", "1", "yes"),
        help="Override TXT ownership lock if owned by a different instance-id",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without calling Route 53")
    parser.add_argument("--json", action="store_true", help="Emit JSON result")
    args = parser.parse_args(argv)

    try:
        client = None
        if not args.dry_run:
            import boto3  # type: ignore

            client = boto3.client("route53")

        result = sync_route53_record(
            route53_client=client,
            domain=args.domain,
            ip=args.ip,
            zone_id=args.zone_id,
            instance_id=args.instance_id,
            ttl=args.ttl,
            force=args.force,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(result))
        else:
            print(
                f"[Route53 DDNS] {result['status'].upper()}: {result['domain']} -> {result['ip']} "
                f"(zone={result['zone_id']}, ttl={result['ttl']}s)"
            )
        return 0
    except PermissionError as exc:
        if args.json:
            print(json.dumps({"status": "collision", "error": str(exc)}))
        else:
            print(f"[Route53 DDNS] COLLISION: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}))
        else:
            print(f"[Route53 DDNS] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
