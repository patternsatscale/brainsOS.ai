variable "aws_region" {
  type        = string
  description = "AWS region for building and publishing the golden AMI"
  default     = "us-east-1"
}

variable "ami_name_prefix" {
  type        = string
  description = "Prefix for the generated AMI name"
  default     = "brainsos-arm64"
}

variable "instance_type" {
  type        = string
  description = "EC2 ARM64 Graviton instance type used for the Packer builder"
  default     = "c7g.xlarge"
}

variable "volume_size" {
  type        = number
  description = "Root EBS volume size in GB"
  default     = 50
}

variable "publish_community" {
  type        = bool
  description = "Whether to publish AMI to the AWS Community Catalogue (public). Prefer 'build-ami.sh --promote <ami-id>' after rehearsal."
  default     = false
}

variable "source_dir" {
  type        = string
  description = "Staged, clean source tree produced by scripts/control/build-ami.sh from a git ref (never the working directory)"

  validation {
    condition     = length(var.source_dir) > 0
    error_message = "The source_dir variable must point to the staged artifact created by scripts/control/build-ami.sh."
  }
}

variable "brainsos_ref" {
  type        = string
  description = "Git ref (tag or commit) the staged artifact was produced from; recorded as an AMI tag"
  default     = "unknown"
}

variable "brainsos_commit" {
  type        = string
  description = "Resolved commit SHA of brainsos_ref; recorded as an AMI tag"
  default     = "unknown"
}

variable "ssh_interface" {
  type        = string
  description = "SSH communicator interface ('session_manager' (default, zero-inbound), 'public_ip', or 'private_ip')"
  default     = "session_manager"
}

variable "iam_instance_profile" {
  type        = string
  description = "Existing IAM instance profile for the builder. When null, Packer creates a temporary profile with SSM permissions."
  default     = null
}

variable "subnet_id" {
  type        = string
  description = "VPC Subnet ID where the build instance will be launched"
  default     = null
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where the build instance will be launched"
  default     = null
}
