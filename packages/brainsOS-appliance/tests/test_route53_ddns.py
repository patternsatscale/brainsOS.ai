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
GENERATE_ENV = REPO_ROOT / "scripts" / "control" / "generate-env.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"

TEST_SECRET_A = "a" * 64
TEST_SECRET_B = "b" * 64


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
        existing_owner_claim: str | None = None,
        legacy_owner: str | None = None,
        deny_list: bool = False,
        zones: list[dict[str, Any]] | None = None,
    ) -> None:
        self.existing_ip = existing_ip
        self.existing_owner_claim = existing_owner_claim
        self.legacy_owner = legacy_owner
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
        if StartRecordType == "TXT" and (self.existing_owner_claim or self.legacy_owner):
            txt_val = (
                f'"owner-sha256={self.existing_owner_claim}"'
                if self.existing_owner_claim
                else f'"instance-id={self.legacy_owner}"'
            )
            rrs.append(
                {
                    "Name": StartRecordName,
                    "Type": "TXT",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": txt_val}],
                }
            )
        return {"ResourceRecordSets": rrs}

    def change_resource_record_sets(
        self, HostedZoneId: str, ChangeBatch: dict[str, Any]
    ) -> dict[str, Any]:
        self.changes.append({"HostedZoneId": HostedZoneId, "ChangeBatch": ChangeBatch})
        return {"ChangeInfo": {"Id": "/change/C1234567890", "Status": "PENDING"}}


def test_sync_route53_upsert_redacts_instance_id_and_idempotency(monkeypatch):
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", TEST_SECRET_A)
    mod = _load_sync_module()
    client = FakeRoute53Client()
    raw_iid = "i-0123456789abcdef0"

    res = mod.sync_route53_record(
        route53_client=client,
        domain="https://alice.demo.infotechlabs.io/",
        ip="54.210.11.22",
        zone_id="/hostedzone/Z0987654321DEMO",
        instance_id=raw_iid,
        ttl=60,
    )
    expected_claim = mod.compute_owner_claim("alice.demo.infotechlabs.io", "Z0987654321DEMO", raw_iid)
    assert res["status"] == "updated"
    assert res["changed"] is True
    assert res["domain"] == "alice.demo.infotechlabs.io"
    assert res["zone_id"] == "Z0987654321DEMO"
    assert res["owner_claim"] == expected_claim
    assert len(client.changes) == 1
    batch = client.changes[0]["ChangeBatch"]["Changes"]
    assert batch[0]["Action"] == "UPSERT"
    assert batch[0]["ResourceRecordSet"]["Name"] == "alice.demo.infotechlabs.io"
    assert batch[0]["ResourceRecordSet"]["ResourceRecords"] == [{"Value": "54.210.11.22"}]
    assert batch[1]["ResourceRecordSet"]["Name"] == "_brainsos-owner.alice.demo.infotechlabs.io"
    assert batch[1]["ResourceRecordSet"]["ResourceRecords"] == [
        {"Value": f'"owner-sha256={expected_claim}"'}
    ]
    # Raw EC2 Instance ID must never appear anywhere in the public Route 53 ChangeBatch (#384)
    assert raw_iid not in str(client.changes[0])

    # Unchanged when IP and keyed owner claim already match
    unchanged_client = FakeRoute53Client(
        existing_ip="54.210.11.22",
        existing_owner_claim=expected_claim,
    )
    res2 = mod.sync_route53_record(
        route53_client=unchanged_client,
        domain="alice.demo.infotechlabs.io",
        ip="54.210.11.22",
        zone_id="Z0987654321DEMO",
        instance_id=raw_iid,
    )
    assert res2["status"] == "unchanged"
    assert res2["changed"] is False
    assert len(unchanged_client.changes) == 0

    # Any pre-existing legacy instance-id= TXT record (even from another ID) is overwritten directly with no legacy fallback
    legacy_client = FakeRoute53Client(
        existing_ip="54.210.11.22",
        legacy_owner="i-0legacyother12345",
    )
    res_mig = mod.sync_route53_record(
        route53_client=legacy_client,
        domain="alice.demo.infotechlabs.io",
        ip="54.210.11.22",
        zone_id="Z0987654321DEMO",
        instance_id=raw_iid,
    )
    assert res_mig["status"] == "updated"
    assert len(legacy_client.changes) == 1
    assert raw_iid not in str(legacy_client.changes[0])
    assert legacy_client.changes[0]["ChangeBatch"]["Changes"][1]["ResourceRecordSet"]["ResourceRecords"] == [
        {"Value": f'"owner-sha256={expected_claim}"'}
    ]


