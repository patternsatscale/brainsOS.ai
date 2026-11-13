"""Tests for Route 53 Dynamic Fleet DNS Synchronizer & User-Data Routing (Ticket #373)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "control" / "sync-route53-ddns.py"
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_route53_ddns", SYNC_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRoute53Client:
    """In-memory mock of boto3 route53 client for deterministic DDNS tests."""

    def __init__(
        self,
        existing_ip: str | None = None,
        existing_owner: str | None = None,
        deny_list: bool = False,
        zones: list[dict[str, Any]] | None = None,
    ) -> None:
        self.existing_ip = existing_ip
        self.existing_owner = existing_owner
        self.deny_list = deny_list
        self.zones = zones or []
        self.changes: list[dict[str, Any]] = []

    def list_hosted_zones_by_name(self, DNSName: str, MaxItems: str = "10") -> dict[str, Any]:
        return {"HostedZones": self.zones}

    def list_resource_record_sets(
        self,
        HostedZoneId: str,
        StartRecordName: str,
        StartRecordType: str,
        MaxItems: str = "5",
    ) -> dict[str, Any]:
        if self.deny_list:
            exc = Exception("An error occurred (AccessDenied) when calling ListResourceRecordSets")
            setattr(exc, "response", {"Error": {"Code": "AccessDenied"}})
            raise exc
        rrs: list[dict[str, Any]] = []
        if StartRecordType == "A" and self.existing_ip:
            rrs.append(
                {
                    "Name": StartRecordName,
                    "Type": "A",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": self.existing_ip}],
                }
            )
        if StartRecordType == "TXT" and self.existing_owner:
            rrs.append(
                {
                    "Name": StartRecordName,
                    "Type": "TXT",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": f'"instance-id={self.existing_owner}"'}],
                }
            )
        return {"ResourceRecordSets": rrs}

    def change_resource_record_sets(
        self, HostedZoneId: str, ChangeBatch: dict[str, Any]
    ) -> dict[str, Any]:
        self.changes.append({"HostedZoneId": HostedZoneId, "ChangeBatch": ChangeBatch})
        return {"ChangeInfo": {"Id": "/change/C1234567890", "Status": "PENDING"}}


def test_sync_route53_upsert_and_idempotency():
    mod = _load_sync_module()
    client = FakeRoute53Client()

    res = mod.sync_route53_record(
        route53_client=client,
        domain="https://alice.demo.infotechlabs.io/",
        ip="54.210.11.22",
        zone_id="/hostedzone/Z0987654321DEMO",
        instance_id="i-0123456789abcdef0",
        ttl=60,
    )
    assert res["status"] == "updated"
    assert res["changed"] is True
    assert res["domain"] == "alice.demo.infotechlabs.io"
    assert res["zone_id"] == "Z0987654321DEMO"
    assert len(client.changes) == 1
    batch = client.changes[0]["ChangeBatch"]["Changes"]
    assert batch[0]["Action"] == "UPSERT"
    assert batch[0]["ResourceRecordSet"]["Name"] == "alice.demo.infotechlabs.io"
    assert batch[0]["ResourceRecordSet"]["ResourceRecords"] == [{"Value": "54.210.11.22"}]
    assert batch[1]["ResourceRecordSet"]["Name"] == "_brainsos-owner.alice.demo.infotechlabs.io"
    assert batch[1]["ResourceRecordSet"]["ResourceRecords"] == [
        {"Value": '"instance-id=i-0123456789abcdef0"'}
    ]

    # Unchanged when IP and instance_id already match
    unchanged_client = FakeRoute53Client(
        existing_ip="54.210.11.22",
        existing_owner="i-0123456789abcdef0",
    )
    res2 = mod.sync_route53_record(
        route53_client=unchanged_client,
        domain="alice.demo.infotechlabs.io",
        ip="54.210.11.22",
        zone_id="Z0987654321DEMO",
        instance_id="i-0123456789abcdef0",
    )
    assert res2["status"] == "unchanged"
    assert res2["changed"] is False
    assert len(unchanged_client.changes) == 0


def test_sync_route53_ownership_collision_and_force():
    mod = _load_sync_module()
    other_owner_client = FakeRoute53Client(
        existing_ip="3.91.10.20",
        existing_owner="i-0aaaaaaaaaaaaaaa1",
    )

    with pytest.raises(PermissionError, match="already owned by EC2 instance"):
        mod.sync_route53_record(
            route53_client=other_owner_client,
            domain="alice.demo.infotechlabs.io",
            ip="54.210.11.22",
            zone_id="Z0987654321DEMO",
            instance_id="i-0bbbbbbbbbbbbbbb2",
            force=False,
        )
    assert len(other_owner_client.changes) == 0

    # --force overrides ownership lock cleanly
    forced = mod.sync_route53_record(
        route53_client=other_owner_client,
        domain="alice.demo.infotechlabs.io",
        ip="54.210.11.22",
        zone_id="Z0987654321DEMO",
        instance_id="i-0bbbbbbbbbbbbbbb2",
        force=True,
    )
    assert forced["status"] == "updated"
    assert len(other_owner_client.changes) == 1


def test_sync_route53_minimal_iam_fallback_and_zone_discovery():
    mod = _load_sync_module()
    minimal_iam_client = FakeRoute53Client(
        deny_list=True,
        zones=[
            {
                "Id": "/hostedzone/ZINFOTECHLABS99",
                "Name": "infotechlabs.io.",
                "Config": {"PrivateZone": False},
            }
        ],
    )

    res = mod.sync_route53_record(
        route53_client=minimal_iam_client,
        domain="bob.demo.infotechlabs.io",
        ip="44.201.99.12",
        zone_id="",
        instance_id="i-0ccccccccccccccc3",
    )
    assert res["status"] == "updated"
    assert res["zone_id"] == "ZINFOTECHLABS99"
    assert len(minimal_iam_client.changes) == 1


def test_sync_route53_invalid_inputs_rejected():
    mod = _load_sync_module()
    client = FakeRoute53Client()

    with pytest.raises(ValueError, match="Invalid FQDN"):
        mod.sync_route53_record(client, domain="not_a_domain", ip="1.2.3.4", zone_id="Z123456")

    with pytest.raises(ValueError, match="Invalid IPv4"):
        mod.sync_route53_record(
            client, domain="alice.demo.infotechlabs.io", ip="999.999.1.1", zone_id="Z123456"
        )


def test_firstboot_userdata_route53_domain_and_acme_defaults(tmp_path: Path):
    """Verify firstboot.sh configures custom subdomain, ACME TLS, and userdata routing from EC2 User Data."""
    user_data = tmp_path / "user-data"
    user_data.write_text(
        """BRAINSOS_DOMAIN=alice.demo.infotechlabs.io
