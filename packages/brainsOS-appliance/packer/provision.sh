#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Golden AMI Provisioner (Packer Shell Provisioner)
# Ticket #313 / #322 / #338 (Epic #309)
#
# Configures a clean Ubuntu 24.04 ARM64 instance into a turnkey brainsOS appliance:
#   1. Installs base packages, Docker CE + Compose, Node.js (portal), uv
#   2. Ensures exactly one AWS SSM Agent (Canonical AMIs ship the snap)
#   3. Installs systemd units (brainsos, brainsos-firstboot)
#   4. Enforces host perimeter hardening (harden-host.sh) and log retention bounds
#   5. Pre-builds ALL platform images (make runner-base build) and the portal bundle
#   6. Sanitizes the host (secrets, SSH keys, machine-id, cloud-init, histories)
#   7. Fail-closed scan: aborts the build if any secret or key material remains
#
# The repository tree at /opt/brainsos is a clean artifact staged by
# scripts/control/build-ami.sh from a git ref; it never contains a .env.
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
SCAN_ONLY=false
INCREMENTAL_BUILD="${BRAINSOS_INCREMENTAL_BUILD:-false}"
APP_DIR="${BRAINSOS_APP_DIR:-/opt/brainsos}"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --scan-only)
      SCAN_ONLY=true
      shift
      ;;
    --incremental)
      INCREMENTAL_BUILD=true
      shift
      ;;
    --app-dir)
      APP_DIR="${2:-${APP_DIR}}"
      shift 2
      ;;
    -h|--help)
      cat <<EOF
