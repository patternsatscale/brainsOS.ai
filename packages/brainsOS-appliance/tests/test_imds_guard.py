"""Unit tests for B6 (Ticket #330): IMDS container isolation guard (scripts/setup/imds-guard.sh)."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
IMDS_GUARD = REPO_ROOT / "scripts" / "setup" / "imds-guard.sh"
BRAINSOS_SERVICE = REPO_ROOT / "packages" / "brainsOS-appliance" / "configs" / "brainsos.service"


def _make_shims(
    bin_dir: Path,
    ipt_log: Path,
    docker_output: str = "",
    check_exit: int = 1,
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)

    uname_shim = bin_dir / "uname"
    uname_shim.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
    uname_shim.chmod(0o755)

    docker_shim = bin_dir / "docker"
    docker_shim.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{docker_output}'\n",
        encoding="utf-8",
    )
    docker_shim.chmod(0o755)

    for tool_name in ("iptables", "ip6tables"):
        ipt_shim = bin_dir / tool_name
        ipt_shim.write_text(
            f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{ipt_log}"
for arg in "$@"; do
  if [ "$arg" = "-C" ]; then
    exit {check_exit}
  fi
done
exit 0
""",
            encoding="utf-8",
        )
        ipt_shim.chmod(0o755)


def test_noop_on_non_appliance(tmp_path: Path):
    """Without BRAINSOS_APPLIANCE=true, imds-guard.sh exits 0, logs not applicable, and invokes no iptables."""
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    env.pop("BRAINSOS_APPLIANCE", None)

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "not applicable" in proc.stdout
    assert not ipt_log.exists() or ipt_log.read_text(encoding="utf-8") == ""


def test_apply_allows_litellm_and_drops_rest(tmp_path: Path):
    """With LiteLLM container IPs present, BRAINSOS-IMDS allows each IP with RETURN, ends with DROP, and inserts into DOCKER-USER."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="172.20.0.5 172.21.0.7 ", check_exit=1)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    lines = [
        ln.removeprefix("iptables ")
        for ln in proc.stdout.splitlines()
        if ln.startswith("iptables ")
    ]
    expected_sequence = [
        "-F BRAINSOS-IMDS",
        "-A BRAINSOS-IMDS -s 172.20.0.5/32 -j RETURN",
        "-A BRAINSOS-IMDS -s 172.21.0.7/32 -j RETURN",
        "-A BRAINSOS-IMDS -j DROP",
    ]
    indices = [lines.index(cmd) for cmd in expected_sequence]
    assert indices == sorted(indices)
    assert any(
        "DOCKER-USER" in ln and "-d 169.254.169.254/32 -j BRAINSOS-IMDS" in ln and "-I" in ln
        for ln in lines
    )


def test_apply_fails_closed_without_litellm(tmp_path: Path):
    """When LiteLLM is not running (no IPs), BRAINSOS-IMDS contains only -j DROP."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="", check_exit=1)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    chain_rules = [
        ln.removeprefix("iptables ")
        for ln in proc.stdout.splitlines()
        if ln.startswith("iptables -A BRAINSOS-IMDS")
    ]
    assert chain_rules == ["-A BRAINSOS-IMDS -j DROP"]


def test_apply_is_idempotent(tmp_path: Path):
    """When iptables -C exits 0, no second -I DOCKER-USER is issued."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="172.20.0.5 ", check_exit=0)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "-I DOCKER-USER" not in proc.stdout


def test_brainsos_service_applies_guard():
    """brainsos.service includes ExecStartPost=/opt/brainsos/scripts/setup/imds-guard.sh --apply."""
    content = BRAINSOS_SERVICE.read_text(encoding="utf-8")
    assert "ExecStartPost=/opt/brainsos/scripts/setup/imds-guard.sh --apply" in content


def test_apply_enforces_internal_egress_chain_and_route53_caddy(tmp_path: Path):
    """F8 + F12: BRAINSOS-EGRESS restricts br-internal WAN egress to tool-egress-proxy:8082 and Route 53 mode allows Caddy IMDS."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_APPLIANCE=true\n"
        "BRAINSOS_TLS_MODE=route53\n"
        "BRAINSOS_LITELLM_STATIC_IP=172.28.2.10\n"
        "BRAINSOS_CADDY_STATIC_IP=172.28.0.10\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="", check_exit=1)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "iptables -A BRAINSOS-IMDS -s 172.28.2.10/32 -j RETURN" in proc.stdout
    assert "iptables -A BRAINSOS-IMDS -s 172.28.0.10/32 -j RETURN" in proc.stdout
    assert "iptables -A BRAINSOS-EGRESS -o br-internal -j RETURN" in proc.stdout
    assert "iptables -A BRAINSOS-EGRESS -s 172.28.1.2/32 -j RETURN" in proc.stdout
    assert "iptables -A BRAINSOS-EGRESS -j DROP" in proc.stdout
    assert "iptables -I DOCKER-USER 1 -i br-internal -j BRAINSOS-EGRESS" in proc.stdout
    assert "ip6tables -A BRAINSOS-EGRESS6 -j DROP" in proc.stdout


