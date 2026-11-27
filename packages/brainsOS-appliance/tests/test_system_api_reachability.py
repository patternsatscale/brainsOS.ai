"""Unit and integration tests for B2 (Ticket #330): System API bind IP and Caddy reachability."""

import os
import platform
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
from brainsos_telemetry.system import get_default_api_host

REPO_ROOT = Path(__file__).resolve().parents[3]
FIRSTBOOT = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@brainsos.ai", "-c", "user.name=test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def firstboot_tree(tmp_path: Path) -> Path:
    """Minimal repository subset needed by firstboot.sh + generate-env.sh."""
    root = tmp_path / "brainsos"
    (root / "scripts" / "control").mkdir(parents=True)
    (root / "packages" / "brainsOS-appliance" / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "generate-env.sh", root / "scripts" / "control")
    shutil.copy2(REPO_ROOT / "scripts" / "control" / "env-upsert.sh", root / "scripts" / "control")
    shutil.copy2(FIRSTBOOT, root / "packages" / "brainsOS-appliance" / "scripts")
    shutil.copy2(REPO_ROOT / ".env.example", root)
    _git(root, "init", "--quiet")
    return root


def _run_firstboot(root: Path) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("BRAINSOS_")
    }
    env.update(
        {
            "BRAINSOS_REPO_ROOT": str(root),
            "BRAINSOS_FIRSTBOOT_SKIP_IMDS": "true",
            "BRAINSOS_FIRSTBOOT_SKIP_PORTAL": "true",
            "BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP": "true",
        }
    )
    return subprocess.run(
        ["bash", str(root / "packages" / "brainsOS-appliance" / "scripts" / "firstboot.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_firstboot_does_not_pin_system_api_host(firstboot_tree: Path):
    """First boot must not write an active BRAINSOS_SYSTEM_API_HOST= assignment."""
    proc = _run_firstboot(firstboot_tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    env_lines = (firstboot_tree / ".env").read_text(encoding="utf-8").splitlines()
    active_host_lines = [
        ln for ln in env_lines
        if not ln.lstrip().startswith("#") and ln.lstrip().startswith("BRAINSOS_SYSTEM_API_HOST=")
    ]
    assert active_host_lines == []


def test_env_example_does_not_pin_system_api_host():
    """.env.example must have no uncommented BRAINSOS_SYSTEM_API_HOST= line."""
    env_lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    active_host_lines = [
        ln for ln in env_lines
        if not ln.lstrip().startswith("#") and ln.lstrip().startswith("BRAINSOS_SYSTEM_API_HOST=")
    ]
    assert active_host_lines == []


def test_default_bind_rejects_wildcard(monkeypatch: pytest.MonkeyPatch):
    """Wildcard bind addresses (0.0.0.0, ::) are rejected and fall through to auto-detection."""
    monkeypatch.setenv("BRAINSOS_SYSTEM_API_HOST", "0.0.0.0")
    host = get_default_api_host()
    assert host not in ("0.0.0.0", "::")


@pytest.mark.skipif(
    platform.system() != "Linux" or shutil.which("docker") is None,
    reason="Requires Linux + docker",
)
def test_container_reaches_default_bind_address(monkeypatch: pytest.MonkeyPatch):
    """A container with host.docker.internal:host-gateway can reach a listener bound to get_default_api_host()."""
    monkeypatch.delenv("BRAINSOS_SYSTEM_API_HOST", raising=False)
    bind_ip = get_default_api_host()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((bind_ip, 0))
    except OSError as exc:
        srv.close()
        pytest.skip(f"Cannot bind to {bind_ip}: {exc}")

    port = srv.getsockname()[1]
    srv.listen(1)
    srv.settimeout(10)

    def _accept_once() -> None:
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept_once, daemon=True)
    t.start()

    try:
        proc = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--add-host",
                "host.docker.internal:host-gateway",
                "alpine",
                "nc",
                "-z",
                "-w",
                "3",
                "host.docker.internal",
                str(port),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        srv.close()
        t.join(timeout=2)


HARDEN_HOST = REPO_ROOT / "packages" / "brainsOS-appliance" / "scripts" / "harden-host.sh"


def _ufw_fixture(
    *,
    verbose: bool = False,
    default_incoming: str = "deny",
    include_8000_deny: bool = True,
    include_8010_deny: bool = True,
    include_br_mail_allow: bool = True,
    include_br_ingress_allow: bool = True,
    extra_rules: tuple[str, ...] = (),
) -> str:
    action_allow = "ALLOW IN   " if verbose else "ALLOW      "
    action_deny = "DENY IN    " if verbose else "DENY       "
    lines = ["Status: active"]
    if verbose:
        lines.extend(
            [
                "Logging: on (low)",
                f"Default: {default_incoming} (incoming), allow (outgoing), disabled (routed)",
                "New profiles: skip",
            ]
        )
    lines.extend(
        [
            "",
            "To                         Action      From",
            "--                         ------      ----",
            f"80/tcp                     {action_allow} Anywhere                   # brainsOS Ingress HTTP (Redirect)",
            f"443/tcp                    {action_allow} Anywhere                   # brainsOS Ingress HTTPS (Single-Origin)",
        ]
    )
    if include_8000_deny:
        lines.append(
            f"8000/tcp on ens5           {action_deny} Anywhere                   # Block external VPC access to Mail Ingress (ens5)"
        )
    if include_8010_deny:
        lines.append(
            f"8010/tcp on ens5           {action_deny} Anywhere                   # Block external VPC access to System API (ens5)"
        )
    if include_br_mail_allow:
        lines.append(
            f"8000/tcp on br-mail        {action_allow} 172.28.5.0/24              # brainsOS Mail Ingress (brainsos-mail-net)"
        )
    if include_br_ingress_allow:
        lines.append(
            f"8010/tcp on br-ingress     {action_allow} 172.28.0.0/24              # brainsOS System API (brainsos-ingress-net)"
        )
    lines.extend(extra_rules)
    return "\n".join(lines) + "\n"


def _run_harden_host_check(
    tmp_path: Path,
    *,
    status_text: str,
    verbose_text: str | None = None,
    reject_verbose: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    uname_shim = bin_dir / "uname"
    uname_shim.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
    uname_shim.chmod(0o755)

    (tmp_path / "ufw_status.txt").write_text(status_text, encoding="utf-8")
    (tmp_path / "ufw_verbose.txt").write_text(
        status_text if verbose_text is None else verbose_text,
        encoding="utf-8",
    )

    ufw_shim = bin_dir / "ufw"
    reject_flag = "1" if reject_verbose else "0"
    ufw_shim.write_text(
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "status" ] && [ "${{2:-}}" = "verbose" ]; then
  if [ "{reject_flag}" = "1" ]; then
    exit 1
  fi
  cat "{tmp_path / 'ufw_verbose.txt'}"
  exit 0
fi
if [ "${{1:-}}" = "status" ]; then
  cat "{tmp_path / 'ufw_status.txt'}"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    ufw_shim.chmod(0o755)

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    return subprocess.run(
        ["bash", str(HARDEN_HOST), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("mode", ["non_verbose", "verbose", "verbose_fallback"])
def test_harden_host_check_ufw_passes_non_verbose_and_verbose(tmp_path: Path, mode: str) -> None:
    """harden-host.sh --check passes Check 1 for non-verbose ufw status, ufw status verbose, and verbose fallback."""
    if mode == "non_verbose":
        proc = _run_harden_host_check(tmp_path, status_text=_ufw_fixture(verbose=False))
    elif mode == "verbose":
        proc = _run_harden_host_check(
            tmp_path,
            status_text=_ufw_fixture(verbose=False),
            verbose_text=_ufw_fixture(verbose=True),
        )
    else:
        proc = _run_harden_host_check(
            tmp_path,
            status_text=_ufw_fixture(verbose=False),
            reject_verbose=True,
        )

    assert "UFW ports 80/tcp and 443/tcp are allowed." in proc.stdout
    assert "strictly bridge-scoped and denied on external NICs" in proc.stdout
    assert "lack strict bridge scoping" not in proc.stdout


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "missing_8010_deny",
        "missing_8000_deny",
        "legacy_172_16_allow",
        "anywhere_allow",
        "zero_slash_zero_allow",
        "missing_br_mail_allow",
        "missing_br_ingress_allow",
        "comment_spoof_deny",
        "bridge_interface_deny_only",
        "ipv6_allow_8010_anywhere",
        "ipv6_allow_8000_anywhere",
        "ipv6_allow_8010_cidr",
        "ipv4_allow_8010_172_31",
        "ipv4_allow_8000_10_0_0_0",
        "ipv4_allow_8000_on_ens5",
        "ipv4_allow_8010_wrong_bridge",
        "ipv4_allow_8000_wrong_bridge",
        "ipv4_allow_8010_wrong_subnet",
        "proto_any_allow_8010",
        "limit_8010_anywhere",
        "dst_ip_8010_anywhere",
        "v6_only_deny_8010",
        "port_range_8000_8010",
        "port_range_7999_8001",
        "port_range_999_8000",
        "port_range_proto_any",
        "multiport_80_8010",
        "multiport_8000_8010",
        "multiport_8000_8080",
        "multiport_with_range",
        "anywhere_all_ports_allow",
        "anywhere_tcp_all_ports_allow",
        "anywhere_udp_all_ports_allow",
        "anywhere_v6_all_ports_allow",
        "anywhere_on_ens5_allow",
        "anywhere_limit",
        "dst_ip_all_ports_allow",
        "dst_cidr_tcp_all_ports_allow",
        "br_control_deny_only",
        "docker0_deny_only",
    ],
)
def test_harden_host_check_ufw_fails_on_policy_violations(
    tmp_path: Path, verbose: bool, scenario: str
) -> None:
    """harden-host.sh --check rejects missing per-port external DENY, broad ALLOWs, missing bridge ALLOWs, and spoofed DENYs."""
    allow_tok = "ALLOW IN   " if verbose else "ALLOW      "
    deny_tok = "DENY IN    " if verbose else "DENY       "
    limit_tok = "LIMIT IN   " if verbose else "LIMIT      "

    kwargs: dict[str, object] = {"verbose": verbose}
    if scenario == "missing_8010_deny":
        kwargs["include_8010_deny"] = False
    elif scenario == "missing_8000_deny":
        kwargs["include_8000_deny"] = False
    elif scenario == "legacy_172_16_allow":
        kwargs["extra_rules"] = (
            f"8000/tcp on br-mail        {allow_tok} 172.16.0.0/12              # legacy broad allow",
        )
    elif scenario == "anywhere_allow":
        kwargs["extra_rules"] = (
            f"8010/tcp                   {allow_tok} Anywhere                   # accidental global allow",
        )
    elif scenario == "zero_slash_zero_allow":
        kwargs["extra_rules"] = (
            f"8000/tcp                   {allow_tok} 0.0.0.0/0                  # accidental 0.0.0.0/0 allow",
        )
    elif scenario == "missing_br_mail_allow":
        kwargs["include_br_mail_allow"] = False
    elif scenario == "missing_br_ingress_allow":
        kwargs["include_br_ingress_allow"] = False
    elif scenario == "comment_spoof_deny":
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"22/tcp on ens5             {deny_tok} Anywhere                   # 8010/tcp on ens5 DENY Anywhere",
        )
    elif scenario == "bridge_interface_deny_only":
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"8010/tcp on br-ingress     {deny_tok} Anywhere                   # wrong interface deny",
        )
    elif scenario == "ipv6_allow_8010_anywhere":
        kwargs["extra_rules"] = (
            f"8010/tcp (v6)              {allow_tok} Anywhere (v6)              # IPv6 global 8010 allow",
        )
    elif scenario == "ipv6_allow_8000_anywhere":
        kwargs["extra_rules"] = (
            f"8000/tcp (v6)              {allow_tok} Anywhere (v6)              # IPv6 global 8000 allow",
        )
    elif scenario == "ipv6_allow_8010_cidr":
        kwargs["extra_rules"] = (
            f"8010/tcp                   {allow_tok} fe80::/10                  # IPv6 link-local allow",
        )
    elif scenario == "ipv4_allow_8010_172_31":
        kwargs["extra_rules"] = (
            f"8010/tcp                   {allow_tok} 172.31.0.0/16              # AWS Default VPC CIDR allow",
        )
    elif scenario == "ipv4_allow_8000_10_0_0_0":
        kwargs["extra_rules"] = (
            f"8000/tcp                   {allow_tok} 10.0.0.0/8                 # RFC1918 10/8 allow",
        )
    elif scenario == "ipv4_allow_8000_on_ens5":
        kwargs["extra_rules"] = (
            f"8000/tcp on ens5           {allow_tok} 172.28.5.0/24              # external NIC allow with mail subnet",
        )
    elif scenario == "ipv4_allow_8010_wrong_bridge":
        kwargs["extra_rules"] = (
            f"8010/tcp on br-mail        {allow_tok} 172.28.5.0/24              # wrong bridge allow",
        )
    elif scenario == "ipv4_allow_8000_wrong_bridge":
        kwargs["extra_rules"] = (
            f"8000/tcp on br-ingress     {allow_tok} 172.28.0.0/24              # wrong bridge allow",
        )
    elif scenario == "ipv4_allow_8010_wrong_subnet":
        kwargs["extra_rules"] = (
            f"8010/tcp on br-ingress     {allow_tok} 172.28.5.0/24              # wrong subnet on right bridge",
        )
    elif scenario == "proto_any_allow_8010":
        kwargs["extra_rules"] = (
            f"8010                       {allow_tok} Anywhere                   # proto any allow",
        )
    elif scenario == "limit_8010_anywhere":
        kwargs["extra_rules"] = (
            f"8010/tcp                   {limit_tok} Anywhere                   # rate-limited allow",
        )
    elif scenario == "dst_ip_8010_anywhere":
        kwargs["extra_rules"] = (
            f"172.28.0.1 8010/tcp        {allow_tok} Anywhere                   # dst IP scoped allow",
        )
    elif scenario == "v6_only_deny_8010":
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"8010/tcp (v6) on ens5      {deny_tok} Anywhere (v6)              # IPv6-only deny",
        )
    elif scenario == "port_range_8000_8010":
        kwargs["extra_rules"] = (
            f"8000:8010/tcp              {allow_tok} Anywhere                   # port range covering 8000-8010",
        )
    elif scenario == "port_range_7999_8001":
        kwargs["extra_rules"] = (
            f"7999:8001/tcp              {allow_tok} Anywhere                   # port range spanning 8000",
        )
    elif scenario == "port_range_999_8000":
        kwargs["extra_rules"] = (
            f"999:8000/tcp               {allow_tok} Anywhere                   # numeric range boundary 999..8000",
        )
    elif scenario == "port_range_proto_any":
        kwargs["extra_rules"] = (
            f"8000:8010                  {allow_tok} Anywhere                   # proto-any range",
        )
    elif scenario == "multiport_80_8010":
        kwargs["extra_rules"] = (
            f"80,8010/tcp                {allow_tok} Anywhere                   # multiport including 8010",
        )
    elif scenario == "multiport_8000_8010":
        kwargs["extra_rules"] = (
            f"8000,8010/tcp              {allow_tok} Anywhere                   # multiport 8000,8010",
        )
    elif scenario == "multiport_8000_8080":
        kwargs["extra_rules"] = (
            f"8000,8080/tcp              {allow_tok} Anywhere                   # multiport including 8000",
        )
    elif scenario == "multiport_with_range":
        kwargs["extra_rules"] = (
            f"80,7999:8001,443/tcp       {allow_tok} Anywhere                   # multiport with range spanning 8000",
        )
    elif scenario == "anywhere_all_ports_allow":
        kwargs["extra_rules"] = (
            f"Anywhere                   {allow_tok} 172.31.0.0/16              # all-port allow from VPC CIDR",
        )
    elif scenario == "anywhere_tcp_all_ports_allow":
        kwargs["extra_rules"] = (
            f"Anywhere/tcp               {allow_tok} Anywhere                   # all-port TCP allow",
        )
    elif scenario == "anywhere_udp_all_ports_allow":
        kwargs["extra_rules"] = (
            f"Anywhere/udp               {allow_tok} Anywhere                   # all-port UDP allow",
        )
    elif scenario == "anywhere_v6_all_ports_allow":
        kwargs["extra_rules"] = (
            f"Anywhere (v6)              {allow_tok} Anywhere (v6)              # all-port IPv6 allow",
        )
    elif scenario == "anywhere_on_ens5_allow":
        kwargs["extra_rules"] = (
            f"Anywhere on ens5           {allow_tok} Anywhere                   # all-port allow on WAN NIC",
        )
    elif scenario == "anywhere_limit":
        kwargs["extra_rules"] = (
            f"Anywhere                   {limit_tok} Anywhere                   # all-port LIMIT",
        )
    elif scenario == "dst_ip_all_ports_allow":
        kwargs["extra_rules"] = (
            f"172.28.0.1                 {allow_tok} Anywhere                   # dst-IP all-port allow",
        )
    elif scenario == "dst_cidr_tcp_all_ports_allow":
        kwargs["extra_rules"] = (
            f"172.28.0.0/24/tcp          {allow_tok} Anywhere                   # dst-CIDR TCP all-port allow",
        )
    elif scenario == "br_control_deny_only":
        kwargs["include_8000_deny"] = False
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"8000/tcp on br-control     {deny_tok} Anywhere",
            f"8010/tcp on br-control     {deny_tok} Anywhere",
        )
    elif scenario == "docker0_deny_only":
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"8010/tcp on docker0        {deny_tok} Anywhere",
        )

    text = _ufw_fixture(**kwargs)  # type: ignore[arg-type]
    proc = _run_harden_host_check(tmp_path, status_text=text, verbose_text=text)
    assert proc.returncode != 0
    assert "lack strict bridge scoping" in proc.stdout
    assert "strictly bridge-scoped and denied on external NICs" not in proc.stdout


