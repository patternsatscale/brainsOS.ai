#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Appliance Host Hardening Baseline (Ticket #312)
# Enforces strict perimeter isolation, host firewall rules (UFW), SSH hardening,
# and Docker daemon log rotation constraints for turn-key appliance deployments.
#
# Usage:
#   sudo ./packages/brainsOS-appliance/scripts/harden-host.sh [OPTIONS]
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
  sudo ./packages/brainsOS-appliance/scripts/harden-host.sh [OPTIONS]

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
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

CONFIGS_DIR="$(cd "${SCRIPT_DIR}/../configs" && pwd)"

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

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

INGRESS_BRIDGE="${BRAINSOS_INGRESS_BRIDGE:-br-ingress}"
INGRESS_SUBNET="${BRAINSOS_INGRESS_SUBNET:-172.28.0.0/24}"
MAIL_BRIDGE="${BRAINSOS_MAIL_BRIDGE:-br-mail}"
MAIL_SUBNET="${BRAINSOS_MAIL_SUBNET:-172.28.5.0/24}"

# ------------------------------------------------------------------------------
# 1. Audit Mode (--check)
# ------------------------------------------------------------------------------
if [ "${CHECK_MODE}" = true ]; then
  log_info "Auditing appliance host hardening posture..."
  AUDIT_FAILED=0

  # Check 1: UFW Firewall
  if command -v ufw >/dev/null 2>&1; then
    if ! UFW_STATUS="$(ufw status verbose 2>/dev/null)" || [ -z "${UFW_STATUS}" ]; then
      UFW_STATUS="$(ufw status 2>/dev/null || true)"
    fi
    if echo "${UFW_STATUS}" | grep -q "Status: active"; then
      log_success "UFW is active."
      UFW_CLEAN="$(printf '%s\n' "${UFW_STATUS}" | sed -E 's/[[:space:]]*#.*$//; s/[[:space:]]+$//')"
      DEFAULT_POLICY_OK=true
      if printf '%s\n' "${UFW_CLEAN}" | grep -qE "^Default:" \
        && ! printf '%s\n' "${UFW_CLEAN}" | grep -qE "^Default:[[:space:]]*deny[[:space:]]+\(incoming\)(,|[[:space:]]|$)"; then
        log_warn "UFW is active but default incoming policy is not deny (incoming)."
        DEFAULT_POLICY_OK=false
        AUDIT_FAILED=1
      fi
      if printf '%s\n' "${UFW_CLEAN}" | grep -qE "^80/tcp([[:space:]]+on[[:space:]]+[^[:space:]]+)?[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+" \
        && printf '%s\n' "${UFW_CLEAN}" | grep -qE "^443/tcp([[:space:]]+on[[:space:]]+[^[:space:]]+)?[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+"; then
        log_success "UFW ports 80/tcp and 443/tcp are allowed."
      else
        log_warn "UFW is active but ports 80 and/or 443 are not explicitly allowed."
        AUDIT_FAILED=1
      fi
      INGRESS_BRIDGE_RE="${INGRESS_BRIDGE//./\\.}"
      INGRESS_SUBNET_RE="${INGRESS_SUBNET//./\\.}"
      MAIL_BRIDGE_RE="${MAIL_BRIDGE//./\\.}"
      MAIL_SUBNET_RE="${MAIL_SUBNET//./\\.}"
      NON_BRIDGE_UFW_LINES="$(printf '%s\n' "${UFW_CLEAN}" | grep -vE "^[^#]*[[:space:]]on[[:space:]]+(${MAIL_BRIDGE_RE}|${INGRESS_BRIDGE_RE}|br-[^[:space:]]+|docker0|veth[^[:space:]]+)[[:space:]]" || true)"
      DISALLOWED_PORT_ALLOWS="$(printf '%s\n' "${UFW_CLEAN}" \
        | awk '
          function port_hits_target(spec,    n, i, parts, k, bounds, lo, hi, p) {
            n = split(spec, parts, ",")
            for (i = 1; i <= n; i++) {
              p = parts[i]
              if (p ~ /^[0-9]+$/) {
                p = p + 0
                if (p == 8000 || p == 8010) return 1
              } else if (p ~ /^[0-9]+:[0-9]+$/) {
                k = split(p, bounds, ":")
                if (k == 2) {
                  lo = bounds[1] + 0
                  hi = bounds[2] + 0
                  if ((lo <= 8000 && 8000 <= hi) || (lo <= 8010 && 8010 <= hi)) return 1
                }
              }
            }
            return 0
          }
          {
            if (NF == 0 || $1 == "Status:" || $1 == "Logging:" || $1 == "Default:" || $1 == "New" || $1 == "To" || $1 == "--") {
              next
            }
            act_idx = 0
            for (i = 2; i <= NF; i++) {
              if ($i == "ALLOW" || $i == "LIMIT") {
                act_idx = i
                break
              }
              if ($i == "DENY" || $i == "REJECT") {
                next
              }
            }
            if (act_idx == 0) {
              next
            }
            tok_count = 0
            for (i = 1; i < act_idx; i++) {
              t = $i
              if (t == "on") {
                i++
                continue
              }
              if (t == "(v6)") {
                continue
              }
              if (t ~ /^\(/) {
                while (i < act_idx && $i !~ /\)$/) {
                  i++
                }
                continue
              }
              tok_count++
              toks[tok_count] = t
            }
            if (tok_count == 0) {
              next
            }
            flagged = 0
            for (i = 1; i <= tok_count; i++) {
              t = toks[i]
              if (t ~ /^Anywhere(\/(tcp|udp))?$/) {
                flagged = 1
                break
              }
              base = t
              if (base ~ /\/tcp$/) {
                sub(/\/tcp$/, "", base)
              } else if (base ~ /\//) {
                base = ""
              }
              if (base != "" && base ~ /^[0-9,:]+$/) {
                if (port_hits_target(base)) {
                  flagged = 1
                  break
                }
              }
            }
            if (!flagged && tok_count == 1) {
              t = toks[1]
              sub(/\/(tcp|udp)$/, "", t)
              if (t ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(\/[0-9]+)?$/ || t ~ /::/ || t ~ /^[0-9a-fA-F:]+:[0-9a-fA-F:]+(\/[0-9]+)?$/) {
                if (t !~ /^[0-9]+:[0-9]+$/) {
                  flagged = 1
                }
              }
            }
            if (flagged) {
              print $0
            }
          }
        ' \
        | grep -vE "^8000/tcp[[:space:]]+on[[:space:]]+${MAIL_BRIDGE_RE}[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+${MAIL_SUBNET_RE}([[:space:]]+\(log(-all)?\))?$" \
        | grep -vE "^8010/tcp[[:space:]]+on[[:space:]]+${INGRESS_BRIDGE_RE}[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+${INGRESS_SUBNET_RE}([[:space:]]+\(log(-all)?\))?$" \
        || true)"
      if [ "${DEFAULT_POLICY_OK}" = true ] \
        && printf '%s\n' "${UFW_CLEAN}" | grep -qE "^8010/tcp[[:space:]]+on[[:space:]]+${INGRESS_BRIDGE_RE}[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+${INGRESS_SUBNET_RE}([[:space:]]+\(log(-all)?\))?$" \
        && printf '%s\n' "${UFW_CLEAN}" | grep -qE "^8000/tcp[[:space:]]+on[[:space:]]+${MAIL_BRIDGE_RE}[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+${MAIL_SUBNET_RE}([[:space:]]+\(log(-all)?\))?$" \
        && [ -z "${DISALLOWED_PORT_ALLOWS}" ] \
        && printf '%s\n' "${NON_BRIDGE_UFW_LINES}" | grep -qE "^8000/tcp[[:space:]]+on[[:space:]]+[^[:space:]]+[[:space:]]+DENY([[:space:]]+IN)?[[:space:]]+Anywhere([[:space:]]+\(log(-all)?\))?$" \
        && printf '%s\n' "${NON_BRIDGE_UFW_LINES}" | grep -qE "^8010/tcp[[:space:]]+on[[:space:]]+[^[:space:]]+[[:space:]]+DENY([[:space:]]+IN)?[[:space:]]+Anywhere([[:space:]]+\(log(-all)?\))?$"; then
        log_success "UFW ports 8010/tcp (${INGRESS_BRIDGE}) and 8000/tcp (${MAIL_BRIDGE}) are strictly bridge-scoped and denied on external NICs."
      else
        log_warn "UFW is active but ports 8000/8010/tcp lack strict bridge scoping (${MAIL_BRIDGE}/${INGRESS_BRIDGE}) or external NIC deny."
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

  # Check 4: Systemd Journald Retention Policy (Ticket #317)
  JOURNALD_CONF_DROPIN="/etc/systemd/journald.conf.d/99-brainsos.conf"
  if [ -f "${JOURNALD_CONF_DROPIN}" ]; then
    if grep -q "SystemMaxUse" "${JOURNALD_CONF_DROPIN}"; then
      log_success "Journald retention policy configured in ${JOURNALD_CONF_DROPIN}."
    else
      log_warn "Journald drop-in exists but lacks SystemMaxUse directive."
      AUDIT_FAILED=1
    fi
  else
    log_warn "Journald drop-in ${JOURNALD_CONF_DROPIN} does not exist."
    AUDIT_FAILED=1
  fi

  # Check 5: Logrotate Configuration (Ticket #317)
  LOGROTATE_CONF="/etc/logrotate.d/brainsos"
  if [ -f "${LOGROTATE_CONF}" ]; then
    log_success "Logrotate policy configured in ${LOGROTATE_CONF}."
  else
    log_warn "Logrotate configuration ${LOGROTATE_CONF} does not exist."
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

# Discover external/physical network interfaces so AWS Default VPC traffic (172.31.0.0/16 ⊂ 172.16.0.0/12)
# can never reach Docker-bridge-only ports 8000/8010 (#384 / #399).
WAN_IFACES=()
if command -v ip >/dev/null 2>&1; then
  while IFS= read -r ifname; do
    [ -n "${ifname}" ] && WAN_IFACES+=("${ifname}")
  done < <(
    {
      ip route show default 2>/dev/null | awk '/default/ {print $5}'
      ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | cut -d'@' -f1 | grep -E '^(ens|eth|enp|ena|wl)[a-zA-Z0-9._-]*$' || true
    } | awk 'NF && !seen[$0]++'
  )
fi
if [ "${#WAN_IFACES[@]}" -eq 0 ]; then
  WAN_IFACES=("ens5")
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would execute: ufw default deny incoming"
  log_info "[DRY-RUN] Would execute: ufw default allow outgoing"
  log_info "[DRY-RUN] Would execute: ufw allow 80/tcp comment 'brainsOS Ingress HTTP (Redirect)'"
  log_info "[DRY-RUN] Would execute: ufw allow 443/tcp comment 'brainsOS Ingress HTTPS (Single-Origin)'"
  for wan_if in "${WAN_IFACES[@]}"; do
    log_info "[DRY-RUN] Would execute: ufw deny in on ${wan_if} to any port 8000 proto tcp comment 'Block external VPC access to Mail Ingress'"
    log_info "[DRY-RUN] Would execute: ufw deny in on ${wan_if} to any port 8010 proto tcp comment 'Block external VPC access to System API'"
  done
  log_info "[DRY-RUN] Would execute: ufw allow in on ${MAIL_BRIDGE} from ${MAIL_SUBNET} to any port 8000 proto tcp comment 'brainsOS Mail Ingress (brainsos-mail-net)'"
  log_info "[DRY-RUN] Would execute: ufw allow in on ${INGRESS_BRIDGE} from ${INGRESS_SUBNET} to any port 8010 proto tcp comment 'brainsOS System API (brainsos-ingress-net)'"
  if [ "${ALLOW_SSH}" = true ]; then
    log_info "[DRY-RUN] Would execute: ufw allow ${SSH_PORT}/tcp comment 'brainsOS SSH Operator Ingress'"
  else
    log_info "[DRY-RUN] SSH port 22/tcp remains CLOSED (Zero-inbound access via AWS SSM Session Manager)"
  fi
  log_info "[DRY-RUN] Would execute: ufw --force enable"
else
  # Purge legacy broad 172.16.0.0/12 allow rules for 8000/8010 on upgrade (#399)
  while IFS= read -r rule_num; do
    [ -n "${rule_num}" ] && ufw --force delete "${rule_num}" >/dev/null 2>&1 || true
  done < <(ufw status numbered 2>/dev/null | grep -E '(8000|8010)/tcp.*ALLOW.*172\.16\.0\.0/12' | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn || true)

  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 80/tcp comment 'brainsOS Ingress HTTP (Redirect)'
  ufw allow 443/tcp comment 'brainsOS Ingress HTTPS (Single-Origin)'
  ufw allow in on "${MAIL_BRIDGE}" from "${MAIL_SUBNET}" to any port 8000 proto tcp comment "brainsOS Mail Ingress (brainsos-mail-net)"
  ufw allow in on "${INGRESS_BRIDGE}" from "${INGRESS_SUBNET}" to any port 8010 proto tcp comment "brainsOS System API (brainsos-ingress-net)"
  for wan_if in "${WAN_IFACES[@]}"; do
    if ip link show "${wan_if}" >/dev/null 2>&1; then
      ufw insert 1 deny in on "${wan_if}" to any port 8010 proto tcp comment "Block external VPC access to System API (${wan_if})" || \
        ufw deny in on "${wan_if}" to any port 8010 proto tcp comment "Block external VPC access to System API (${wan_if})"
      ufw insert 1 deny in on "${wan_if}" to any port 8000 proto tcp comment "Block external VPC access to Mail Ingress (${wan_if})" || \
        ufw deny in on "${wan_if}" to any port 8000 proto tcp comment "Block external VPC access to Mail Ingress (${wan_if})"
    fi
  done

  if [ "${ALLOW_SSH}" = true ]; then
    ufw allow "${SSH_PORT}/tcp" comment 'brainsOS SSH Operator Ingress'
    log_success "UFW allowed SSH port ${SSH_PORT}/tcp."
  else
    log_info "SSH port 22/tcp is not opened in UFW (AWS SSM Session Manager provides zero-inbound operator access)."
  fi

  ufw --force enable
  log_success "UFW host firewall enabled with strict bridge-scoped perimeter."
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
python3 - "${DOCKER_CONF}" "${DOCKER_DIR}" "${DRY_RUN}" << 'EOF'
import json
import os
import sys

conf_path = sys.argv[1]
docker_dir = sys.argv[2]
dry_run = (sys.argv[3] == "true")

data = {}
if os.path.exists(conf_path):
    try:
        with open(conf_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Warning: existing {conf_path} could not be parsed as JSON: {e}", file=sys.stderr)
        data = {}

data["log-driver"] = "json-file"
log_opts = data.get("log-opts", {})
log_opts["max-size"] = "50m"
log_opts["max-file"] = "3"
data["log-opts"] = log_opts

merged_json = json.dumps(data, indent=2)

if dry_run:
    print(f"[DRY-RUN] Would update {conf_path} to:")
    print(merged_json)
else:
    os.makedirs(docker_dir, exist_ok=True)
    with open(conf_path, "w") as f:
        f.write(merged_json + "\n")
    os.chmod(conf_path, 0o644)
    print(f"Successfully updated {conf_path}")
EOF

if [ "${DRY_RUN}" = false ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet docker 2>/dev/null; then
    log_info "Reloading Docker daemon configuration..."
    systemctl reload docker 2>/dev/null || systemctl restart docker 2>/dev/null || true
    log_success "Docker daemon reloaded with log rotation bounds."
  fi
fi

# ------------------------------------------------------------------------------
# 5. Systemd Journald, Logrotate & Automated Retention Timer (Ticket #317)
# ------------------------------------------------------------------------------
log_info "Configuring systemd journal retention, logrotate, and automated maintenance timers..."

JOURNALD_DIR="/etc/systemd/journald.conf.d"
JOURNALD_FILE="${JOURNALD_DIR}/99-brainsos.conf"
LOGROTATE_TARGET="/etc/logrotate.d/brainsos"
SYSTEMD_SYSTEM_DIR="/etc/systemd/system"

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would install ${JOURNALD_FILE} from ${CONFIGS_DIR}/journald-brainsos.conf"
  log_info "[DRY-RUN] Would install ${LOGROTATE_TARGET} from ${CONFIGS_DIR}/logrotate-brainsos"
  log_info "[DRY-RUN] Would install brainsos-prune-logs.service and .timer to ${SYSTEMD_SYSTEM_DIR}"
  log_info "[DRY-RUN] Would execute: systemctl daemon-reload && systemctl enable --now brainsos-prune-logs.timer"
else
  # Journald configuration
  mkdir -p "${JOURNALD_DIR}"
  if [ -f "${CONFIGS_DIR}/journald-brainsos.conf" ]; then
    cp "${CONFIGS_DIR}/journald-brainsos.conf" "${JOURNALD_FILE}"
    chmod 644 "${JOURNALD_FILE}"
    log_success "Installed journald retention configuration."
    if command -v systemctl >/dev/null 2>&1; then
      systemctl restart systemd-journald 2>/dev/null || true
    fi
  fi

  # Logrotate configuration
  if [ -f "${CONFIGS_DIR}/logrotate-brainsos" ]; then
    mkdir -p /etc/logrotate.d
    cp "${CONFIGS_DIR}/logrotate-brainsos" "${LOGROTATE_TARGET}"
    chmod 644 "${LOGROTATE_TARGET}"
    log_success "Installed logrotate policy for brainsOS and Caddy logs."
  fi

  # Systemd timer installation
  if [ -f "${CONFIGS_DIR}/brainsos-prune-logs.service" ] && [ -f "${CONFIGS_DIR}/brainsos-prune-logs.timer" ]; then
    cp "${CONFIGS_DIR}/brainsos-prune-logs.service" "${SYSTEMD_SYSTEM_DIR}/"
    cp "${CONFIGS_DIR}/brainsos-prune-logs.timer" "${SYSTEMD_SYSTEM_DIR}/"
    chmod 644 "${SYSTEMD_SYSTEM_DIR}/brainsos-prune-logs.service" "${SYSTEMD_SYSTEM_DIR}/brainsos-prune-logs.timer"
    if command -v systemctl >/dev/null 2>&1; then
      systemctl daemon-reload 2>/dev/null || true
      systemctl enable --now brainsos-prune-logs.timer 2>/dev/null || true
      log_success "Enabled daily brainsOS log pruning systemd timer."
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 6. Swapfile Safeguard (Prevents OOM on 4 GB RAM instances like t4g.medium)
# ------------------------------------------------------------------------------
SWAP_FILE="/swapfile"
if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would provision 4G ${SWAP_FILE} if not present and register in /etc/fstab"
else
  if [ ! -f "${SWAP_FILE}" ] && ! swapon --show 2>/dev/null | grep -q .; then
    log_info "Provisioning 4G swapfile at ${SWAP_FILE} to protect small instances (e.g. t4g.medium) from OOM..."
    if (fallocate -l 4G "${SWAP_FILE}" 2>/dev/null || dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=4096 status=none 2>/dev/null) && \
       chmod 600 "${SWAP_FILE}" && \
       mkswap "${SWAP_FILE}" >/dev/null 2>&1 && \
       swapon "${SWAP_FILE}" 2>/dev/null; then
      if [ -f /etc/fstab ] && ! grep -q "^${SWAP_FILE} " /etc/fstab; then
        echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
      fi
      log_success "Activated 4G swapfile at ${SWAP_FILE}."
    else
      rm -f "${SWAP_FILE}" 2>/dev/null || true
      log_warn "Could not activate swapfile at ${SWAP_FILE} (continuing)."
    fi
  fi
fi

log_success "Appliance host perimeter hardening and log retention safeguards completed successfully."
