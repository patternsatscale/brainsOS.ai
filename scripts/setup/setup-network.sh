#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Network & Local Domain Configuration Script
# Configures static IP address (Netplan on Ubuntu/DGX OS or networksetup on macOS)
# and registers local appliance domains in /etc/hosts with confirmation.
# ==============================================================================

set -euo pipefail

# Visual styling
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

# Load .env if present
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${REPO_ROOT}/.env"
  set +a
fi

OS="$(uname -s)"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"

# ------------------------------------------------------------------------------
# Helpers: Validation and Conversion
# ------------------------------------------------------------------------------
is_valid_ipv4() {
  local ip="$1"
  local rx='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
  if [[ "$ip" =~ $rx ]]; then
    local -a octets
    IFS='.' read -r -a octets <<< "$ip"
    for octet in "${octets[@]}"; do
      if (( octet < 0 || octet > 255 )); then
        return 1
      fi
    done
    return 0
  fi
  return 1
}

is_valid_cidr() {
  local cidr="$1"
  if [[ "$cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]{1,2})$ ]]; then
    local ip="${cidr%/*}"
    local prefix="${cidr#*/}"
    if is_valid_ipv4 "$ip" && (( prefix >= 1 && prefix <= 32 )); then
      return 0
    fi
  fi
  return 1
}

cidr_to_netmask() {
  local prefix="$1"
  local mask=""
  local full_octets=$(( prefix / 8 ))
  local partial_octet=$(( prefix % 8 ))

  for ((i=0; i<4; i++)); do
    if (( i < full_octets )); then
      mask+="255"
    elif (( i == full_octets )); then
      mask+=$(( 256 - (1 << (8 - partial_octet)) ))
    else
      mask+="0"
    fi
    (( i < 3 )) && mask+="."
  done
  echo "$mask"
}

is_gx10_hardware() {
  if [[ "${OS}" != "Linux" ]]; then
    return 1
  fi
  if [ -f /sys/class/dmi/id/product_name ] && grep -qi "GX10" /sys/class/dmi/id/product_name 2>/dev/null; then
    return 0
  fi
  if [ -f /sys/class/dmi/id/sys_vendor ] && grep -qi "ASUS" /sys/class/dmi/id/sys_vendor 2>/dev/null && grep -qi "GX10" /sys/class/dmi/id/board_name 2>/dev/null; then
    return 0
  fi
  if [ -d "/opt/nvidia/dgx-dashboard-service" ] || uname -r | grep -qi "nvidia"; then
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------------------
# Command-Line Arguments Parsing
# ------------------------------------------------------------------------------
AUTO_CONFIRM=false
CONFIGURE_STATIC_IP=true
CONFIGURE_HOSTS=true

ARG_IFACE=""
ARG_IP=""
ARG_GATEWAY=""
ARG_DNS=""
ARG_DOMAIN=""
ARG_HOSTS_IP=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Configures static IP and appliance local domain entries in /etc/hosts.
Prompts for confirmation before applying any system changes.

Options:
  --interface <name>     Network interface (e.g. eth0, enp3s0, en0)
  --ip <ip/cidr>         Static IP address with subnet mask CIDR (e.g. 192.168.1.150/24)
  --gateway <ip>         Default gateway IPv4 address (e.g. 192.168.1.1)
  --dns <ip1,ip2>        Comma-separated DNS nameservers (e.g. 1.1.1.1,8.8.8.8)
  --domain <domain>      Local base domain suffix (default: ${BRAINSOS_DOMAIN})
  --hosts-target <ip>    IP to map domains to in /etc/hosts (default: 127.0.0.1 or static IP)
  --langfuse-ip <ip>     Optional dedicated LAN IP for langfuse.${BRAINSOS_DOMAIN} (if on separate machine)
  --skip-ip              Only configure /etc/hosts, skip static IP assignment
  --skip-hosts           Only configure static IP, skip /etc/hosts
  -y, --yes              Non-interactive mode: auto-confirm applying changes
  -h, --help             Show this help message
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interface)
      ARG_IFACE="$2"; shift 2 ;;
    --ip)
      ARG_IP="$2"; shift 2 ;;
    --gateway)
      ARG_GATEWAY="$2"; shift 2 ;;
    --dns)
      ARG_DNS="$2"; shift 2 ;;
    --domain)
      ARG_DOMAIN="$2"; shift 2 ;;
    --hosts-target)
      ARG_HOSTS_IP="$2"; shift 2 ;;
    --langfuse-ip)
      ARG_LANGFUSE_IP="$2"; shift 2 ;;
    --skip-ip)
      CONFIGURE_STATIC_IP=false; shift ;;
    --skip-hosts)
      CONFIGURE_HOSTS=false; shift ;;
    -y|--yes)
      AUTO_CONFIRM=true; shift ;;
    -h|--help)
      usage ;;
    *)
      log_error "Unknown option: $1"
      usage ;;
  esac
