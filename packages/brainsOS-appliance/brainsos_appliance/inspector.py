"""System inspector and posture auditor for brainsOS appliance."""

import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


def get_repo_root() -> Path:
    """Find the root directory of the brainsOS repository."""
    return Path(__file__).resolve().parents[3]


def inspect_firstboot_status(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Check if first-boot initialization has been performed."""
    root = repo_root or get_repo_root()
    init_flag = root / ".brainsos-initialized"
    env_file = root / ".env"

    is_initialized = init_flag.is_file()
    init_timestamp = None
    if is_initialized:
        try:
            init_timestamp = init_flag.read_text().strip()
        except Exception:
            init_timestamp = "unknown"

    env_exists = env_file.is_file()
    env_mode = None
    env_permissions_ok = False
    if env_exists:
        stat_info = env_file.stat()
        env_mode = oct(stat_info.st_mode)[-3:]
        env_permissions_ok = (env_mode == "600")

    return {
        "initialized": is_initialized,
        "initialization_timestamp": init_timestamp,
        "env_file_exists": env_exists,
        "env_permissions": env_mode,
        "env_permissions_secure": env_permissions_ok,
    }


def query_imdsv2_metadata(timeout: float = 1.0) -> Dict[str, Any]:
    """Safely query AWS EC2 IMDSv2 metadata with short timeout."""
    token_url = "http://169.254.169.254/latest/api/token"
    token = None
    try:
        req = urllib.request.Request(
            token_url,
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                token = resp.read().decode("utf-8").strip()
    except Exception:
        token = None

    if not token:
        return {
            "imds_available": False,
            "instance_id": None,
            "public_hostname": None,
            "local_ipv4": None,
        }

    def _get_meta(path: str) -> Optional[str]:
        try:
            req = urllib.request.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8").strip()
        except Exception:
            return None
        return None

    return {
        "imds_available": True,
        "instance_id": _get_meta("instance-id"),
        "public_hostname": _get_meta("public-hostname"),
        "local_ipv4": _get_meta("local-ipv4"),
    }


def audit_host_hardening() -> Dict[str, Any]:
    """Audit local host hardening status (Docker logging, Journald, UFW)."""
    checks: Dict[str, Any] = {}

    # Check Docker daemon logging
    docker_conf = Path("/etc/docker/daemon.json")
    if docker_conf.is_file():
        try:
            with open(docker_conf, "r") as f:
                data = json.load(f)
            log_opts = data.get("log-opts", {})
            checks["docker_daemon_logging"] = {
                "configured": True,
                "max_size": log_opts.get("max-size"),
                "max_file": log_opts.get("max-file"),
            }
        except Exception as e:
            checks["docker_daemon_logging"] = {"configured": False, "error": str(e)}
    else:
        checks["docker_daemon_logging"] = {"configured": False, "present": False}

    # Check Journald drop-in
    journald_dropin = Path("/etc/systemd/journald.conf.d/99-brainsos.conf")
    checks["journald_dropin_present"] = journald_dropin.is_file()

    # Check Logrotate drop-in
    logrotate_conf = Path("/etc/logrotate.d/brainsos")
    checks["logrotate_present"] = logrotate_conf.is_file()

    # Check UFW status if command available
    if shutil.which("ufw"):
        try:
            res = subprocess.run(["ufw", "status"], capture_output=True, text=True, check=False)
            checks["ufw"] = {
                "available": True,
                "active": "Status: active" in res.stdout,
                "output": res.stdout.strip(),
            }
        except Exception as e:
            checks["ufw"] = {"available": True, "error": str(e)}
    else:
        checks["ufw"] = {"available": False}

    return checks


def evaluate_ami_findings(
    findings_payload: Dict[str, Any],
    ami_id: str = "ami-unknown",
    zero_fixable: bool = False,
) -> Dict[str, Any]:
    """Evaluate AWS EC2 GetImageFindings payload and assert 0 blocking fixable vulnerabilities.

    Unfixed upstream kernel CVEs (``FixAvailable: false``) are tracked separately from
    actionable vulnerabilities (``FixAvailable: true``).
    """
    findings = findings_payload.get("Findings") or findings_payload.get("findings") or []
    total_by_sev: Dict[str, int] = {}
    fixable_by_sev: Dict[str, int] = {}
    blocking_samples = []

    for item in findings:
        sev = str(item.get("Severity") or item.get("severity") or "UNSPECIFIED").upper()
        fix_raw = item.get("FixAvailable", item.get("fixAvailable", False))
        if isinstance(fix_raw, str):
            fix_avail = fix_raw.strip().upper() in ("TRUE", "YES", "1")
        else:
            fix_avail = bool(fix_raw)

        total_by_sev[sev] = total_by_sev.get(sev, 0) + 1
        if fix_avail:
            fixable_by_sev[sev] = fixable_by_sev.get(sev, 0) + 1
            if zero_fixable or sev in ("CRITICAL", "HIGH"):
                vuln_id = (
                    item.get("VulnerabilityId")
                    or item.get("Title")
                    or item.get("FindingArn")
                    or "unknown"
                )
                pkg = (
                    item.get("PackageName")
                    or (
                        item.get("PackageVulnerabilityDetails", {}).get("VulnerablePackages")
                        or [{}]
                    )[0].get("Name")
                    or "unknown"
                )
                blocking_samples.append(
                    {"severity": sev, "vulnerability_id": vuln_id, "package": pkg}
                )

    fixable_critical = fixable_by_sev.get("CRITICAL", 0)
    fixable_high = fixable_by_sev.get("HIGH", 0)
    fixable_total = sum(fixable_by_sev.values())
    total_count = sum(total_by_sev.values())
    passed = (
        (fixable_total == 0)
        if zero_fixable
        else (fixable_critical == 0 and fixable_high == 0)
    )

    return {
        "ami_id": ami_id,
        "scan_status": findings_payload.get("Status") or "ACTIVE",
        "total_findings": total_count,
        "fixable_total": fixable_total,
        "fixable_critical": fixable_critical,
        "fixable_high": fixable_high,
        "total_by_severity": total_by_sev,
        "fixable_by_severity": fixable_by_sev,
        "zero_fixable_enforced": zero_fixable,
        "passed": passed,
        "blocking_samples": blocking_samples[:20],
    }
