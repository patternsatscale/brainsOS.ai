"""Tests for Meeting-Screenshot Bulk Fleet Launcher Skill & CLI (Ticket #377)."""

import os
import subprocess
from pathlib import Path

from brainsos_skills.validator import validate_skill_file

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCH_FLEET_SH = REPO_ROOT / "scripts" / "control" / "launch-fleet.sh"
WORKSPACE_SKILL = REPO_ROOT / ".agents" / "skills" / "launch-fleet" / "SKILL.md"
DEFAULT_SKILL = REPO_ROOT / "config" / "default_skills" / "launch-fleet" / "SKILL.md"
BUNDLED_SKILL = (
    REPO_ROOT
    / "packages"
    / "brainsOS-skills"
    / "brainsos_skills"
    / "bundled"
    / "launch-fleet"
    / "SKILL.md"
)


def test_launch_fleet_skill_files_exist_and_validate():
    """Verify .agents/skills, config/default_skills, and bundled SKILL.md exist without symlinks and validate."""
    for path in (WORKSPACE_SKILL, DEFAULT_SKILL, BUNDLED_SKILL):
        assert path.is_file(), f"Missing skill file: {path}"
        assert not path.is_symlink(), f"Symlinks are forbidden by Rule 8: {path}"
        valid, msg, skill = validate_skill_file(path)
        assert valid, f"Skill validation failed for {path}: {msg}"
        assert skill is not None
        assert skill.name == "launch-fleet"
        assert skill.matches_trigger("/launch-fleet")