done

echo -e "${BLUE}${BOLD}==============================================================================${NC}"
echo -e "${BLUE}${BOLD}brainsOS: Network & Local Domain Setup${NC}"
echo -e "${BLUE}${BOLD}Target: ASUS Ascent GX10 / Linux (Netplan) & macOS Development Workstation${NC}"
echo -e "${BLUE}${BOLD}==============================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Environment & Network Detection
# ------------------------------------------------------------------------------
DETECTED_IFACE=""
DETECTED_IP_CIDR=""
DETECTED_GATEWAY=""
DETECTED_DNS=""

if [[ "${OS}" == "Linux" ]]; then
  # Detect active default route interface
  if command -v ip >/dev/null 2>&1; then
    DETECTED_IFACE="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}' || true)"
    DETECTED_GATEWAY="$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}' || true)"
    if [ -n "${DETECTED_IFACE}" ]; then
      DETECTED_IP_CIDR="$(ip -o -4 addr show dev "${DETECTED_IFACE}" 2>/dev/null | awk '{print $4; exit}' || true)"
    fi
  fi

  # Detect DNS
  if command -v resolvectl >/dev/null 2>&1; then
    DETECTED_DNS="$(resolvectl dns "${DETECTED_IFACE}" 2>/dev/null | awk '{for(i=4;i<=NF;i++) printf "%s%s", $i, (i<NF?",":"")}' || true)"
  fi
  if [ -z "${DETECTED_DNS}" ] && [ -f /etc/resolv.conf ]; then
    DETECTED_DNS="$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}' | tr '\n' ',' | sed 's/,$//' || true)"
  fi

elif [[ "${OS}" == "Darwin" ]]; then
  if command -v route >/dev/null 2>&1; then
    DETECTED_IFACE="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2; exit}' || true)"
    DETECTED_GATEWAY="$(route -n get default 2>/dev/null | awk '/gateway:/ {print $2; exit}' || true)"
    if [ -n "${DETECTED_IFACE}" ] && command -v ipconfig >/dev/null 2>&1; then
      CURRENT_IP="$(ipconfig getifaddr "${DETECTED_IFACE}" 2>/dev/null || true)"
      CURRENT_MASK="$(ipconfig getoption "${DETECTED_IFACE}" subnet_mask 2>/dev/null || true)"
      if [ -n "${CURRENT_IP}" ]; then
        DETECTED_IP_CIDR="${CURRENT_IP}/24" # standard fallback prefix
      fi
    fi
  fi
  if [ -f /etc/resolv.conf ]; then
    DETECTED_DNS="$(grep '^nameserver' /etc/resolv.conf | awk '{print $2}' | tr '\n' ',' | sed 's/,$//' || true)"
  fi
fi

# Fallback defaults if detection was empty
[ -z "${DETECTED_DNS}" ] && DETECTED_DNS="1.1.1.1,8.8.8.8"
[ -z "${DETECTED_GATEWAY}" ] && DETECTED_GATEWAY="192.168.1.1"

# ------------------------------------------------------------------------------
# 2. Interactive Prompts (with pre-filled defaults)
# ------------------------------------------------------------------------------

# 2A. Static IP Parameters
SELECTED_IFACE="${ARG_IFACE:-$DETECTED_IFACE}"
SELECTED_IP="${ARG_IP:-$DETECTED_IP_CIDR}"
SELECTED_GATEWAY="${ARG_GATEWAY:-$DETECTED_GATEWAY}"
SELECTED_DNS="${ARG_DNS:-$DETECTED_DNS}"
SELECTED_DOMAIN="${ARG_DOMAIN:-$BRAINSOS_DOMAIN}"

