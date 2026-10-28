"""Tests for brainsos-appliance command-line interface."""

import subprocess

from brainsos_appliance import builder
from brainsos_appliance.cli import create_parser, main


def test_cli_parser_creation():
    """Verify CLI parser has all required subcommands."""
    parser = create_parser()
    subparsers_actions = [
        action for action in parser._actions if action.dest == "command"
    ]
    assert len(subparsers_actions) == 1
    choices = subparsers_actions[0].choices
    assert "validate" in choices
    assert "build" in choices
    assert "status" in choices
    assert "audit" in choices


def test_cli_validate_command():
    """Verify 'brainsos-appliance validate' exits with 0."""
    code = main(["validate"])
    assert code == 0


def test_cli_build_dry_run_delegates_to_build_ami_sh(monkeypatch):
    """'brainsos-appliance build' must delegate to scripts/control/build-ami.sh."""
    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    code = main(["build", "--dry-run", "--region", "eu-west-1", "--ref", "v0.1.0", "--allow-dirty"])
    assert code == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0].endswith("scripts/control/build-ami.sh")
    assert cmd[cmd.index("--region") + 1] == "eu-west-1"
    assert cmd[cmd.index("--ref") + 1] == "v0.1.0"
    assert "--allow-dirty" in cmd and "--dry-run" in cmd


def test_cli_build_promote_command():
    cmd = builder.build_ami_command(region="us-west-2", promote="ami-0123456789abcdef0")
    assert cmd[1:] == ["--region", "us-west-2", "--promote", "ami-0123456789abcdef0"]


def test_cli_status_command():
    """Verify 'brainsos-appliance status' and '--json' exit with 0."""
    assert main(["status"]) == 0
    assert main(["status", "--json"]) == 0


def test_cli_audit_command():
    """Verify 'brainsos-appliance audit' and '--json' exit with 0."""
    assert main(["audit"]) == 0
    assert main(["audit", "--json"]) == 0
