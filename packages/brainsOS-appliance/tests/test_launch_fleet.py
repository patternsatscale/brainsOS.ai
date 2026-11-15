"""Tests for Standalone Interactive Launch-Template Fleet Wizard & CLI (Tickets #377 / #380)."""

import base64
import json
import os
import shutil
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


def _write_mock_aws(bin_dir: Path, counter_file: Path, calls_log: Path) -> Path:
    """Create a mock AWS CLI supporting STS, Route 53, EC2 Launch Templates, AMIs, and RunInstances."""
    lt_userdata_b64 = base64.b64encode(
        b"#cloud-config\nBRAINSOS_BASE_DOMAIN=demo.infotechlabs.io\n"
    ).decode("ascii")

    lt_list_json = json.dumps(
        {
            "LaunchTemplates": [
                {
                    "LaunchTemplateId": "lt-0123456789abcdef0",
                    "LaunchTemplateName": "brainsos-demo-template",
                    "CreateTime": "2026-11-14T12:00:00Z",
                    "DefaultVersionNumber": 1,
                    "LatestVersionNumber": 2,
                }
            ]
        }
    )
    lt_ver_json = json.dumps(
        {
            "LaunchTemplateVersions": [
                {
                    "LaunchTemplateId": "lt-0123456789abcdef0",
                    "LaunchTemplateName": "brainsos-demo-template",
                    "VersionNumber": 2,
                    "LaunchTemplateData": {
                        "ImageId": "ami-03941c398c47dabb1",
                        "InstanceType": "m7g.xlarge",
                        "IamInstanceProfile": {"Name": "instanceRoleBedrock"},
                        "NetworkInterfaces": [{"DeviceIndex": 0, "AssociatePublicIpAddress": True}],
                        "UserData": lt_userdata_b64,
                        "TagSpecifications": [
                            {
                                "ResourceType": "instance",
                                "Tags": [{"Key": "Environment", "Value": "DemoAccount"}],
                            }
                        ],
                    },
                }
            ]
        }
    )
    zones_json = json.dumps(
        {
            "HostedZones": [
                {
                    "Id": "/hostedzone/Z1234567890MOCK",
                    "Name": "infotechlabs.io.",
                    "Config": {"PrivateZone": False},
                }
            ]
        }
    )
    sts_json = json.dumps(
        {
            "Account": "066683141917",
            "Arn": "arn:aws:iam::066683141917:user/work-operator",
        }
    )

    fake_aws = bin_dir / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'FLAT_ARGS="${*//$\'\\n\'/ }"\n'
        f'printf "%s\\n" "$FLAT_ARGS" >> "{calls_log}"\n'
        'if [[ "$*" == *"configure get region"* ]]; then echo "us-east-1"; exit 0; fi\n'
        f"if [[ \"$*\" == *\"sts get-caller-identity\"* ]]; then printf '%s\\n' '{sts_json}'; exit 0; fi\n"
        f"if [[ \"$*\" == *\"ec2 describe-launch-templates\"* ]]; then printf '%s\\n' '{lt_list_json}'; exit 0; fi\n"
        f"if [[ \"$*\" == *\"ec2 describe-launch-template-versions\"* ]]; then printf '%s\\n' '{lt_ver_json}'; exit 0; fi\n"
        f"if [[ \"$*\" == *\"route53 list-hosted-zones \"* ]] || [[ \"$*\" == *\"route53 list-hosted-zones\" ]]; then printf '%s\\n' '{zones_json}'; exit 0; fi\n"
        'if [[ "$*" == *"list-hosted-zones-by-name"* ]]; then echo "/hostedzone/Z1234567890MOCK"; exit 0; fi\n'
        'if [[ "$*" == *"describe-images"* ]]; then echo "ami-03941c398c47dabb1"; exit 0; fi\n'
        'if [[ "$*" == *"get-instance-profile"* ]]; then echo "instanceRoleBedrock"; exit 0; fi\n'
        'if [[ "$*" == *"put-role-policy"* ]]; then exit 0; fi\n'
        'if [[ "$*" == *"describe-vpcs"* ]]; then echo "vpc-0123456789"; exit 0; fi\n'
        'if [[ "$*" == *"describe-security-groups"* ]]; then echo "sg-0123456789"; exit 0; fi\n'
        'if [[ "$*" == *"run-instances"* ]]; then\n'
        f'  c=$(cat "{counter_file}")\n'
        "  c=$((c + 1))\n"
        f'  echo "$c" > "{counter_file}"\n'
        '  printf "i-0000000000000000%d\\n" "$c"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    fake_aws.chmod(0o755)
    return fake_aws


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


