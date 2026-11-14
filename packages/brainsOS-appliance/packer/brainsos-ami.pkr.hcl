# ==============================================================================
# brainsOS: Declarative HashiCorp Packer Pipeline for ARM64 Graviton AMI
# Ticket #313 / #322 (Epic #309)
#
# Builds a hardened golden AMI with:
#   - Ubuntu 24.04 LTS Noble Numbat (ARM64)
#   - Docker CE & Compose plugin, all platform images pre-built
#   - AWS SSM Agent (zero-inbound management; also used as the build communicator)
#   - Clean source tree staged from a git ref by scripts/control/build-ami.sh
#   - First-boot IMDSv2 provisioner generating unique per-instance secrets
#   - Automated log retention safeguards & host hardening
#
# Invoke via: make build-ami ARGS="--ref <tag>"   (never 'packer build' directly)
# ==============================================================================

packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.8"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

source "amazon-ebs" "brainsos" {
  ami_name             = var.ami_name != "" ? var.ami_name : "${var.ami_name_prefix}-${formatdate("YYYYMMDD-hhmm", timestamp())}"
  ami_description      = "brainsOS turnkey appliance (ARM64) built from ${var.brainsos_ref}"
  instance_type        = var.instance_type
  region               = var.aws_region
  iam_instance_profile = var.iam_instance_profile
  subnet_id            = var.subnet_id
  vpc_id               = var.vpc_id
  communicator         = "ssh"
  ssh_interface        = var.ssh_interface
  ssh_username         = "ubuntu"

  # Temporary builder profile for SSM Session Manager when no profile is supplied.
  dynamic "temporary_iam_instance_profile_policy_document" {
    for_each = var.iam_instance_profile == null ? [1] : []
    content {
      Version = "2012-10-17"
      Statement {
        Effect = "Allow"
        Action = [
          "ssm:DescribeAssociation",
          "ssm:GetDeployablePatchSnapshotForInstance",
          "ssm:GetDocument",
          "ssm:DescribeDocument",
          "ssm:GetManifest",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:PutInventory",
          "ssm:PutComplianceItems",
          "ssm:PutConfigurePackageResult",
          "ssm:UpdateAssociationStatus",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:UpdateInstanceInformation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply"
        ]
        Resource = ["*"]
      }
    }
  }

  source_ami = var.source_ami != "" ? var.source_ami : null

  dynamic "source_ami_filter" {
    for_each = var.source_ami == "" ? [1] : []
    content {
      filters = {
        name                = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"
        root-device-type    = "ebs"
        virtualization-type = "hvm"
        architecture        = "arm64"
      }
      most_recent = true
      owners      = ["099720109477"] # Canonical
    }
  }

  # Prevent brainsos-firstboot.service and brainsos.service from starting Docker
  # topology while Packer builds incrementally on top of a previous brainsOS AMI (#374).
  user_data = <<-EOT
    #cloud-config
    # BRAINSOS_PACKER_BUILD=true
    bootcmd:
      - systemctl mask --runtime brainsos-firstboot.service brainsos.service brainsos-system-api.service brainsos-resume.service || true
      - mkdir -p /opt/brainsos
      - touch /opt/brainsos/.brainsos-initialized
      - rm -f /opt/brainsos/.env
  EOT

  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = var.volume_size
    volume_type           = "gp3"
    throughput            = var.volume_throughput
    iops                  = var.volume_iops
    delete_on_termination = true
    encrypted             = false # Public AMIs cannot reference encrypted snapshots
  }

  # Builder instance metadata policy
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  # AMI-level default for every launched instance: IMDSv2 required + hop limit 2
  # (containers on Docker bridge networks need 2 hops to reach IMDS for IAM role credentials).
  imds_support = "v2.0"

  ami_groups = var.publish_community ? ["all"] : []

  tags = {
    Name           = var.ami_display_name
    OS             = "Ubuntu 24.04 LTS"
    Arch           = "arm64"
    ManagedBy      = "Packer"
    Repository     = "https://github.com/patternsatscale/brainsOS.ai"
    BrainsOSRef    = var.brainsos_ref
    BrainsOSCommit = var.brainsos_commit
    BuildMode      = var.incremental_build ? "incremental" : "full"
    BaseAMI        = var.source_ami != "" ? var.source_ami : "ubuntu-24.04-canonical"
  }
}

build {
  name    = "brainsos-appliance"
  sources = ["source.amazon-ebs.brainsos"]

  # Step 1: Quiesce any inherited appliance services (incremental mode) and prepare /opt/brainsos
  provisioner "shell" {
    inline = [
      "sudo systemctl mask --runtime brainsos-firstboot.service brainsos.service brainsos-system-api.service brainsos-resume.service 2>/dev/null || true",
      "sudo systemctl stop brainsos.service brainsos-firstboot.service brainsos-system-api.service 2>/dev/null || true",
      "if command -v docker >/dev/null 2>&1; then sudo docker rm -f $(sudo docker ps -aq) 2>/dev/null || true; fi",
      "sudo mkdir -p /opt/brainsos",
      "sudo find /opt/brainsos -mindepth 1 -maxdepth 1 ! -name '.venv' -exec rm -rf {} +",
      "sudo chown -R ubuntu:ubuntu /opt/brainsos"
    ]
  }

  # Step 2: Upload the clean staged artifact (trailing slash = copy contents into /opt/brainsos)
  provisioner "file" {
    source      = "${var.source_dir}/"
    destination = "/opt/brainsos"
  }

  # Step 3: Host provisioning, image pre-build, sanitization & fail-closed secret scan (runs as root).
  # Executes the provisioner from the staged artifact so script, units and configs share one commit.
  provisioner "shell" {
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
      "BRAINSOS_REF=${var.brainsos_ref}",
      "BRAINSOS_INCREMENTAL_BUILD=${var.incremental_build}"
    ]
    execute_command = "{{ .Vars }} sudo -E bash '{{ .Path }}'"
    inline = [
      "bash /opt/brainsos/packages/brainsOS-appliance/packer/provision.sh"
    ]
  }
}