def test_remove_cleans_imds_and_egress_chains(tmp_path: Path):
    """imds-guard.sh --remove --dry-run removes both BRAINSOS-IMDS and BRAINSOS-EGRESS jumps and chains."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    ipt_log = tmp_path / "iptables.log"
    _make_shims(bin_dir, ipt_log, docker_output="", check_exit=0)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--remove", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "iptables -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS" in proc.stdout
    assert "iptables -X BRAINSOS-IMDS" in proc.stdout
    assert "iptables -D DOCKER-USER -i br-internal -j BRAINSOS-EGRESS" in proc.stdout
    assert "iptables -X BRAINSOS-EGRESS" in proc.stdout
    assert "ip6tables -X BRAINSOS-EGRESS6" in proc.stdout


def _make_stateful_shims(
    bin_dir: Path,
    state_dir: Path,
    cmd_log: Path,
    *,
    initial_v4: dict[str, list[str]] | None = None,
    initial_v6: dict[str, list[str]] | None = None,
    docker_litellm_ip: str = "172.28.2.10",
) -> None:
    import json

    bin_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    uname_shim = bin_dir / "uname"
    uname_shim.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
    uname_shim.chmod(0o755)

    id_shim = bin_dir / "id"
    id_shim.write_text(
        "#!/usr/bin/env bash\nif [ \"${1:-}\" = \"-u\" ]; then echo 0; else /usr/bin/id \"$@\"; fi\n",
        encoding="utf-8",
    )
    id_shim.chmod(0o755)

    docker_shim = bin_dir / "docker"
    docker_shim.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"com.docker.network.bridge.name"*) echo "br-internal" ;;
  *"brainsos-control-litellm"*) echo "{docker_litellm_ip}" ;;
  *"brainsos-agent-egress-proxy"*) echo "172.28.1.2" ;;
  *"brainsos-ingress-caddy"*) echo "172.28.1.10" ;;
  *) echo "" ;;
esac
""",
        encoding="utf-8",
    )
    docker_shim.chmod(0o755)

    for tool_name, init_state in (
        ("iptables", initial_v4 or {"DOCKER-USER": []}),
        ("ip6tables", initial_v6 or {"DOCKER-USER": []}),
    ):
        state_file = state_dir / f"{tool_name}.json"
        state_file.write_text(json.dumps(init_state), encoding="utf-8")
        shim = bin_dir / tool_name
        shim.write_text(
            f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

state_path = Path({str(state_file)!r})
log_path = Path({str(cmd_log)!r})
args = sys.argv[1:]
with log_path.open("a", encoding="utf-8") as lf:
    lf.write("{tool_name} " + " ".join(args) + "\\n")

state = json.loads(state_path.read_text(encoding="utf-8"))
if not args:
    sys.exit(0)

op = args[0]
chain = args[1] if len(args) > 1 else ""
rest = args[2:]

if op == "-N":
    state.setdefault(chain, [])
elif op == "-F":
    if chain not in state:
        sys.exit(1)
    state[chain] = []
elif op == "-X":
    state.pop(chain, None)
elif op == "-A":
    if chain not in state:
        sys.exit(1)
    state[chain].append(" ".join(rest))
elif op == "-I":
    if chain not in state:
        sys.exit(1)
    pos = 1
    rule_parts = rest
    if rest and rest[0].isdigit():
        pos = int(rest[0])
        rule_parts = rest[1:]
    state[chain].insert(max(0, pos - 1), " ".join(rule_parts))
elif op == "-D":
    if chain not in state:
        sys.exit(1)
    rule = " ".join(rest)
    if rule not in state[chain]:
        sys.exit(1)
    state[chain].remove(rule)
elif op == "-C":
    if chain not in state:
        sys.exit(1)
    rule = " ".join(rest)
    sys.exit(0 if rule in state[chain] else 1)
elif op == "-S":
    if chain not in state:
        sys.exit(1)
    print(f"-N {{chain}}")
    for r in state[chain]:
        print(f"-A {{chain}} {{r}}")
elif op == "-L":
    if chain not in state:
        sys.exit(1)
else:
    sys.exit(0)

state_path.write_text(json.dumps(state), encoding="utf-8")
""",
            encoding="utf-8",
        )
        shim.chmod(0o755)


def test_upgrade_host_preexisting_imds_only_orders_imds_before_egress(tmp_path: Path) -> None:
    """Upgrading a host with pre-existing BRAINSOS-IMDS keeps #1 IMDS, #2 EGRESS in DOCKER-USER."""
    import json

    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_APPLIANCE=true\n"
        "BRAINSOS_LITELLM_STATIC_IP=172.28.2.10\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(
        bin_dir,
        state_dir,
        cmd_log,
        initial_v4={
            "DOCKER-USER": ["-d 169.254.169.254/32 -j BRAINSOS-IMDS", "-j RETURN"],
            "BRAINSOS-IMDS": ["-s 172.28.2.10/32 -j RETURN", "-j DROP"],
        },
        initial_v6={
            "DOCKER-USER": ["-d fd00:ec2::254/128 -j BRAINSOS-IMDS6"],
            "BRAINSOS-IMDS6": ["-j DROP"],
        },
    )
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    dry_proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--dry-run", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry_proc.returncode == 0, dry_proc.stdout + dry_proc.stderr
    dry_lines = dry_proc.stdout.splitlines()
    assert "iptables -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS" in dry_lines
    egress_idx = dry_lines.index("iptables -I DOCKER-USER 1 -i br-internal -j BRAINSOS-EGRESS")
    imds_idx = dry_lines.index("iptables -I DOCKER-USER 1 -d 169.254.169.254/32 -j BRAINSOS-IMDS")
    assert egress_idx < imds_idx

    apply_proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply_proc.returncode == 0, apply_proc.stdout + apply_proc.stderr

    v4_state = json.loads((state_dir / "iptables.json").read_text(encoding="utf-8"))
    v6_state = json.loads((state_dir / "ip6tables.json").read_text(encoding="utf-8"))
    assert v4_state["DOCKER-USER"][:2] == [
        "-d 169.254.169.254/32 -j BRAINSOS-IMDS",
        "-i br-internal -j BRAINSOS-EGRESS",
    ]
    assert "-i docker0 -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL" in v4_state["DOCKER-USER"]
    assert v4_state["DOCKER-USER"][-1] == "-j RETURN"
    assert v4_state["BRAINSOS-LINKLOCAL"] == [
        "-s 172.28.2.10/32 -d 169.254.169.254/32 -j RETURN",
        "-d 169.254.0.0/16 -j DROP",
    ]
    assert v6_state["DOCKER-USER"] == [
        "-d fd00:ec2::254/128 -j BRAINSOS-IMDS6",
        "-i br-internal -j BRAINSOS-EGRESS6",
    ]

    check_proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--check", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check_proc.returncode == 0, check_proc.stdout + check_proc.stderr