if [ "${CONFIGURE_STATIC_IP}" = true ]; then
  if [ -z "${ARG_IFACE}" ]; then
    read -r -p "Network Interface to configure [${DETECTED_IFACE:-eth0}]: " input_iface
    SELECTED_IFACE="${input_iface:-${DETECTED_IFACE:-eth0}}"
  fi

  if [ -z "${ARG_IP}" ]; then
    while true; do
      read -r -p "Static IP with CIDR (e.g. 192.168.1.150/24) [${DETECTED_IP_CIDR:-192.168.1.150/24}]: " input_ip
      candidate_ip="${input_ip:-${DETECTED_IP_CIDR:-192.168.1.150/24}}"
      if is_valid_cidr "${candidate_ip}"; then
        SELECTED_IP="${candidate_ip}"
        break
      else
        echo -e "${RED}Invalid IP/CIDR format '${candidate_ip}'. Must be IPv4/prefix (e.g. 192.168.1.150/24).${NC}"
      fi
    done
  fi

  if [ -z "${ARG_GATEWAY}" ]; then
    while true; do
      read -r -p "Default Gateway IPv4 [${SELECTED_GATEWAY}]: " input_gw
      candidate_gw="${input_gw:-$SELECTED_GATEWAY}"
      if is_valid_ipv4 "${candidate_gw}"; then
        SELECTED_GATEWAY="${candidate_gw}"
        break
      else
        echo -e "${RED}Invalid Gateway IPv4 format '${candidate_gw}'.${NC}"
      fi
    done
  fi

  if [ -z "${ARG_DNS}" ]; then
    read -r -p "DNS Nameservers (comma-separated) [${SELECTED_DNS}]: " input_dns
    SELECTED_DNS="${input_dns:-$SELECTED_DNS}"
  fi
fi

# 2B. Local Domain & /etc/hosts Parameters
if [ "${CONFIGURE_HOSTS}" = true ]; then
  if [ -z "${ARG_DOMAIN}" ]; then
    read -r -p "Local Domain Suffix [${SELECTED_DOMAIN}]: " input_domain
    SELECTED_DOMAIN="${input_domain:-$SELECTED_DOMAIN}"
  fi

  # Extract pure IPv4 from static IP (without CIDR) for hosts option
  PLAIN_STATIC_IP="${SELECTED_IP%/*}"

  if [ -z "${ARG_HOSTS_IP}" ]; then
    echo ""
    echo "Choose IP mapping destination for '${SELECTED_DOMAIN}' in /etc/hosts:"
    echo "  1) 127.0.0.1  (Local loopback - recommended if services run locally)"
    if [ "${CONFIGURE_STATIC_IP}" = true ] && [ -n "${PLAIN_STATIC_IP}" ]; then
      echo "  2) ${PLAIN_STATIC_IP} (Static appliance IP - allows other LAN clients to resolve host)"
    fi
    read -r -p "Selection [1]: " hosts_choice
    hosts_choice="${hosts_choice:-1}"
    if [ "${hosts_choice}" = "2" ] && [ -n "${PLAIN_STATIC_IP}" ]; then
      SELECTED_HOSTS_IP="${PLAIN_STATIC_IP}"
    else
      SELECTED_HOSTS_IP="127.0.0.1"
    fi
  else
    SELECTED_HOSTS_IP="${ARG_HOSTS_IP}"
  fi
fi

# ------------------------------------------------------------------------------
# 3. Confirmation Review Gate
# ------------------------------------------------------------------------------
echo ""
echo -e "${YELLOW}${BOLD}------------------------------------------------------------------------------${NC}"
echo -e "${YELLOW}${BOLD}REVIEW PROPOSED CONFIGURATION CHANGES${NC}"
echo -e "${YELLOW}${BOLD}------------------------------------------------------------------------------${NC}"

if [ "${CONFIGURE_STATIC_IP}" = true ]; then
  echo -e "${BOLD}[Static IP Configuration]${NC}"
  echo "  OS Environment:      ${OS}"
  echo "  Interface:           ${SELECTED_IFACE}"
  echo "  Static IP Address:   ${SELECTED_IP}"
  echo "  Default Gateway:     ${SELECTED_GATEWAY}"
  echo "  DNS Nameservers:     ${SELECTED_DNS}"
  if [[ "${OS}" == "Linux" ]]; then
    echo "  Config File Target:  /etc/netplan/99-brainsos-static.yaml"
  elif [[ "${OS}" == "Darwin" ]]; then
    echo "  Config Command:      networksetup -setmanual"
  fi