def test_launch_fleet_dry_run_sanitizes_ui_noise_and_disambiguates_collisions():
    """Verify Zoom/Meet UI chrome stripping, duplicate first-name disambiguation, and reserved slug avoidance."""
    proc = subprocess.run(
        [
            str(LAUNCH_FLEET_SH),
            "--participants",
            "Alice Morgan (Host), Alex Chen (You), Alex Rivera, Alex Clark, Admin User, custombox=Dr. Jean-Luc Picard",
            "--base-domain",
            "demo.infotechlabs.io",
            "--fleet",
            "test-fleet-01",
            "--no-ensure-iam-ddns",
        ],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout
    assert "https://alice.demo.infotechlabs.io" in out
    assert "https://alexc.demo.infotechlabs.io" in out
    assert "https://alexr.demo.infotechlabs.io" in out
    assert "https://alex-clark.demo.infotechlabs.io" in out
    assert "https://adminu.demo.infotechlabs.io" in out
    assert "https://custombox.demo.infotechlabs.io" in out
    # Ensure raw "(Host)" and "(You)" were stripped from participant display names
    assert "(Host)" not in out
    assert "(You)" not in out


def test_launch_fleet_emit_script_generates_valid_self_contained_bash(tmp_path):
    """Verify --emit-script outputs a syntactically valid bash script with embedded roster and User-Data."""
    emitted = tmp_path / "cloudshell-launch.sh"
    proc = subprocess.run(
        [
            str(LAUNCH_FLEET_SH),
            "--participants",
            "Alice Morgan, Bob Patel",
            "--base-domain",
            "demo.infotechlabs.io",
            "--zone-id",
            "arn:aws:route53:::hostedzone/Z09988776655TEST",
            "--ami",
            "ami-0eac84eb9a9415531",
            "--fleet",
            "demo-cloudshell",
            "--hibernation-capable",
            "--emit-script",
            str(emitted),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert emitted.is_file()
    assert os.access(emitted, os.X_OK)

    syntax = subprocess.run(["bash", "-n", str(emitted)], capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr

    body = emitted.read_text()
    assert 'ZONE_ID="Z09988776655TEST"' in body
    assert 'AMI_ID="ami-0eac84eb9a9415531"' in body
    assert 'HIBERNATION_CAPABLE="true"' in body
    assert "alice|Alice Morgan" in body or "alice\\|Alice\\ Morgan" in body
    assert "route53_zone_id: ${ZONE_ID}" in body
    assert "brainsos-fleet-https-sg" in body


def test_launch_fleet_apply_with_mock_aws_cli_produces_roster_md_and_csv(tmp_path):
    """Verify --apply executes end-to-end against mocked AWS CLI and writes Markdown + CSV handoff rosters."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    counter_file = tmp_path / "counter"
    counter_file.write_text("0")

    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo "066683141917"; exit 0; fi\n'
        'if [[ "$*" == *"list-hosted-zones-by-name"* ]]; then echo "/hostedzone/Z1234567890MOCK"; exit 0; fi\n'
        'if [[ "$*" == *"describe-images"* ]]; then echo "ami-0eac84eb9a9415531"; exit 0; fi\n'
        'if [[ "$*" == *"get-instance-profile"* ]]; then echo "instanceRoleBedrock"; exit 0; fi\n'
        'if [[ "$*" == *"put-role-policy"* ]]; then exit 0; fi\n'
        'if [[ "$*" == *"describe-vpcs"* ]]; then echo "vpc-0123456789"; exit 0; fi\n'
        'if [[ "$*" == *"describe-security-groups"* ]]; then echo "sg-0123456789"; exit 0; fi\n'
        'if [[ "$*" == *"run-instances"* ]]; then\n'
        f'  c=$(cat "{counter_file}")\n'
        '  c=$((c + 1))\n'
        f'  echo "$c" > "{counter_file}"\n'
        '  printf "i-0000000000000000%d\\n" "$c"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    fake_aws.chmod(0o755)

    roster_prefix = tmp_path / "handoff" / "workshop"
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    proc = subprocess.run(
        [
            str(LAUNCH_FLEET_SH),
            "--participants",
            "Alice Morgan, Bob Patel",
            "--base-domain",
            "demo.infotechlabs.io",
            "--fleet",
            "workshop-mock",
            "--roster-out",
            str(roster_prefix),
            "--apply",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    md_file = Path(f"{roster_prefix}.md")
    csv_file = Path(f"{roster_prefix}.csv")
    assert md_file.is_file()
    assert csv_file.is_file()

    md_text = md_file.read_text()
    assert "| Alice Morgan | https://alice.demo.infotechlabs.io | `i-00000000000000001` |" in md_text
    assert "| Bob Patel | https://bob.demo.infotechlabs.io | `i-00000000000000002` |" in md_text

    csv_text = csv_file.read_text()
    assert '"Alice Morgan","https://alice.demo.infotechlabs.io","i-00000000000000001"' in csv_text


def test_launch_fleet_day2_terminate_requires_yes_confirmation(tmp_path):
    """Verify --terminate refuses destructive teardown without --yes and requires --fleet."""
    # 1. Missing --fleet rejected
    proc_no_fleet = subprocess.run(
        [str(LAUNCH_FLEET_SH), "--terminate"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_no_fleet.returncode != 0
    assert "requires --fleet" in proc_no_fleet.stderr

    # 2. With --fleet but without --yes rejected at safety gate
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo "066683141917"; exit 0; fi\n'
        'if [[ "$*" == *"describe-instances"* ]]; then printf "i-0abc111\\ti-0abc222\\n"; exit 0; fi\n'
        'if [[ "$*" == *"terminate-instances"* ]]; then echo "TERMINATED"; exit 0; fi\n'
        "exit 0\n"
    )
    fake_aws.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}

    proc_gate = subprocess.run(
        [str(LAUNCH_FLEET_SH), "--terminate", "--fleet", "workshop-mock"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_gate.returncode != 0
    assert "[SAFETY GATE]" in proc_gate.stderr

    # 3. With --yes succeeds
    proc_ok = subprocess.run(
        [str(LAUNCH_FLEET_SH), "--terminate", "--fleet", "workshop-mock", "--yes"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_ok.returncode == 0, proc_ok.stderr
    assert "Terminated 2 instance(s)" in proc_ok.stderr