def test_check_fails_and_apply_heals_misordered_docker_user_rules(tmp_path: Path) -> None:
    """--check fails when BRAINSOS-EGRESS precedes BRAINSOS-IMDS (or IMDS drop missing), and --apply self-heals order."""
    import json

    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_APPLIANCE=true\n"
        "BRAINSOS_LITELLM_STATIC_IP=172.28.2.10\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(
        bin_dir,
        state_dir,
        cmd_log,
        initial_v4={
            "DOCKER-USER": [
                "-i br-internal -j BRAINSOS-EGRESS",
                "-d 169.254.169.254/32 -j BRAINSOS-IMDS",
            ],
            "BRAINSOS-IMDS": ["-s 172.28.2.10/32 -j RETURN", "-j DROP"],
            "BRAINSOS-EGRESS": [
                "-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN",
                "-o br-internal -j RETURN",
                "-d 169.254.0.0/16 -j DROP",
                "-s 172.28.1.2/32 -j RETURN",
                "-j DROP",
            ],
        },
        initial_v6={
            "DOCKER-USER": [
                "-i br-internal -j BRAINSOS-EGRESS6",
                "-d fd00:ec2::254/128 -j BRAINSOS-IMDS6",
            ],
            "BRAINSOS-IMDS6": ["-j DROP"],
            "BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-j DROP"],
        },
    )
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    bad_check = subprocess.run(
        ["bash", str(IMDS_GUARD), "--check", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_check.returncode == 1
    assert "order/uniqueness invalid" in bad_check.stderr

    heal_proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert heal_proc.returncode == 0, heal_proc.stdout + heal_proc.stderr

    v4_state = json.loads((state_dir / "iptables.json").read_text(encoding="utf-8"))
    v6_state = json.loads((state_dir / "ip6tables.json").read_text(encoding="utf-8"))
    assert v4_state["DOCKER-USER"][:2] == [
        "-d 169.254.169.254/32 -j BRAINSOS-IMDS",
        "-i br-internal -j BRAINSOS-EGRESS",
    ]
    assert "-i docker0 -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL" in v4_state["DOCKER-USER"]
    assert v6_state["DOCKER-USER"] == [
        "-d fd00:ec2::254/128 -j BRAINSOS-IMDS6",
        "-i br-internal -j BRAINSOS-EGRESS6",
    ]

    ok_check = subprocess.run(
        ["bash", str(IMDS_GUARD), "--check", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok_check.returncode == 0, ok_check.stdout + ok_check.stderr


def test_stateful_apply_re_run_is_noop_when_ordered(tmp_path: Path) -> None:
    """Re-running imds-guard.sh --apply on an ordered stateful host emits zero DOCKER-USER mutations."""
    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(bin_dir, state_dir, cmd_log)
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    first = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr

    cmd_log.write_text("", encoding="utf-8")
    second = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stdout + second.stderr

    logged = cmd_log.read_text(encoding="utf-8").splitlines()
    assert not any("-I DOCKER-USER" in ln or "-D DOCKER-USER" in ln for ln in logged)

    check_proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--check", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check_proc.returncode == 0, check_proc.stdout + check_proc.stderr


def test_br_internal_imds_traffic_allowed_for_authorized_ips_and_dropped_for_others(tmp_path: Path) -> None:
    """Finding 2A: br-internal IMDS traffic from Caddy (route53) and LiteLLM is NOT dropped by BRAINSOS-EGRESS."""
    import ipaddress
    import json

    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_APPLIANCE=true\n"
        "BRAINSOS_TLS_MODE=route53\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(
        bin_dir,
        state_dir,
        cmd_log,
        docker_litellm_ip="172.28.2.10 172.28.1.11",
    )
    # Override docker shim so caddy returns both ingress and internal IPs
    docker_shim = bin_dir / "docker"
    docker_shim.write_text(
        """#!/usr/bin/env bash
case "$*" in
  *"com.docker.network.bridge.name"*) echo "br-internal" ;;
  *"NetworkSettings.Networks}}{{.IPAddress}}"*"brainsos-control-litellm"*) echo "172.28.2.10 172.28.1.11" ;;
  *"NetworkSettings.Networks}}{{.IPAddress}}"*"brainsos-ingress-caddy"*) echo "172.28.0.10 172.28.1.10" ;;
  *"brainsos-control-litellm"*) echo "172.28.1.11" ;;
  *"brainsos-agent-egress-proxy"*) echo "172.28.1.2" ;;
  *"brainsos-ingress-caddy"*) echo "172.28.1.10" ;;
  *) echo "" ;;
esac
""",
        encoding="utf-8",
    )
    docker_shim.chmod(0o755)
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.run(
        ["bash", str(IMDS_GUARD), "--apply", "--force"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    v4_state = json.loads((state_dir / "iptables.json").read_text(encoding="utf-8"))
    egress = v4_state["BRAINSOS-EGRESS"]
    drop_ll_idx = egress.index("-d 169.254.0.0/16 -j DROP")
    assert egress.index("-s 172.28.1.11/32 -d 169.254.169.254/32 -j RETURN") < drop_ll_idx
    assert egress.index("-s 172.28.1.10/32 -d 169.254.169.254/32 -j RETURN") < drop_ll_idx
    assert "-s 172.28.1.2/32 -d 169.254.169.254/32 -j RETURN" not in egress

    def eval_chain(chain_name: str, *, in_if: str, out_if: str, src: str, dst: str) -> str:
        src_ip = ipaddress.ip_address(src)
        dst_ip = ipaddress.ip_address(dst)
        for rule in v4_state[chain_name]:
            tokens = rule.split()
            matched = True
            target = ""
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok == "-s":
                    if src_ip not in ipaddress.ip_network(tokens[i + 1], strict=False):
                        matched = False
                        break
                    i += 2
                elif tok == "-d":
                    if dst_ip not in ipaddress.ip_network(tokens[i + 1], strict=False):
                        matched = False
                        break
                    i += 2
                elif tok == "-i":
                    if in_if != tokens[i + 1]:
                        matched = False
                        break
                    i += 2
                elif tok == "-o":
                    if out_if != tokens[i + 1]:
                        matched = False
                        break
                    i += 2
                elif tok == "-m":
                    # new-connection probe does not match ESTABLISHED,RELATED
                    matched = False
                    break
                elif tok == "-j":
                    target = tokens[i + 1]
                    i += 2
                else:
                    i += 1
            if not matched:
                continue
            if target in ("DROP", "ACCEPT"):
                return target
            if target == "RETURN":
                return "RETURN"
            res = eval_chain(target, in_if=in_if, out_if=out_if, src=src, dst=dst)
            if res != "RETURN":
                return res
        return "RETURN"

    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.11", dst="169.254.169.254") == "RETURN"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.10", dst="169.254.169.254") == "RETURN"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.2", dst="169.254.169.254") == "DROP"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.20", dst="169.254.169.254") == "DROP"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.11", dst="169.254.1.1") == "DROP"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.20", dst="1.1.1.1") == "DROP"
    assert eval_chain("DOCKER-USER", in_if="br-internal", out_if="eth0", src="172.28.1.2", dst="1.1.1.1") == "RETURN"

    ok_check = subprocess.run(["bash", str(IMDS_GUARD), "--check", "--force"], env=env, capture_output=True, text=True, check=False)
    assert ok_check.returncode == 0, ok_check.stdout + ok_check.stderr

    # Moving IMDS exemption after link-local DROP must fail --check
    rule = "-s 172.28.1.10/32 -d 169.254.169.254/32 -j RETURN"
    v4_state["BRAINSOS-EGRESS"].remove(rule)
    v4_state["BRAINSOS-EGRESS"].insert(v4_state["BRAINSOS-EGRESS"].index("-d 169.254.0.0/16 -j DROP") + 1, rule)
    (state_dir / "iptables.json").write_text(json.dumps(v4_state), encoding="utf-8")
    bad_order_check = subprocess.run(["bash", str(IMDS_GUARD), "--check", "--force"], env=env, capture_output=True, text=True, check=False)
    assert bad_order_check.returncode == 1


def test_check_rejects_tampered_ipv6_imds_and_egress_chains(tmp_path: Path) -> None:
    """Finding 2B: --check rejects fail-open or missing rules inside BRAINSOS-IMDS6 and BRAINSOS-EGRESS6."""
    import json

    env_file = tmp_path / ".env"
    env_file.write_text("BRAINSOS_APPLIANCE=true\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(bin_dir, state_dir, cmd_log)
    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    assert subprocess.run(["bash", str(IMDS_GUARD), "--apply", "--force"], env=env, check=False).returncode == 0
    assert subprocess.run(["bash", str(IMDS_GUARD), "--check", "--force"], env=env, check=False).returncode == 0

    baseline_v6: dict[str, list[str]] = json.loads((state_dir / "ip6tables.json").read_text(encoding="utf-8"))
    tamper_cases: list[dict[str, list[str]]] = [
        {"BRAINSOS-IMDS6": ["-j ACCEPT"]},
        {"BRAINSOS-IMDS6": ["-j ACCEPT", "-j DROP"]},
        {"BRAINSOS-IMDS6": ["-j RETURN", "-j DROP"]},
        {"BRAINSOS-IMDS6": []},
        {"BRAINSOS-EGRESS6": ["-j ACCEPT"]},
        {"BRAINSOS-EGRESS6": ["-j ACCEPT", "-o br-internal -j RETURN", "-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-j RETURN", "-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-s ::/0 -j RETURN", "-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-i br-internal -j RETURN", "-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-p tcp -j RETURN", "-j DROP"]},
        {"BRAINSOS-EGRESS6": ["-o br-internal -j RETURN", "-d ::/0 -j RETURN", "-j DROP"]},
    ]
    for patch in tamper_cases:
        mutated = {**baseline_v6, **patch}
        (state_dir / "ip6tables.json").write_text(json.dumps(mutated), encoding="utf-8")
        res = subprocess.run(
            ["bash", str(IMDS_GUARD), "--check", "--force"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1, f"Expected --check failure for {patch}, got rc=0"

    # Canonical kernel ip6tables -S ordering (RELATED,ESTABLISHED) must pass --check
    canonical_v6 = {
        **baseline_v6,
        "BRAINSOS-EGRESS6": [
            "-m conntrack --ctstate RELATED,ESTABLISHED -j RETURN",
            "-o br-internal -j RETURN",
            "-j DROP",
        ],
    }
    (state_dir / "ip6tables.json").write_text(json.dumps(canonical_v6), encoding="utf-8")
    assert (
        subprocess.run(
            ["bash", str(IMDS_GUARD), "--check", "--force"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )

    # Re-applying heals tampered IPv6 chains
    assert subprocess.run(["bash", str(IMDS_GUARD), "--apply", "--force"], env=env, check=False).returncode == 0
    assert subprocess.run(["bash", str(IMDS_GUARD), "--check", "--force"], env=env, check=False).returncode == 0


def test_linklocal_guard_protects_sandbox_and_docker0_bridges(tmp_path: Path) -> None:
    """#406 INFO-1: BRAINSOS-LINKLOCAL drops 169.254.0.0/16 (incl. 169.254.170.2) across br-sandbox, brainsos-*-net, and docker0."""
    import json

    env_file = tmp_path / ".env"
    env_file.write_text(
        "BRAINSOS_APPLIANCE=true\n"
        "BRAINSOS_LITELLM_STATIC_IP=172.28.2.10\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    cmd_log = tmp_path / "ipt.log"
    _make_stateful_shims(bin_dir, state_dir, cmd_log)

    # Override docker shim to report distinct bridge names per network
    (bin_dir / "docker").write_text(
        """#!/usr/bin/env bash
case "$*" in
  *"network ls"*) printf 'brainsos-internal-net\\nbrainsos-sandbox-net\\nbrainsos-ingress-net\\n' ;;
  *"network inspect"*brainsos-internal-net*) echo "br-internal" ;;
  *"network inspect"*brainsos-sandbox-net*) echo "br-sandbox" ;;
  *"network inspect"*brainsos-ingress-net*) echo "br-ingress" ;;
  *"brainsos-control-litellm"*) echo "172.28.2.10" ;;
  *"brainsos-agent-egress-proxy"*) echo "172.28.1.2" ;;
  *"brainsos-ingress-caddy"*) echo "172.28.1.10" ;;
  *) echo "" ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "docker").chmod(0o755)

    env = {
        **os.environ,
        "BRAINSOS_ENV_FILE": str(env_file),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    res = subprocess.run(["bash", str(IMDS_GUARD), "--apply", "--force"], env=env, capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stdout + res.stderr

    v4_state = json.loads((state_dir / "iptables.json").read_text(encoding="utf-8"))
    assert v4_state["BRAINSOS-LINKLOCAL"] == [
        "-s 172.28.2.10/32 -d 169.254.169.254/32 -j RETURN",
        "-d 169.254.0.0/16 -j DROP",
    ]
    for br in ("br-sandbox", "br-ingress", "docker0"):
        assert f"-i {br} -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL" in v4_state["DOCKER-USER"]
    assert subprocess.run(["bash", str(IMDS_GUARD), "--check", "--force"], env=env, capture_output=True, text=True, check=False).returncode == 0