@pytest.mark.parametrize("default_incoming", ["allow", "reject"])
def test_harden_host_check_ufw_fails_on_non_deny_default_incoming(
    tmp_path: Path, default_incoming: str
) -> None:
    """harden-host.sh --check rejects verbose UFW status whose default incoming policy is not deny."""
    text = _ufw_fixture(verbose=True, default_incoming=default_incoming)
    proc = _run_harden_host_check(tmp_path, status_text=text, verbose_text=text)
    assert proc.returncode != 0
    assert "default incoming policy is not deny" in proc.stdout
    assert "strictly bridge-scoped and denied on external NICs" not in proc.stdout


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "external_deny_comment_mentions_bridge",
        "external_deny_comment_mentions_allow",
        "bridge_allow_with_allow_comment",
    ],
)
def test_harden_host_check_ufw_passes_with_bridge_and_allow_comments(
    tmp_path: Path, verbose: bool, scenario: str
) -> None:
    """harden-host.sh --check strips UFW rule comments before checking bridge scoping and disallowed allows."""
    allow_tok = "ALLOW IN   " if verbose else "ALLOW      "
    deny_tok = "DENY IN    " if verbose else "DENY       "

    kwargs: dict[str, object] = {"verbose": verbose}
    if scenario == "external_deny_comment_mentions_bridge":
        kwargs["include_8000_deny"] = False
        kwargs["include_8010_deny"] = False
        kwargs["extra_rules"] = (
            f"8000/tcp on ens5           {deny_tok} Anywhere                   # replaced on br-mail rule",
            f"8010/tcp on ens5           {deny_tok} Anywhere                   # replaced on br-ingress rule",
        )
    elif scenario == "external_deny_comment_mentions_allow":
        kwargs["include_8000_deny"] = False
        kwargs["extra_rules"] = (
            f"8000/tcp on ens5           {deny_tok} Anywhere                   # replaces 8000/tcp ALLOW Anywhere",
        )
    elif scenario == "bridge_allow_with_allow_comment":
        kwargs["include_br_mail_allow"] = False
        kwargs["extra_rules"] = (
            f"8000/tcp on br-mail        {allow_tok} 172.28.5.0/24              # ALLOW Anywhere",
        )

    text = _ufw_fixture(**kwargs)  # type: ignore[arg-type]
    proc = _run_harden_host_check(tmp_path, status_text=text, verbose_text=text)
    assert "UFW ports 80/tcp and 443/tcp are allowed." in proc.stdout
    assert "strictly bridge-scoped and denied on external NICs" in proc.stdout
    assert "lack strict bridge scoping" not in proc.stdout


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "bridge_allow_8000_udp_extra",
        "non_target_port_range_8001_8009",
        "non_target_multiport_800_80000",
        "br_control_deny_alongside_ens5",
        "app_profile_openssh",
        "comment_mentions_range_and_anywhere",
    ],
)
def test_harden_host_check_ufw_passes_non_disallowed_extra_rules(
    tmp_path: Path, verbose: bool, scenario: str
) -> None:
    """harden-host.sh --check passes valid non-disallowed UDP, non-target range/multiport, app profile, and comment rules."""
    allow_tok = "ALLOW IN   " if verbose else "ALLOW      "
    deny_tok = "DENY IN    " if verbose else "DENY       "

    kwargs: dict[str, object] = {"verbose": verbose}
    if scenario == "bridge_allow_8000_udp_extra":
        kwargs["extra_rules"] = (
            f"8000/udp on br-mail        {allow_tok} 172.28.5.0/24              # UDP rule on br-mail",
        )
    elif scenario == "non_target_port_range_8001_8009":
        kwargs["extra_rules"] = (
            f"8001:8009/tcp              {allow_tok} Anywhere                   # range strictly between 8000 and 8010",
        )
    elif scenario == "non_target_multiport_800_80000":
        kwargs["extra_rules"] = (
            f"800,80000/tcp              {allow_tok} Anywhere                   # non-matching ports sharing prefix",
        )
    elif scenario == "br_control_deny_alongside_ens5":
        kwargs["extra_rules"] = (
            f"8000/tcp on br-control     {deny_tok} Anywhere                   # extra bridge deny with ens5 present",
        )
    elif scenario == "app_profile_openssh":
        kwargs["extra_rules"] = (
            "22/tcp (OpenSSH)           ALLOW IN    Anywhere"
            if verbose
            else "OpenSSH                    ALLOW       Anywhere",
        )
    elif scenario == "comment_mentions_range_and_anywhere":
        kwargs["include_8000_deny"] = False
        kwargs["extra_rules"] = (
            f"8000/tcp on ens5           {deny_tok} Anywhere                   # 8000:8010/tcp Anywhere ALLOW",
        )

    text = _ufw_fixture(**kwargs)  # type: ignore[arg-type]
    proc = _run_harden_host_check(tmp_path, status_text=text, verbose_text=text)
    assert "UFW ports 80/tcp and 443/tcp are allowed." in proc.stdout
    assert "strictly bridge-scoped and denied on external NICs" in proc.stdout
    assert "lack strict bridge scoping" not in proc.stdout
    assert "default incoming policy is not deny" not in proc.stdout