def test_sync_route53_ownership_collision_and_force(monkeypatch):
    mod = _load_sync_module()
    other_claim = mod.compute_owner_claim(
        "alice.demo.infotechlabs.io",
        "Z0987654321DEMO",
        "i-0aaaaaaaaaaaaaaa1",
        owner_secret=TEST_SECRET_B,
    )
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", TEST_SECRET_A)
    other_owner_client = FakeRoute53Client(
        existing_ip="3.91.10.20",
        existing_owner_claim=other_claim,
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


def test_sync_route53_minimal_iam_fallback_and_zone_discovery(monkeypatch):
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", TEST_SECRET_A)
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


def test_sync_route53_invalid_inputs_rejected(monkeypatch):
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", TEST_SECRET_A)
    mod = _load_sync_module()
    client = FakeRoute53Client()

    with pytest.raises(ValueError, match="Invalid FQDN"):
        mod.sync_route53_record(client, domain="not_a_domain", ip="1.2.3.4", zone_id="Z123456")

    with pytest.raises(ValueError, match="Invalid IPv4"):
        mod.sync_route53_record(
            client, domain="alice.demo.infotechlabs.io", ip="999.999.1.1", zone_id="Z123456"
        )


def test_compute_owner_claim_fails_closed_without_256bit_secret(monkeypatch):
    mod = _load_sync_module()
    for bad in ("", "   ", "not-hex", "a" * 63, "a" * 65):
        monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", bad)
        with pytest.raises(ValueError, match="BRAINSOS_DDNS_OWNER_SECRET"):
            mod.compute_owner_claim("alice.demo.infotechlabs.io", "Z0987654321DEMO", "i-0123456789abcdef0")
    monkeypatch.delenv("BRAINSOS_DDNS_OWNER_SECRET", raising=False)
    with pytest.raises(ValueError, match="BRAINSOS_DDNS_OWNER_SECRET"):
        mod.compute_owner_claim("alice.demo.infotechlabs.io", "Z0987654321DEMO", "i-0123456789abcdef0")


def test_sync_route53_fails_closed_without_owner_secret(monkeypatch):
    monkeypatch.delenv("BRAINSOS_DDNS_OWNER_SECRET", raising=False)
    mod = _load_sync_module()
    client = FakeRoute53Client()
    with pytest.raises(ValueError, match="BRAINSOS_DDNS_OWNER_SECRET"):
        mod.sync_route53_record(
            route53_client=client,
            domain="alice.demo.infotechlabs.io",
            ip="54.210.11.22",
            zone_id="Z0987654321DEMO",
            instance_id="i-0123456789abcdef0",
        )
    assert client.changes == []

    # CLI exits 1 when secret is missing
    proc = subprocess.run(
        [
            "python3",
            str(SYNC_SCRIPT),
            "--domain",
            "alice.demo.infotechlabs.io",
            "--ip",
            "54.210.11.22",
            "--zone-id",
            "Z0987654321DEMO",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "BRAINSOS_DDNS_OWNER_SECRET"},
    )
    assert proc.returncode == 1
    assert "BRAINSOS_DDNS_OWNER_SECRET" in proc.stderr


def test_sync_route53_ebs_resume_same_secret_new_instance_id(monkeypatch):
    """Host B resuming a volume with persisted TEST_SECRET_A updates IP seamlessly even with new instance_id."""
    monkeypatch.setenv("BRAINSOS_DDNS_OWNER_SECRET", TEST_SECRET_A)
    mod = _load_sync_module()
    claim_host_a = mod.compute_owner_claim(
        "alice.demo.infotechlabs.io", "Z0987654321DEMO", "i-0hostaaaaaaaaaa1"
    )
    client = FakeRoute53Client(
        existing_ip="1.2.3.4",
        existing_owner_claim=claim_host_a,
    )
    res = mod.sync_route53_record(
        route53_client=client,
        domain="alice.demo.infotechlabs.io",
        ip="5.6.7.8",
        zone_id="Z0987654321DEMO",
        instance_id="i-0hostbbbbbbbbbb2",
    )
    assert res["status"] == "updated"
    assert res["owner_claim"] == claim_host_a
    assert len(client.changes) == 1


def test_generate_env_persists_and_preserves_256bit_ddns_owner_secret(tmp_path: Path):
    """generate-env.sh creates 64-hex BRAINSOS_DDNS_OWNER_SECRET (0600) and preserves it across re-runs."""
    import re
    import shutil
    import stat

    ctrl_dir = tmp_path / "scripts" / "control"
    ctrl_dir.mkdir(parents=True)
    shutil.copy2(GENERATE_ENV, ctrl_dir / "generate-env.sh")
    (ctrl_dir / "generate-env.sh").chmod(0o755)
    shutil.copy2(ENV_EXAMPLE, tmp_path / ".env.example")

    env_file = tmp_path / ".env"
    env = {
        **os.environ,
        "BRAINSOS_REPO_ROOT": str(tmp_path),
        "BRAINSOS_ENV_FILE": str(env_file),
    }

    p1 = subprocess.run(
        [str(ctrl_dir / "generate-env.sh"), "--non-interactive", "--no-rebuild"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert p1.returncode == 0, p1.stdout + p1.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    m1 = re.search(r"^BRAINSOS_DDNS_OWNER_SECRET=([0-9a-fA-F]{64})$", env_file.read_text(encoding="utf-8"), re.M)
    assert m1 is not None
    secret_1 = m1.group(1)

    p2 = subprocess.run(
        [str(ctrl_dir / "generate-env.sh"), "--non-interactive", "--no-rebuild"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert p2.returncode == 0, p2.stdout + p2.stderr
    m2 = re.search(r"^BRAINSOS_DDNS_OWNER_SECRET=([0-9a-fA-F]{64})$", env_file.read_text(encoding="utf-8"), re.M)
    assert m2 is not None
    assert m2.group(1) == secret_1


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
    assert "BRAINSOS_DDNS_OWNER_SECRET=<auto-generated-256bit>" in proc.stdout
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