else
  echo -e "${BOLD}[Static IP Configuration]${NC} SKIPPED (--skip-ip)"
fi

echo ""
if [ "${CONFIGURE_HOSTS}" = true ]; then
  echo -e "${BOLD}[/etc/hosts Domain Entries]${NC}"
  echo "  File Target:         /etc/hosts"
  echo "  Mapping IP:          ${SELECTED_HOSTS_IP}"
  echo "  Mapped Hostnames:    ${SELECTED_DOMAIN}"
  echo "                       hermes.${SELECTED_DOMAIN}"
  echo "                       api.hermes.${SELECTED_DOMAIN}"
  echo "                       proxy.${SELECTED_DOMAIN}"
  echo "                       memory.${SELECTED_DOMAIN}"
  echo "                       langfuse.${SELECTED_DOMAIN} (Observability)"
  if is_gx10_hardware; then
    echo "                       dgx.${SELECTED_DOMAIN}"
  fi
else
  echo -e "${BOLD}[/etc/hosts Domain Entries]${NC} SKIPPED (--skip-hosts)"
fi
echo -e "${YELLOW}${BOLD}------------------------------------------------------------------------------${NC}"

if [ "${AUTO_CONFIRM}" != true ]; then
  read -r -p "Are you sure you want to apply these network settings? (y/N): " CONFIRM
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    log_info "Operation cancelled by user. No changes were applied."
    exit 0
  fi
fi

