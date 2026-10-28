"""Tests for HashiCorp Packer template validation and IMDSv2 security invariants."""

from pathlib import Path

from brainsos_appliance.builder import find_packer_binary, get_packer_dir, validate_packer_templates


def test_packer_binary_detected():
    """Verify packer binary is found in PATH or virtualenv."""
    packer_bin = find_packer_binary()
    assert packer_bin is not None
    assert Path(packer_bin).is_file()


def test_packer_templates_validation():
    """Run packer validate on the appliance templates."""
    success, output = validate_packer_templates()
    assert success is True
    assert "The configuration is valid" in output


def test_packer_template_security_invariants():
    """Verify IMDSv2 token requirement and zero-inbound configuration in HCL."""
    packer_dir = get_packer_dir()
    template_file = packer_dir / "brainsos-ami.pkr.hcl"
    assert template_file.is_file()

    content = template_file.read_text()

    # IMDSv2 token enforcement
    assert 'http_tokens                 = "required"' in content
    assert 'http_endpoint               = "enabled"' in content
    assert 'http_put_response_hop_limit = 2' in content
    assert 'imds_support = "v2.0"' in content

    # ARM64 architecture filter
    assert 'architecture        = "arm64"' in content

    # Provisioners: upload the git-staged artifact, run the staged provisioner
    assert 'provisioner "shell"' in content
    assert 'provisioner "file"' in content
    assert 'source      = "${var.source_dir}/"' in content
    assert "/opt/brainsos/packages/brainsOS-appliance/packer/provision.sh" in content


def test_packer_variables_defined():
    """Verify required Packer variables exist with sensible defaults."""
    packer_dir = get_packer_dir()
    var_file = packer_dir / "variables.pkr.hcl"
    assert var_file.is_file()

    content = var_file.read_text()
    assert 'variable "aws_region"' in content
    assert 'variable "ami_name_prefix"' in content
    assert 'variable "instance_type"' in content
    assert 'variable "volume_size"' in content
    assert 'variable "publish_community"' in content
    assert 'variable "source_dir"' in content
    assert 'variable "brainsos_ref"' in content
    assert 'default     = "session_manager"' in content
