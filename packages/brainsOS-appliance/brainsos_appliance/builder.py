"""Packer AMI build engine and template validation for brainsOS appliance."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_packer_binary() -> Optional[str]:
    """Find the Packer executable in PATH or virtualenv."""
    bin_in_path = shutil.which("packer")
    if bin_in_path:
        return bin_in_path

    # Check repository virtualenv or common locations
    candidate_paths = [
        Path(__file__).resolve().parents[3] / ".venv" / "bin" / "packer",
        Path.home() / ".local" / "bin" / "packer",
        Path("/usr/local/bin/packer"),
        Path("/usr/bin/packer"),
    ]
    for p in candidate_paths:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def get_packer_dir() -> Path:
    """Resolve the directory containing Packer HCL templates."""
    return Path(__file__).resolve().parent.parent / "packer"


def get_build_script() -> Path:
    """Resolve the canonical AMI build wrapper (scripts/control/build-ami.sh)."""
    return Path(__file__).resolve().parents[3] / "scripts" / "control" / "build-ami.sh"


def validate_packer_templates(packer_dir: Optional[Path] = None) -> Tuple[bool, str]:
    """Run 'packer validate' on the appliance Packer templates.

    ``source_dir`` is a required template variable (the git-staged artifact);
    an empty temporary directory is supplied because validation does not
    upload anything.
    """
    packer_bin = find_packer_binary()
    if not packer_bin:
        return False, "Packer executable not found in PATH or .venv/bin/packer."

    target_dir = packer_dir or get_packer_dir()
    if not target_dir.exists():
        return False, f"Packer template directory not found: {target_dir}"

    try:
        with tempfile.TemporaryDirectory(prefix="brainsos-ami-validate-") as stage:
            cmd = [packer_bin, "validate", f"-var=source_dir={stage}", str(target_dir)]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        output = proc.stdout.strip() or proc.stderr.strip()
        return (proc.returncode == 0, output)
    except Exception as exc:
        return False, f"Failed to execute packer validate: {exc}"


def check_aws_context() -> Dict[str, Any]:
    """Inspect environment for AWS configuration and credentials."""
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    has_env_creds = bool(
        os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    has_profile = bool(os.environ.get("AWS_PROFILE"))
    return {
        "region": region,
        "has_env_credentials": has_env_creds,
        "has_profile": has_profile,
        "aws_profile": os.environ.get("AWS_PROFILE", "default"),
    }


def build_ami_command(
    region: str = "us-east-1",
    publish_community: bool = False,
    instance_type: str = "c7g.xlarge",
    volume_size: int = 50,
    dry_run: bool = False,
    ref: Optional[str] = None,
    allow_dirty: bool = False,
    promote: Optional[str] = None,
) -> List[str]:
    """Compose the build-ami.sh invocation for the requested options."""
    cmd = [str(get_build_script()), "--region", region]
    if promote:
        cmd += ["--promote", promote]
    else:
        cmd += ["--instance-type", instance_type, "--volume-size", str(volume_size)]
        if ref:
            cmd += ["--ref", ref]
        if allow_dirty:
            cmd.append("--allow-dirty")
        if publish_community:
            cmd.append("--publish-community")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def build_ami(
    region: str = "us-east-1",
    publish_community: bool = False,
    instance_type: str = "c7g.xlarge",
    volume_size: int = 50,
    dry_run: bool = False,
    ref: Optional[str] = None,
    allow_dirty: bool = False,
    promote: Optional[str] = None,
) -> Tuple[bool, str, List[str]]:
    """Build (or promote) the AMI by delegating to scripts/control/build-ami.sh.

    The shell wrapper is the single implementation: it stages a clean artifact
    from a git ref, runs the fail-closed secret scan and performs AWS
    pre-flights. Output streams directly to the terminal.
    """
    script = get_build_script()
    if not script.is_file():
        return False, f"Build wrapper not found: {script}", []

    cmd = build_ami_command(
        region=region,
        publish_community=publish_community,
        instance_type=instance_type,
        volume_size=volume_size,
        dry_run=dry_run,
        ref=ref,
        allow_dirty=allow_dirty,
        promote=promote,
    )
    try:
        proc = subprocess.run(cmd, check=False)
    except Exception as exc:
        return False, f"build-ami.sh execution failed: {exc}", cmd
    if proc.returncode == 0:
        return True, "build-ami.sh completed successfully.", cmd
    return False, f"build-ami.sh exited with code {proc.returncode}.", cmd
