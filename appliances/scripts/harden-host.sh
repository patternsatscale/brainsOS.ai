#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Appliance Host Hardening Baseline (Ticket #312)
# Enforces strict perimeter isolation, host firewall rules (UFW), SSH hardening,
# and Docker daemon log rotation constraints for turn-key appliance deployments.
#
# Usage:
#   sudo ./appliances/scripts/harden-host.sh [OPTIONS]
#
# Options:
#   --dry-run       Simulate changes without modifying firewall or host files
#   --check         Audit and verify system posture against hardening baseline
#   --allow-ssh     Permit SSH ingress on port 22/tcp (Default: disabled, SSM only)
#   --ssh-port N    Specify custom SSH port if --allow-ssh is enabled (Default: 22)
#   -h, --help      Display this help message
# ==============================================================================

set -euo pipefail

# Visual styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

DRY_RUN=false
CHECK_MODE=false
ALLOW_SSH=false
SSH_PORT=22

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --check)
      CHECK_MODE=true
      shift
      ;;
    --allow-ssh)
      ALLOW_SSH=true
      shift
      ;;
    --ssh-port)
      SSH_PORT="${2:-22}"
      shift 2
      ;;
    -h|--help)
      cat <<EOF
brainsOS Appliance Host Hardening Script (Ticket #312)

Usage:
  sudo ./appliances/scripts/harden-host.sh [OPTIONS]

Options:
  --dry-run       Simulate changes without modifying firewall or host files
  --check         Audit current system posture against hardening baseline
  --allow-ssh     Permit SSH inbound on port 22/tcp (Default: closed, SSM only)
  --ssh-port N    Specify custom port if --allow-ssh is enabled (Default: 22)
  -h, --help      Display this help message
EOF
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

# Detect Operating System
OS_NAME="$(uname -s)"
if [ "${OS_NAME}" != "Linux" ]; then
  log_warn "Host OS is ${OS_NAME}. Appliance perimeter hardening (UFW, sshd_config.d, /etc/docker) applies to Linux (Ubuntu / DGX OS)."
  log_info "Skipping host-level enforcement on non-Linux platform."
  exit 0
fi

# ------------------------------------------------------------------------------
# Privilege Pre-flight Check
# ------------------------------------------------------------------------------
if [ "${DRY_RUN}" = false ] && [ "${CHECK_MODE}" = false ]; then
  if [ "$(id -u)" -ne 0 ]; then
    log_error "Root privileges are required to configure firewall rules, SSH drop-ins, and Docker daemon settings."
    log_info "Please run: sudo $0 $* (or use --dry-run / --check)"
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# 1. Audit Mode (--check)
# ------------------------------------------------------------------------------
if [ "${CHECK_MODE}" = true ]; then
  log_info "Auditing appliance host hardening posture..."
  AUDIT_FAILED=0

  # Check 1: UFW Firewall
  if command -v ufw >/dev/null 2>&1; then
    UFW_STATUS="$(ufw status 2>/dev/null || true)"
    if echo "${UFW_STATUS}" | grep -q "Status: active"; then
      log_success "UFW is active."
      if echo "${UFW_STATUS}" | grep -E "80/tcp.*ALLOW" >/dev/null && echo "${UFW_STATUS}" | grep -E "443/tcp.*ALLOW" >/dev/null; then
        log_success "UFW ports 80/tcp and 443/tcp are allowed."
      else
        log_warn "UFW is active but ports 80 and/or 443 are not explicitly allowed."
        AUDIT_FAILED=1
      fi
    else
      log_warn "UFW is not active (status: inactive)."
      AUDIT_FAILED=1
    fi
  else
    log_warn "UFW binary not found on host."
    AUDIT_FAILED=1
  fi

  # Check 2: SSH Password Authentication
  SSH_CONF_DROPIN="/etc/ssh/sshd_config.d/99-brainsos-harden.conf"
  if [ -f "${SSH_CONF_DROPIN}" ]; then
    if grep -qE "^\s*PasswordAuthentication\s+no" "${SSH_CONF_DROPIN}"; then
      log_success "SSH drop-in ${SSH_CONF_DROPIN} disables password authentication."
    else
      log_warn "SSH drop-in exists but does not enforce PasswordAuthentication no."
      AUDIT_FAILED=1
    fi
  else
    if command -v sshd >/dev/null 2>&1; then
      # Test effective sshd config
      EFFECTIVE_PW_AUTH="$(sshd -T 2>/dev/null | grep -i "^passwordauthentication" || echo "")"
      if [ "${EFFECTIVE_PW_AUTH}" = "passwordauthentication no" ]; then
        log_success "Effective sshd configuration enforces PasswordAuthentication no."
      else
        log_warn "sshd configuration does not enforce PasswordAuthentication no (${EFFECTIVE_PW_AUTH:-unset})."
        AUDIT_FAILED=1
      fi
    else
      log_warn "SSH drop-in ${SSH_CONF_DROPIN} does not exist."
      AUDIT_FAILED=1
    fi
  fi

  # Check 3: Docker Daemon Logging Limits
  DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
  if [ -f "${DOCKER_DAEMON_JSON}" ]; then
    if grep -q "max-size" "${DOCKER_DAEMON_JSON}" && grep -q "max-file" "${DOCKER_DAEMON_JSON}"; then
      log_success "Docker daemon logging constraints are configured in ${DOCKER_DAEMON_JSON}."
    else
      log_warn "Docker daemon.json exists but lacks log rotation constraints (max-size/max-file)."
      AUDIT_FAILED=1
    fi
  else
    log_warn "Docker daemon configuration ${DOCKER_DAEMON_JSON} does not exist."
    AUDIT_FAILED=1
  fi

  if [ ${AUDIT_FAILED} -eq 0 ]; then
    log_success "All appliance host hardening checks PASSED."
    exit 0
  else
    log_warn "One or more appliance hardening checks failed baseline criteria."
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# 2. UFW Host Firewall Ingress Lockdown
# ------------------------------------------------------------------------------
log_info "Configuring UFW firewall ingress lockdown..."

if ! command -v ufw >/dev/null 2>&1; then
  log_error "UFW (Uncomplicated Firewall) is not installed. Please install ufw (apt install -y ufw)."
  exit 1
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would execute: ufw default deny incoming"
  log_info "[DRY-RUN] Would execute: ufw default allow outgoing"
  log_info "[DRY-RUN] Would execute: ufw allow 80/tcp comment 'brainsOS Ingress HTTP (Redirect)'"
  log_info "[DRY-RUN] Would execute: ufw allow 443/tcp comment 'brainsOS Ingress HTTPS (Single-Origin)'"
  if [ "${ALLOW_SSH}" = true ]; then
    log_info "[DRY-RUN] Would execute: ufw allow ${SSH_PORT}/tcp comment 'brainsOS SSH Operator Ingress'"
  else
    log_info "[DRY-RUN] SSH port 22/tcp remains CLOSED (Zero-inbound access via AWS SSM Session Manager)"
  fi
  log_info "[DRY-RUN] Would execute: ufw --force enable"
else
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 80/tcp comment 'brainsOS Ingress HTTP (Redirect)'
  ufw allow 443/tcp comment 'brainsOS Ingress HTTPS (Single-Origin)'

  if [ "${ALLOW_SSH}" = true ]; then
    ufw allow "${SSH_PORT}/tcp" comment 'brainsOS SSH Operator Ingress'
    log_success "UFW allowed SSH port ${SSH_PORT}/tcp."
  else
    log_info "SSH port 22/tcp is not opened in UFW (AWS SSM Session Manager provides zero-inbound operator access)."
  fi

  ufw --force enable
  log_success "UFW host firewall enabled with strict single-origin perimeter."
fi

# ------------------------------------------------------------------------------
# 3. SSH Hardening (Zero Password Auth & Root Lockdown)
# ------------------------------------------------------------------------------
log_info "Configuring SSH service hardening baseline..."

SSH_DROPIN_DIR="/etc/ssh/sshd_config.d"
SSH_DROPIN_FILE="${SSH_DROPIN_DIR}/99-brainsos-harden.conf"

SSH_HARDEN_CONTENT="# ==============================================================================
# brainsOS: Appliance SSH Hardening Baseline (Ticket #312)
# ==============================================================================
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
X11Forwarding no
MaxAuthTries 3
PubkeyAuthentication yes
ClientAliveInterval 300
ClientAliveCountMax 2
"

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would write drop-in configuration to ${SSH_DROPIN_FILE}:"
  echo "${SSH_HARDEN_CONTENT}"
  log_info "[DRY-RUN] Would validate syntax via 'sshd -t' and reload ssh service."
else
  mkdir -p "${SSH_DROPIN_DIR}"
  echo "${SSH_HARDEN_CONTENT}" > "${SSH_DROPIN_FILE}"
  chmod 644 "${SSH_DROPIN_FILE}"

  if command -v sshd >/dev/null 2>&1; then
    if sshd -t; then
      log_success "SSH configuration syntax verified."
      if systemctl is-active --quiet ssh 2>/dev/null; then
        systemctl reload ssh 2>/dev/null || true
        log_success "Reloaded ssh service."
      elif systemctl is-active --quiet sshd 2>/dev/null; then
        systemctl reload sshd 2>/dev/null || true
        log_success "Reloaded sshd service."
      fi
    else
      log_error "sshd syntax validation failed! Removing invalid drop-in."
      rm -f "${SSH_DROPIN_FILE}"
      exit 1
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 4. Docker Daemon Log Rotation & Disk Space Safeguards
# ------------------------------------------------------------------------------
log_info "Configuring Docker daemon log rotation safeguards (/etc/docker/daemon.json)..."

DOCKER_DIR="/etc/docker"
DOCKER_CONF="${DOCKER_DIR}/daemon.json"

# Python script to safely merge log-driver and log-opts into daemon.json
python3 -c "
import json
import os
import sys

conf_path = '${DOCKER_CONF}'
dry_run = ('${DRY_RUN}' == 'true')

data = {}
if os.path.exists(conf_path):
    try:
        with open(conf_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f'Warning: existing {conf_path} could not be parsed as JSON: {e}', file=sys.stderr)
        data = {}

data['log-driver'] = 'json-file'
log_opts = data.get('log-opts', {})
log_opts['max-size'] = '50m'
log_opts['max-file'] = '3'
data['log-opts'] = log_opts

merged_json = json.dumps(data, indent=2)

if dry_run:
    print(f'[DRY-RUN] Would update {conf_path} to:')
    print(merged_json)
else:
    os.makedirs('${DOCKER_DIR}', exist_ok=True)
    with open(conf_path, 'w') as f:
        f.write(merged_json + '\n')
    os.chmod(conf_path, 0o644)
    print(f'Successfully updated {conf_path}')
"

if [ "${DRY_RUN}" = false ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet docker 2>/dev/null; then
    log_info "Reloading Docker daemon configuration..."
    systemctl reload docker 2>/dev/null || systemctl restart docker 2>/dev/null || true
    log_success "Docker daemon reloaded with log rotation bounds."
  fi
fi

log_success "Appliance host perimeter hardening completed successfully."