# ------------------------------------------------------------------------------
# 4. Applying Changes
# ------------------------------------------------------------------------------
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Sudo check
SUDO=""
if [ "$EUID" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    log_error "Root permissions required to modify network configuration. Please run with sudo."
    exit 1
  fi
fi

# 4A. Apply /etc/hosts Entries
if [ "${CONFIGURE_HOSTS}" = true ]; then
  log_info "Configuring /etc/hosts..."
  
  # Create timestamped backup of /etc/hosts
  HOSTS_BACKUP="/etc/hosts.bak.${TIMESTAMP}"
  log_info "Backing up /etc/hosts to ${HOSTS_BACKUP}..."
  $SUDO cp /etc/hosts "${HOSTS_BACKUP}"

  HOSTS_BLOCK_START="# --- BEGIN BRAINSOS DOMAINS ---"
  HOSTS_BLOCK_END="# --- END BRAINSOS DOMAINS ---"
  HOSTS_LANGFUSE_IP="${ARG_LANGFUSE_IP:-$SELECTED_HOSTS_IP}"
  # Dynamically discover all fleet agent subdomains from config/agents.yaml
  DYNAMIC_AGENT_DOMAINS=""
  if [ -f "${REPO_ROOT}/config/agents.yaml" ]; then
    while read -r sub; do
      [ -z "${sub}" ] && continue
      DYNAMIC_AGENT_DOMAINS="${DYNAMIC_AGENT_DOMAINS} ${sub} api.${sub}"
    done < <(grep -E '^[[:space:]]*subdomain:' "${REPO_ROOT}/config/agents.yaml" | awk '{print $2}' | tr -d '"' | tr -d "'")
  fi
  FLEET_DOMAINS="hermes.${SELECTED_DOMAIN} api.hermes.${SELECTED_DOMAIN} proxy.${SELECTED_DOMAIN} memory.${SELECTED_DOMAIN} github-proxy.${SELECTED_DOMAIN} efw.${SELECTED_DOMAIN} firewall.${SELECTED_DOMAIN}${DYNAMIC_AGENT_DOMAINS}"
  if is_gx10_hardware; then
    HOSTS_LINE="${SELECTED_HOSTS_IP} ${SELECTED_DOMAIN} ${FLEET_DOMAINS} dgx.${SELECTED_DOMAIN}"
  else
    HOSTS_LINE="${SELECTED_HOSTS_IP} ${SELECTED_DOMAIN} ${FLEET_DOMAINS}"
  fi
  LANGFUSE_LINE="${HOSTS_LANGFUSE_IP} langfuse.${SELECTED_DOMAIN}"

  # Strip any previous brainsOS block if present, then append clean block
  TEMP_HOSTS="$(mktemp)"
  sed "/${HOSTS_BLOCK_START}/,/${HOSTS_BLOCK_END}/d" /etc/hosts > "${TEMP_HOSTS}"

  {
    echo ""
    echo "${HOSTS_BLOCK_START}"
    echo "# Configured by brainsOS setup-network.sh on $(date)"
    echo "${HOSTS_LINE}"
    echo "${LANGFUSE_LINE}"
    echo "${HOSTS_BLOCK_END}"
  } >> "${TEMP_HOSTS}"

  $SUDO cp "${TEMP_HOSTS}" /etc/hosts
  $SUDO chmod 644 /etc/hosts
  rm -f "${TEMP_HOSTS}"
  log_success "Updated /etc/hosts with brainsOS domain entries."
fi

# 4B. Apply Static IP Configuration
if [ "${CONFIGURE_STATIC_IP}" = true ]; then
  if [[ "${OS}" == "Linux" ]]; then
    if command -v netplan >/dev/null 2>&1; then
      log_info "Applying static IP via Netplan on Linux/DGX OS..."
      NETPLAN_DIR="/etc/netplan"
      NETPLAN_BACKUP_DIR="${NETPLAN_DIR}/backup_${TIMESTAMP}"
      $SUDO mkdir -p "${NETPLAN_BACKUP_DIR}"

      # Backup existing yaml files
      if compgen -G "${NETPLAN_DIR}/*.yaml" > /dev/null; then
        log_info "Backing up existing Netplan configs to ${NETPLAN_BACKUP_DIR}..."
        $SUDO cp "${NETPLAN_DIR}"/*.yaml "${NETPLAN_BACKUP_DIR}/" 2>/dev/null || true
      fi

      # Determine Netplan renderer (NetworkManager if active or configured, else networkd)
      RENDERER="networkd"
      if grep -qr "renderer:[[:space:]]*NetworkManager" "${NETPLAN_DIR}" 2>/dev/null || \
         (command -v systemctl >/dev/null 2>&1 && systemctl is-active NetworkManager >/dev/null 2>&1); then
        RENDERER="NetworkManager"
      fi
      log_info "Selected Netplan renderer: ${RENDERER}"

      # Split comma-separated DNS list into YAML array format
      DNS_YAML_LIST=""
      IFS=',' read -r -a dns_arr <<< "${SELECTED_DNS}"
      for dns_server in "${dns_arr[@]}"; do
        # Trim leading/trailing whitespace
        dns_trimmed="$(echo "${dns_server}" | xargs)"
        if [ -n "${dns_trimmed}" ]; then
          if [ -z "${DNS_YAML_LIST}" ]; then
            DNS_YAML_LIST="\"${dns_trimmed}\""
          else
            DNS_YAML_LIST="${DNS_YAML_LIST}, \"${dns_trimmed}\""
          fi
        fi
      done

      BRAINSOS_NETPLAN_FILE="${NETPLAN_DIR}/99-brainsos-static.yaml"
      TEMP_NETPLAN="$(mktemp)"

      cat <<EOF > "${TEMP_NETPLAN}"
# ==============================================================================
# brainsOS: Static Network Configuration
# Generated by scripts/setup-network.sh on $(date)
# ==============================================================================
network:
  version: 2
  renderer: ${RENDERER}
  ethernets:
    ${SELECTED_IFACE}:
      dhcp4: no
      addresses:
        - ${SELECTED_IP}
      routes:
        - to: default
          via: ${SELECTED_GATEWAY}
      nameservers:
        addresses: [${DNS_YAML_LIST}]
EOF

      $SUDO cp "${TEMP_NETPLAN}" "${BRAINSOS_NETPLAN_FILE}"
      $SUDO chmod 600 "${BRAINSOS_NETPLAN_FILE}"
      rm -f "${TEMP_NETPLAN}"

      log_info "Validating Netplan configuration..."
      if $SUDO netplan generate; then
        log_info "Applying Netplan configuration..."
        $SUDO netplan apply
        log_success "Netplan configuration successfully applied to ${SELECTED_IFACE}."
      else
        log_error "Netplan configuration validation failed. Restoring previous configuration..."
        if [ -d "${NETPLAN_BACKUP_DIR}" ]; then
          $SUDO cp "${NETPLAN_BACKUP_DIR}"/*.yaml "${NETPLAN_DIR}/" 2>/dev/null || true
          $SUDO rm -f "${BRAINSOS_NETPLAN_FILE}"
          $SUDO netplan apply || true
        fi
        exit 1
      fi

    elif command -v nmcli >/dev/null 2>&1; then
      log_info "Netplan not found. Applying static IP via NetworkManager (nmcli)..."
      PLAIN_IP="${SELECTED_IP}"
      $SUDO nmcli con mod "${SELECTED_IFACE}" ipv4.addresses "${PLAIN_IP}"
      $SUDO nmcli con mod "${SELECTED_IFACE}" ipv4.gateway "${SELECTED_GATEWAY}"
      $SUDO nmcli con mod "${SELECTED_IFACE}" ipv4.dns "${SELECTED_DNS}"
      $SUDO nmcli con mod "${SELECTED_IFACE}" ipv4.method manual
      $SUDO nmcli con up "${SELECTED_IFACE}"
      log_success "NetworkManager configuration successfully applied to ${SELECTED_IFACE}."

    else
      log_error "Neither 'netplan' nor 'nmcli' found on Linux host."
      log_error "Please configure static IP manually according to your Linux distribution."
      exit 1
    fi

  elif [[ "${OS}" == "Darwin" ]]; then
    log_info "Configuring static IP on macOS via networksetup..."
    PREFIX="${SELECTED_IP#*/}"
    IP_ONLY="${SELECTED_IP%/*}"
    NETMASK="$(cidr_to_netmask "${PREFIX}")"

    # Find the macOS service name corresponding to the interface
    SERVICE_NAME=""
    while IFS= read -r line; do
      if [[ "$line" =~ ^Hardware\ Port:\ (.*) ]]; then
        current_service="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ ^Device:\ (.*) ]]; then
        current_dev="${BASH_REMATCH[1]}"
        if [ "${current_dev}" = "${SELECTED_IFACE}" ]; then
          SERVICE_NAME="${current_service}"
          break
        fi
      fi
    done < <(networksetup -listallhardwareports)

    if [ -z "${SERVICE_NAME}" ]; then
      SERVICE_NAME="Wi-Fi" # Default fallback
      log_warn "Could not match device ${SELECTED_IFACE} to a named service. Defaulting to '${SERVICE_NAME}'."
    fi

    log_info "Applying static manual IP on service '${SERVICE_NAME}' (IP: ${IP_ONLY}, Mask: ${NETMASK}, Router: ${SELECTED_GATEWAY})..."
    $SUDO networksetup -setmanual "${SERVICE_NAME}" "${IP_ONLY}" "${NETMASK}" "${SELECTED_GATEWAY}"

    # Split DNS and apply
    IFS=',' read -r -a dns_arr <<< "${SELECTED_DNS}"
    $SUDO networksetup -setdnsservers "${SERVICE_NAME}" "${dns_arr[@]}"
    log_success "macOS network configuration successfully applied."
  fi