brainsOS Golden AMI Provisioner (Tickets #313 / #322 / #338)

Usage:
  sudo ./packages/brainsOS-appliance/packer/provision.sh [OPTIONS]

Options:
  --dry-run       Simulate provisioning steps without host modifications
  --scan-only     Run only the fail-closed snapshot secret scan (exit 1 on findings)
  --incremental   Reuse pre-baked OS, Docker CE, Node.js & cached layers on a base brainsOS AMI
  --app-dir DIR   Appliance root (Default: /opt/brainsos)
  -h, --help      Show this help message
EOF
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

CONFIGS_DIR="${APP_DIR}/packages/brainsOS-appliance/configs"
SCRIPTS_DIR="${APP_DIR}/packages/brainsOS-appliance/scripts"

# ------------------------------------------------------------------------------
# Fail-closed snapshot scan (Rules 5, 10, 14). Prints findings; returns 1 if any.
# ------------------------------------------------------------------------------
snapshot_scan() {
  local root="$1"
  local home_root="${2:-}"
  local findings=0

  # 1. No environment files other than the committed template
  while IFS= read -r f; do
    log_error "SCAN: environment file present: ${f}"
    findings=$((findings + 1))
  done < <(find "${root}" -path "*/node_modules" -prune -o \( -name ".env" -o -name ".env.*" \) ! -name ".env.example" -type f -print 2>/dev/null)

  # 2. No first-boot marker
  if [ -e "${root}/.brainsos-initialized" ]; then
    log_error "SCAN: first-boot marker present: ${root}/.brainsos-initialized"
    findings=$((findings + 1))
  fi

  # 3. Runtime data directory must contain no files (directory skeleton only)
  if [ -d "${root}/data" ]; then
    while IFS= read -r f; do
      log_error "SCAN: runtime data file present: ${f}"
      findings=$((findings + 1))
    done < <(find "${root}/data" -type f ! -name ".gitkeep" -print 2>/dev/null | head -n 20)
  fi

  # 4. No generated master keys (sk-brainsos-<32 hex>) anywhere in the tree
  while IFS= read -r f; do
    log_error "SCAN: generated LiteLLM master key material found in: ${f}"
    findings=$((findings + 1))
  done < <(grep -rIlE "sk-brainsos-[0-9a-f]{32}" --exclude-dir=node_modules "${root}" 2>/dev/null || true)

  # 5. No SSH keys, AWS credentials or shell histories in home directories
  if [ -n "${home_root}" ]; then
    while IFS= read -r f; do
      log_error "SCAN: credential material present: ${f}"
      findings=$((findings + 1))
    done < <(find "${home_root}/root" "${home_root}/home" \( -name "authorized_keys" -o -name ".bash_history" -o -path "*/.aws/credentials" -o -name "id_rsa" -o -name "id_ed25519" \) -type f -print 2>/dev/null)

    while IFS= read -r f; do
      log_error "SCAN: SSH host key present (must be regenerated per instance): ${f}"
      findings=$((findings + 1))
    done < <(find "${home_root}/etc/ssh" -name "ssh_host_*" -type f -print 2>/dev/null)
  fi

  if [ "${findings}" -gt 0 ]; then
    log_error "Snapshot scan FAILED with ${findings} finding(s). Refusing to produce an AMI."
    return 1
  fi
  log_success "Snapshot scan passed: zero secrets, keys or runtime data in the image."
  return 0
}

if [ "${SCAN_ONLY}" = true ]; then
  SCAN_HOME_ROOT=""
  [ "${APP_DIR}" = "/opt/brainsos" ] && SCAN_HOME_ROOT="/"
  snapshot_scan "${APP_DIR}" "${SCAN_HOME_ROOT}"
  exit $?
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Simulating AMI provisioner sequence (app dir: ${APP_DIR})..."
  log_info "[DRY-RUN] 1. apt: dist-upgrade + noble-proposed linux-aws kernel + curl, jq, ufw, logrotate, git, make, python3, NodeSource nodejs 22 LTS (purge python3-pip*/python3-venv/node-lodash*)"
  log_info "[DRY-RUN] 2. Ensure a single AWS SSM Agent (reuse Canonical snap if present)"
  log_info "[DRY-RUN] 3. Install Docker CE + Compose plugin; install latest uv"
  log_info "[DRY-RUN] 4. Install brainsos.service, brainsos-firstboot.service & brainsos-system-api.service"
  log_info "[DRY-RUN] 5. Execute ${SCRIPTS_DIR}/harden-host.sh"
  log_info "[DRY-RUN] 6. make runner-base build; docker compose pull (incl. gitea/gitea:1.22); verify images; portal build; .venv (bootstrap-env.sh)"
  log_info "[DRY-RUN] 7. Sanitize: prune portal node_modules, uv/uvx binaries, superseded kernel packages, provisioning env, SSH keys, host keys, machine-id, cloud-init"
  log_info "[DRY-RUN] 8. Fail-closed snapshot scan"
  log_success "[DRY-RUN] Provisioning simulation complete."
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  log_error "This script must be run as root (Packer invokes it via sudo)."
  exit 1
fi

if [ -f "${APP_DIR}/.env" ]; then
  log_error "${APP_DIR}/.env exists in the staged artifact. The artifact must be produced by build-ami.sh from a git ref."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
export HOME=/root

IS_INCREMENTAL_HOST=false
if [ "${INCREMENTAL_BUILD}" = "true" ] && command -v docker >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
  IS_INCREMENTAL_HOST=true
  log_info "Incremental Delta Build Mode active: reusing pre-baked OS, Docker CE, Node.js & cached image layers (#374)."
fi

# ------------------------------------------------------------------------------
# 1. Base System Packages & Security Upgrades (Ticket #338 / #374)
# ------------------------------------------------------------------------------
if [ "${IS_INCREMENTAL_HOST}" = "true" ]; then
  log_info "1. [Incremental] Applying fast APT security delta updates..."
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold"
  apt-get install -y --no-install-recommends ec2-hibinit-agent acpid
  systemctl enable hibinit-agent.service acpid.service 2>/dev/null || true
else
  log_info "1. Updating package lists, applying security dist-upgrade, and installing foundational dependencies..."
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold"

  # Upgrade AWS kernel packages from noble-proposed when a newer linux-aws release is staged
  # (resolves all 2,732 pending linux-aws-7.0 / linux-image-aws CVEs tracked in Ubuntu OVAL)
  log_info "Upgrading AWS kernel packages from noble-proposed (if newer kernel is staged)..."
  echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports noble-proposed main restricted" > /etc/apt/sources.list.d/noble-proposed-kernel.list
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y -t noble-proposed \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    linux-aws linux-image-aws linux-headers-aws || \
    log_warn "noble-proposed kernel upgrade skipped; continuing with noble-security kernel."
  rm -f /etc/apt/sources.list.d/noble-proposed-kernel.list
  apt-get update -y

  apt-get install -y --no-install-recommends \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    make \
    jq \
    iptables \
    ufw \
    logrotate \
    socat \
    python3 \
    tar \
    gzip \
    ec2-hibinit-agent \
    acpid

  systemctl enable hibinit-agent.service acpid.service 2>/dev/null || true

  log_info "Installing Node.js 22 LTS from NodeSource (bundles npm without Debian node-lodash packages)..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
  chmod a+r /etc/apt/keyrings/nodesource.gpg
  echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | \
    tee /etc/apt/sources.list.d/nodesource.list > /dev/null
  apt-get update -y
  apt-get install -y --no-install-recommends nodejs
fi

# Purge legacy system pip/wheel/venv (uv creates .venv natively without python3-pip-whl) and any Debian node-lodash packages
apt-get purge -y --auto-remove \
  python3-pip python3-pip-whl python3-setuptools-whl python3-wheel \
  python3-venv 'python3.*-venv' 'node-lodash*' 2>/dev/null || true

# ------------------------------------------------------------------------------
# 2. AWS Systems Manager (SSM) Agent - exactly one instance
# ------------------------------------------------------------------------------
log_info "2. Ensuring AWS Systems Manager (SSM) Agent is installed and enabled..."
if command -v snap >/dev/null 2>&1 && snap list amazon-ssm-agent >/dev/null 2>&1; then
  snap start --enable amazon-ssm-agent >/dev/null 2>&1 || true
  log_success "Using Canonical-provided SSM Agent snap (no duplicate .deb installed)."
elif systemctl list-unit-files 2>/dev/null | grep -q "^amazon-ssm-agent.service"; then
  systemctl enable --now amazon-ssm-agent
  log_success "Existing amazon-ssm-agent.service enabled."
else
  SSM_DIR="$(mktemp -d)"
  curl -fsSL "https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_arm64/amazon-ssm-agent.deb" -o "${SSM_DIR}/amazon-ssm-agent.deb"
  dpkg -i "${SSM_DIR}/amazon-ssm-agent.deb"
  rm -rf "${SSM_DIR}"
  systemctl enable --now amazon-ssm-agent
  log_success "AWS SSM Agent (.deb) installed and enabled."
fi

# ------------------------------------------------------------------------------
# 3. Docker CE & Docker Compose Plugin, uv
# ------------------------------------------------------------------------------
if [ "${IS_INCREMENTAL_HOST}" = "true" ]; then
  log_info "3. [Incremental] Verifying pre-installed Docker CE and Compose plugin..."
  systemctl enable --now docker
else
  log_info "3. Installing Docker CE and Docker Compose plugin..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  echo \
    "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null

  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

if id -u ubuntu >/dev/null 2>&1; then
  usermod -aG docker ubuntu
fi
if ! id -u admin >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G sudo,docker admin 2>/dev/null || useradd -m -s /bin/bash admin 2>/dev/null || true
fi
usermod -aG sudo,docker admin 2>/dev/null || true
if [ -d /home/admin ]; then
  grep -q "cd ${APP_DIR}" /home/admin/.bashrc 2>/dev/null || printf '\ncd %s 2>/dev/null || true\n' "${APP_DIR}" >> /home/admin/.bashrc
  chown -R admin:admin /home/admin 2>/dev/null || true
fi
if [ -d /etc/sudoers.d ]; then
  printf "# Managed by brainsOS provision.sh (#332)\nadmin ALL=(ALL:ALL) ALL\n" > /etc/sudoers.d/90-brainsos-admin
  chmod 0440 /etc/sudoers.d/90-brainsos-admin
fi
log_success "Docker CE, Compose plugin, and Linux 'admin' user configured."

log_info "Installing Astral uv..."
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
if [ -x "/usr/local/bin/uv" ]; then
  /usr/local/bin/uv self update >/dev/null 2>&1 || true
  log_success "uv installed at /usr/local/bin/uv ($(/usr/local/bin/uv --version 2>/dev/null || echo 'latest'))."
else
  log_warn "uv not found at /usr/local/bin/uv after install."
fi

# ------------------------------------------------------------------------------
# 4. brainsOS Directory Tree & Systemd Services
# ------------------------------------------------------------------------------
log_info "4. Configuring brainsOS systemd units..."
mkdir -p "${APP_DIR}/data/"{settings,souls,agents,agent_memories,agent_workspaces,agent_apps}
chown -R root:root "${APP_DIR}"

for unit in brainsos.service brainsos-firstboot.service brainsos-system-api.service brainsos-resume.service; do
  if [ ! -f "${CONFIGS_DIR}/${unit}" ]; then
    log_error "Missing systemd unit template: ${CONFIGS_DIR}/${unit}"
    exit 1
  fi
  install -m 0644 "${CONFIGS_DIR}/${unit}" "/etc/systemd/system/${unit}"
done

chmod +x "${SCRIPTS_DIR}/firstboot.sh" "${SCRIPTS_DIR}/harden-host.sh"

systemctl daemon-reload
systemctl enable brainsos-firstboot.service
systemctl enable brainsos.service
systemctl enable brainsos-system-api.service
systemctl enable brainsos-resume.service
log_success "Systemd services enabled (including post-hibernation resume sync)."

# ------------------------------------------------------------------------------
# 5. Host Hardening & Log Safeguards
#    (Safe during build: the Packer communicator is SSM Session Manager by default,
#     so closing inbound 22 does not sever the build session.)
# ------------------------------------------------------------------------------
log_info "5. Executing host perimeter hardening and log rotation setup..."
"${SCRIPTS_DIR}/harden-host.sh"
log_success "Host hardening complete."

# ------------------------------------------------------------------------------
# 6. Pre-build Container Topology & Portal Bundle
#    A throwaway, non-secret provisioning .env is used only for compose
#    interpolation and is removed (and scanned for) before snapshot.
# ------------------------------------------------------------------------------
log_info "6. Pre-building all platform images and the portal bundle..."
cd "${APP_DIR}"
PROVISION_ENV="${APP_DIR}/.env"
cat > "${PROVISION_ENV}" <<EOF
# Temporary provisioning environment (removed before snapshot)
BRAINSOS_DOMAIN=localhost
BRAINSOS_DATA_DIR=${APP_DIR}/data
COMPOSE_FILE=${APP_DIR}/docker-compose.yml:${APP_DIR}/docker/compose/compose.appliance.yml
EOF
cleanup_provision_env() { rm -f "${PROVISION_ENV}"; }
trap cleanup_provision_env EXIT

# 6a. Locally built images (runner base + every compose service with a build: section)
make runner-base build

# 6b. Upstream images (fail the build on any pull failure)
docker compose pull --ignore-buildable
docker pull gitea/gitea:1.22
docker image prune -f >/dev/null 2>&1 || true

# 6c. Verify every image referenced by the appliance topology (including gitea/gitea:1.22) is present locally
MISSING_IMAGES=0
while IFS= read -r img; do
  [ -z "${img}" ] && continue
  if ! docker image inspect "${img}" >/dev/null 2>&1; then
    log_error "Image not present after pre-build: ${img}"
    MISSING_IMAGES=$((MISSING_IMAGES + 1))
  fi
done < <({ docker compose config --images; echo "gitea/gitea:1.22"; } | sort -u)
if [ "${MISSING_IMAGES}" -gt 0 ]; then
  log_error "${MISSING_IMAGES} image(s) missing; first boot would require network builds. Aborting."
  exit 1
fi
log_success "All appliance images are present locally."

# 6d. Portal: install dependencies and compile the production static bundle (dist/).
"${APP_DIR}/scripts/setup/setup-portal.sh"

# 6e. Python .venv with editable platform packages (host queue worker, CLIs).
#     bootstrap-env.sh preserves the provisioning .env; the data/ tree it seeds
#     is wiped in step 7 and re-seeded per instance by firstboot.sh.
if [ -d "${APP_DIR}/.venv" ] && ! "${APP_DIR}/.venv/bin/python" -V >/dev/null 2>&1; then
  rm -rf "${APP_DIR}/.venv"
fi
"${APP_DIR}/scripts/control/bootstrap-env.sh" --skip-images --skip-portal --skip-models
if [ ! -x "${APP_DIR}/.venv/bin/python" ]; then
  log_error "Python virtualenv was not created at ${APP_DIR}/.venv. Aborting."
  exit 1
fi

cleanup_provision_env
trap - EXIT

# ------------------------------------------------------------------------------
# 7. Sanitize Host for Golden AMI Snapshot
# ------------------------------------------------------------------------------
log_info "7. Sanitizing host for AMI snapshot..."

# Prune build-only portal node_modules and uv/uvx binaries after static dist/ and .venv are verified (Ticket #338)
if [ -f "${APP_DIR}/packages/brainsOS-portal/dist/index.html" ]; then
  rm -rf "${APP_DIR}/packages/brainsOS-portal/node_modules"
fi
if [ -x "${APP_DIR}/.venv/bin/python" ]; then
  rm -f /usr/local/bin/uv /usr/local/bin/uvx
fi

# Repository runtime state that provisioning may have produced
rm -f "${APP_DIR}/.env" "${APP_DIR}/.env.bak" "${APP_DIR}/.brainsos-initialized" "${APP_DIR}/.brainsos-wizard-completed"
find "${APP_DIR}" -path "*/node_modules" -prune -o \( -name ".env" -o -name ".env.*" \) ! -name ".env.example" -type f -exec rm -f {} + 2>/dev/null || true
find "${APP_DIR}/data" -type f ! -name ".gitkeep" -delete 2>/dev/null || true
find "${APP_DIR}/data" -depth -mindepth 1 -type d -empty -delete 2>/dev/null || true
git -C "${APP_DIR}" checkout -- data/ 2>/dev/null || true

# SSH: remove Packer's temporary key and host keys (cloud-init regenerates host keys)
rm -f /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys
rm -f /etc/ssh/ssh_host_*

# AWS / tool credentials and build caches that must never persist
rm -rf /root/.aws /home/ubuntu/.aws /root/.docker/config.json /root/.npm
rm -rf /root/.cache/uv /root/.cache/pip
rm -f "${APP_DIR}/.git/hooks/pre-commit"

# Truncate machine-id so each instance generates a unique one
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || true

# Reset cloud-init so per-instance modules (SSH keys, hostname) run on first boot
if command -v cloud-init >/dev/null 2>&1; then
  cloud-init clean --logs --seed || true
fi

# Ensure no builder-sized hibernation swapfile persists in the snapshot
# (hibinit-agent creates /swap-hibinit sized to the launched instance's RAM on first boot)
swapoff /swap-hibinit 2>/dev/null || true
rm -f /swap-hibinit

# Purge superseded AWS kernel packages so only the latest patched kernel remains in /var/lib/dpkg/status
LATEST_IMAGE="$(dpkg-query -W -f='${Package}\t${Status}\n' 2>/dev/null | awk '$2=="install" && $3=="ok" && $4=="installed" && $1 ~ /^linux-image-[0-9]+.*-aws$/ {print $1}' | sort -V | tail -n 1)"
if [ -n "${LATEST_IMAGE}" ]; then
  LATEST_KVER="${LATEST_IMAGE#linux-image-}"
  LATEST_KVER="${LATEST_KVER%-aws}"
  mapfile -t OLD_KERNEL_PKGS < <(
    dpkg-query -W -f='${Package}\t${Status}\n' 2>/dev/null | \
      awk '$2=="install" && $3=="ok" && $4=="installed" {print $1}' | \
      grep -E "^(linux-(image|modules|modules-extra|headers|tools|buildinfo)-[0-9].*-aws|linux-aws(-[0-9.]+)?-(headers|tools)-[0-9].*)$" | \
      grep -vF "${LATEST_KVER}" || true
  )
  if [ "${#OLD_KERNEL_PKGS[@]}" -gt 0 ]; then
    log_info "Purging superseded kernel packages (${OLD_KERNEL_PKGS[*]}), keeping ${LATEST_IMAGE}..."
    DEBIAN_FRONTEND=noninteractive apt-get purge -y --auto-remove "${OLD_KERNEL_PKGS[@]}" || true
    command -v update-grub >/dev/null 2>&1 && update-grub >/dev/null 2>&1 || true
  fi
fi

# Shell histories, temp files, package caches, logs
rm -f /root/.bash_history /home/ubuntu/.bash_history
rm -rf /tmp/* /var/tmp/*
apt-get clean
rm -rf /var/lib/apt/lists/*
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-time=1s >/dev/null 2>&1 || true

# ------------------------------------------------------------------------------
# 8. Fail-Closed Snapshot Scan
# ------------------------------------------------------------------------------
log_info "8. Running fail-closed snapshot scan..."
snapshot_scan "${APP_DIR}" "/"

log_success "brainsOS Golden AMI provisioning complete (ref: ${BRAINSOS_REF:-unknown})."