def test_launch_fleet_dry_run_sanitizes_ui_noise_and_disambiguates_collisions(tmp_path):
    """Verify standalone execution outside repo, UI chrome stripping, and collision disambiguation."""
    standalone = tmp_path / "launch-fleet.sh"
    shutil.copy2(LAUNCH_FLEET_SH, standalone)

    proc = subprocess.run(
        [
            str(standalone),
            "--participants",
            "Alice Morgan (Host), Alex Chen (You), Alex Rivera, Alex Clark, Admin User, custombox=Dr. Jean-Luc Picard",
            "--base-domain",
            "demo.infotechlabs.io",
            "--fleet",
            "test-fleet-01",
            "--dry-run",
        ],
        cwd=str(tmp_path),
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
    assert "(Host)" not in out
    assert "(You)" not in out


def test_launch_fleet_emit_script_generates_valid_self_contained_bash(tmp_path):
    """Verify --emit-script outputs a syntactically valid standalone bash bundle."""
    emitted = tmp_path / "laptop-bundle.sh"
    proc = subprocess.run(
        [
            str(LAUNCH_FLEET_SH),
            "--launch-template",
            "brainsos-demo-template",
            "--participants",
            "Alice Morgan, Bob Patel",
            "--base-domain",
            "demo.infotechlabs.io",
            "--zone-id",
            "arn:aws:route53:::hostedzone/Z09988776655TEST",
            "--fleet",
            "demo-bundle",
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
    assert "brainsos-demo-template" in body
    assert "Z09988776655TEST" in body
    assert "alice=Alice Morgan" in body


def test_launch_template_and_count_cli_mode_preserves_lt_networking_and_tags(tmp_path):
    """Verify --launch-template + --count launches numbered instances without conflicting --security-group-ids."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    counter = tmp_path / "counter"
    counter.write_text("0")
    calls = tmp_path / "aws_calls.log"
    calls.write_text("")
    _write_mock_aws(fake_bin, counter, calls)

    standalone = tmp_path / "launch-fleet.sh"
    shutil.copy2(LAUNCH_FLEET_SH, standalone)
    roster_prefix = tmp_path / "out" / "lab"

    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        [
            str(standalone),
            "--launch-template",
            "brainsos-demo-template",
            "--count",
            "3",
            "--prefix",
            "lab",
            "--base-domain",
            "demo.infotechlabs.io",
            "--fleet",
            "lt-batch-01",
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

    md_text = Path(f"{roster_prefix}.md").read_text()
    assert "| Lab 01 | https://lab01.demo.infotechlabs.io | `i-00000000000000001` |" in md_text
    assert "| Lab 02 | https://lab02.demo.infotechlabs.io | `i-00000000000000002` |" in md_text
    assert "| Lab 03 | https://lab03.demo.infotechlabs.io | `i-00000000000000003` |" in md_text

    run_calls = [ln for ln in calls.read_text().splitlines() if "run-instances" in ln]
    assert len(run_calls) == 3
    for rc in run_calls:
        assert "LaunchTemplateId=lt-0123456789abcdef0,Version=$Latest" in rc
        # Must NOT pass --security-group-ids when Launch Template owns NetworkInterfaces
        assert "--security-group-ids" not in rc
        # Must preserve existing Launch Template tag ("Environment": "DemoAccount")
        assert "DemoAccount" in rc


def test_interactive_wizard_picks_launch_template_launches_and_exits_cleanly(tmp_path):
    """Verify running ./launch-fleet.sh with zero args walks through the Launch Template wizard and exits on 'q'."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    counter = tmp_path / "counter"
    counter.write_text("0")
    calls = tmp_path / "aws_calls.log"
    calls.write_text("")
    _write_mock_aws(fake_bin, counter, calls)

    standalone = tmp_path / "launch-fleet.sh"
    shutil.copy2(LAUNCH_FLEET_SH, standalone)

    # Interactive stdin answers:
    # 1 -> Menu [1] Launch New Appliance Fleet
    # 1 -> Pick Launch Template [1] brainsos-demo-template
    # <Enter> -> Accept $Latest version
    # <Enter> -> Accept auto-suggested demo.infotechlabs.io
    # 2 -> Create 2 instances
    # user -> Prefix 'user' (user01, user02)
    # wizard-demo-01 -> Fleet tag ID
    # y -> Confirm launch
    # q -> Exit cleanly after launch
    wizard_stdin = "\n".join(["1", "1", "", "", "2", "user", "wizard-demo-01", "y", "q"]) + "\n"

    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        [str(standalone)],  # Zero arguments -> auto-enters interactive wizard!
        cwd=str(tmp_path),
        env=env,
        input=wizard_stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert (tmp_path / "wizard-demo-01-roster.md").is_file()
    assert (tmp_path / "wizard-demo-01-roster.csv").is_file()
    roster = (tmp_path / "wizard-demo-01-roster.md").read_text()
    assert "https://user01.demo.infotechlabs.io" in roster
    assert "https://user02.demo.infotechlabs.io" in roster
    assert "Exiting brainsOS Fleet Utility. Goodbye!" in proc.stderr


def test_interactive_wizard_immediate_quit(tmp_path):
    """Verify typing 'q' at the very first prompt exits immediately with code 0."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_mock_aws(fake_bin, tmp_path / "c", tmp_path / "l")
    (tmp_path / "c").write_text("0")
    (tmp_path / "l").write_text("")

    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        [str(LAUNCH_FLEET_SH), "--wizard"],
        cwd=str(tmp_path),
        env=env,
        input="q\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Goodbye!" in proc.stderr


def test_launch_fleet_day2_terminate_requires_yes_confirmation(tmp_path):
    """Verify --terminate refuses destructive teardown without --yes and requires --fleet."""
    proc_no_fleet = subprocess.run(
        [str(LAUNCH_FLEET_SH), "--terminate"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_no_fleet.returncode != 0
    assert "requires --fleet" in proc_no_fleet.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"sts get-caller-identity"* ]]; then echo \'{"Account":"066683141917","Arn":"arn:aws:iam::066683141917:user/op"}\'; exit 0; fi\n'
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