HOSTED_ZONE_ID="arn:aws:route53:::hostedzone/Z0987654321DEMO"
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["BRAINSOS_FIRSTBOOT_USER_DATA_FILE"] = str(user_data)

    proc = subprocess.run(
        [str(FIRSTBOOT), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "BRAINSOS_DOMAIN=alice.demo.infotechlabs.io" in proc.stdout
    assert "BRAINSOS_URL=alice.demo.infotechlabs.io" in proc.stdout
    assert "BRAINSOS_LOCAL_DOMAIN=alice.demo.infotechlabs.io" in proc.stdout
    assert "BRAINSOS_TLS_MODE=acme" in proc.stdout
    assert "ACME_EMAIL=ops@infotechlabs.io" in proc.stdout
    assert "BRAINSOS_USERDATA_ROUTING=true" in proc.stdout
    assert "BRAINSOS_ROUTE53_ZONE_ID=Z0987654321DEMO" in proc.stdout
    assert "Would sync Route 53 A record: alice.demo.infotechlabs.io" in proc.stdout


def test_firstboot_base_domain_derives_from_ec2_name_tag(tmp_path: Path):
    """Verify BRAINSOS_BASE_DOMAIN + EC2 Name tag auto-derives <slug>.<base_domain>."""
    user_data = tmp_path / "user-data"
    user_data.write_text(
        """#cloud-config
brainsos:
  base_domain: demo.infotechlabs.io
  route53_zone_id: Z0987654321DEMO
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["BRAINSOS_FIRSTBOOT_USER_DATA_FILE"] = str(user_data)
    env["BRAINSOS_FIRSTBOOT_NAME_TAG"] = "Charlie Box"

    proc = subprocess.run(
        [str(FIRSTBOOT), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "BRAINSOS_DOMAIN=charlie-box.demo.infotechlabs.io" in proc.stdout
    assert "BRAINSOS_LOCAL_DOMAIN=charlie-box.demo.infotechlabs.io" in proc.stdout
    assert "BRAINSOS_TLS_MODE=acme" in proc.stdout
    assert "BRAINSOS_USERDATA_ROUTING=true" in proc.stdout