fi

# ------------------------------------------------------------------------------
# 5. Summary & Verification Instructions
# ------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}Network and Domain Setup Complete!${NC}"
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
if [ "${CONFIGURE_HOSTS}" = true ]; then
  echo -e "Appliance domains registered in /etc/hosts:"
  echo -e "  - Ingress Portal:  http://${SELECTED_DOMAIN}"
  echo -e "  - Agent Plane:     http://hermes.${SELECTED_DOMAIN}"
  echo -e "  - Agent API:       http://api.hermes.${SELECTED_DOMAIN}"
  echo -e "  - Control Plane:   http://proxy.${SELECTED_DOMAIN}"
  echo -e "  - Memory Plane:    http://memory.${SELECTED_DOMAIN}"
  echo -e "  - Observability:   http://langfuse.${SELECTED_DOMAIN}:3001"
  echo -e "  - Egress Firewall: http://efw.${SELECTED_DOMAIN}"
  if is_gx10_hardware; then
    echo -e "  - Telemetry:       http://dgx.${SELECTED_DOMAIN}"
  fi
fi
if [ "${CONFIGURE_STATIC_IP}" = true ]; then
  echo -e "Static IP assigned to ${SELECTED_IFACE}: ${SELECTED_IP}"
fi
echo -e "${GREEN}${BOLD}==============================================================================${NC}"
