#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Claim & Resume Persistent User EBS Volume on Warm-Standby Appliance
# Ticket #382
#
# Attaches/mounts a per-user persistent EBS data volume on a warm-standby EC2
# appliance VM, initializes or resumes the user's persistent .env and data/
# state without regenerating database credentials on returning volumes, links
# /opt/brainsos/.env -> <mount>/.env, starts brainsOS services, and waits for
# the HTTPS ingress health gate (:443) to respond.
# ==============================================================================

set -euo pipefail

# Ensure sbin directories are in PATH for blkid, mkfs.ext4, fuser, udevadm
for sbin_dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
  if [ -d "${sbin_dir}" ] && [[ ":${PATH}:" != *":${sbin_dir}:"* ]]; then
    export PATH="${PATH}:${sbin_dir}"
  fi
done

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

DEVICE="${BRAINSOS_USER_DEVICE:-}"
MOUNT_PATH="${BRAINSOS_MOUNT_ROOT:-/mnt/brainsos-data}"
CLAIM_DOMAIN="${BRAINSOS_CLAIM_DOMAIN:-}"
USER_SUB="${BRAINSOS_USER_SUB:-}"
SKIP_PORTAL_REBUILD="true"
SKIP_MOUNT=false
SKIP_SERVICE_START=false
SKIP_HEALTH_WAIT=false
HEALTH_TIMEOUT=300
HEALTH_URL="${BRAINSOS_CLAIM_HEALTH_URL:-https://127.0.0.1:443/}"
DRY_RUN=false

usage() {
  cat <<EOF
brainsOS Warm-Standby User Volume Claim & Resume Engine (Ticket #382)

Usage:
  sudo ./scripts/control/claim-user-volume.sh [OPTIONS]

Options:
  --device <dev>                  Block device or raw image path (auto-detected if omitted)
  --mount <path>                  Mount directory (default: /mnt/brainsos-data)
  --domain <fqdn>                 External FQDN for BRAINSOS_DOMAIN & BRAINSOS_URL
                                  (e.g. user.demo.example.com)
  --user-sub <sub>                External OIDC/Cognito user subject (BRAINSOS_USER_SUB)
  --skip-portal-rebuild [bool]    Skip rebuilding Portal SPA (default: true)
  --rebuild-portal                Rebuild Portal SPA bundle during claim
  --skip-mount                    Skip kernel mount syscall (pre-mounted dir / rootless tests)
  --skip-service-start            Do not start systemd services after volume preparation
  --skip-health-wait              Do not poll HTTPS health gate after service start
  --health-timeout <sec>          Seconds to wait for HTTPS health gate (default: 300)
  --health-url <url>              Health gate URL (default: https://127.0.0.1:443/)
  --dry-run                       Simulate claim actions without modifying disk or services
  -h, --help                      Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --device)
      DEVICE="${2:?--device requires a device path}"
      shift 2
      ;;
    --mount|--mount-root)
      MOUNT_PATH="${2:?--mount requires a directory path}"
      shift 2
      ;;
    --domain)
      CLAIM_DOMAIN="${2:?--domain requires an FQDN}"
      shift 2
      ;;
    --user-sub)
      USER_SUB="${2:?--user-sub requires a subject identifier}"
      shift 2
      ;;
    --skip-portal-rebuild)
      if [[ "${2:-}" =~ ^(true|false|1|0|yes|no|TRUE|FALSE|YES|NO)$ ]]; then
        case "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" in
          true|1|yes) SKIP_PORTAL_REBUILD="true" ;;
          false|0|no) SKIP_PORTAL_REBUILD="false" ;;
        esac
        shift 2
      else
        SKIP_PORTAL_REBUILD="true"
        shift
      fi
      ;;
    --skip-portal-rebuild=*)
      case "$(printf '%s' "${1#*=}" | tr '[:upper:]' '[:lower:]')" in
        true|1|yes) SKIP_PORTAL_REBUILD="true" ;;
        false|0|no) SKIP_PORTAL_REBUILD="false" ;;
        *)
          log_error "Invalid value for --skip-portal-rebuild: ${1#*=}"
          exit 1
          ;;
      esac
      shift
      ;;
    --rebuild-portal)
      SKIP_PORTAL_REBUILD="false"
      shift
      ;;
    --skip-mount)
      SKIP_MOUNT=true
      shift
      ;;
    --skip-service-start)
      SKIP_SERVICE_START=true
      shift
      ;;
    --skip-health-wait)
      SKIP_HEALTH_WAIT=true
      shift
      ;;
    --health-timeout)
      HEALTH_TIMEOUT="${2:?--health-timeout requires seconds}"
      shift 2
      ;;
    --health-url)
      HEALTH_URL="${2:?--health-url requires a URL}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

MOUNT_PATH="${MOUNT_PATH%/}"
if [ -z "${MOUNT_PATH}" ] || [ "${MOUNT_PATH}" = "/" ]; then
  log_error "Refusing unsafe --mount path: '${MOUNT_PATH:-/}'"
  exit 1
fi

strip_value() { local v="${1%%#*}"; printf '%s' "${v}" | tr -d "\"' \r"; }
normalize_url_host() {
  local raw="$1"
  raw="${raw#http://}"
  raw="${raw#https://}"
  raw="${raw%%/*}"
  raw="${raw%%:*}"
  printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]' | tr -d ' '
}
is_ipv4() { [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; }

NORM_CLAIM_DOMAIN=""
if [ -n "${CLAIM_DOMAIN}" ]; then
  NORM_CLAIM_DOMAIN="$(normalize_url_host "$(strip_value "${CLAIM_DOMAIN}")")"
fi

# ------------------------------------------------------------------------------
# Helper: Auto-detect first unmounted secondary EBS block device (Nitro NVMe / xvd)
# ------------------------------------------------------------------------------
detect_unmounted_ebs_device() {
  local root_src root_real root_pkname root_disk=""
  root_src="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
  root_real="$(readlink -f "${root_src}" 2>/dev/null || printf '%s' "${root_src}")"
  if [ -n "${root_real}" ] && command -v lsblk >/dev/null 2>&1; then
    root_pkname="$(lsblk -ndo PKNAME "${root_real}" 2>/dev/null | head -n 1 || true)"
    if [ -n "${root_pkname}" ]; then
      root_disk="/dev/${root_pkname}"
    else
      root_disk="${root_real}"
    fi
  fi

  # 1. Check standard EC2 attachment symlink aliases first (/dev/sdf, /dev/xvdf)
  local alias_dev resolved_alias
  for alias_dev in /dev/sdf /dev/xvdf /dev/sdg /dev/xvdg; do
    if [ -b "${alias_dev}" ]; then
      resolved_alias="$(readlink -f "${alias_dev}" 2>/dev/null || printf '%s' "${alias_dev}")"
      if [ "${resolved_alias}" != "${root_disk}" ] && [ "${resolved_alias}" != "${root_real}" ]; then
        if ! lsblk -nr -o MOUNTPOINT "${resolved_alias}" 2>/dev/null | grep -q '.'; then
          printf '%s\n' "${resolved_alias}"
          return 0
        fi
      fi
    fi
  done

  # 2. Scan lsblk top-level disks, excluding root disk, loop, ram, zram, sr, dm, md
  if command -v lsblk >/dev/null 2>&1; then
    local dev_path dev_type
    while read -r dev_path dev_type; do
      [ "${dev_type}" = "disk" ] || continue
      case "$(basename "${dev_path}")" in
        loop*|ram*|zram*|sr*|fd*|dm-*|md*) continue ;;
      esac
      [ "${dev_path}" = "${root_disk}" ] && continue
      [ "${dev_path}" = "${root_real}" ] && continue

      # Skip if any mountpoint (or [SWAP]) is active anywhere on this disk or its partitions
      if lsblk -nr -o MOUNTPOINT "${dev_path}" 2>/dev/null | grep -q '.'; then
        continue
      fi

      # If the disk has no direct filesystem but has exactly one child partition, use the partition
      local direct_fs part_list part_count
      direct_fs="$(blkid -o value -s TYPE "${dev_path}" 2>/dev/null || true)"
      if [ -z "${direct_fs}" ]; then
        part_list="$(lsblk -nr -o PATH,TYPE "${dev_path}" 2>/dev/null | awk '$2=="part" {print $1}')"
        part_count="$(printf '%s\n' "${part_list}" | sed '/^$/d' | wc -l | tr -d ' ')"
        if [ "${part_count}" -eq 1 ]; then
          printf '%s\n' "${part_list}"
          return 0
        fi
      fi

      printf '%s\n' "${dev_path}"
      return 0
    done < <(lsblk -ndo PATH,TYPE 2>/dev/null)
  fi

  return 1
}

# ------------------------------------------------------------------------------
# Helper: Fail-closed filesystem check; formats ONLY confirmed blank volumes
# ------------------------------------------------------------------------------
ensure_device_filesystem() {
  local dev="$1"
  local blkid_raw="" blkid_rc=0 fstype="" ptype="" probe_out="" probe_rc=0

  set +e
  blkid_raw="$(blkid "${dev}" 2>/dev/null)"
  blkid_rc=$?
  fstype="$(blkid -o value -s TYPE "${dev}" 2>/dev/null || true)"
  ptype="$(blkid -p -o value -s PTTYPE "${dev}" 2>/dev/null || true)"
  probe_out="$(blkid -p "${dev}" 2>/dev/null)"
  probe_rc=$?
  set -e

  if [ -n "${fstype}" ]; then
    log_info "Existing ${fstype} filesystem detected on ${dev} — preserving volume without formatting."
    return 0
  fi

  if [ -n "${ptype}" ]; then
    log_error "Partition table (${ptype}) detected on ${dev} with no direct filesystem; specify a partition device instead. Refusing to format."
    exit 1
  fi

  # util-linux blkid exits 2 ONLY when the device was opened & probed cleanly with zero signatures
  if [ "${blkid_rc}" -ne 2 ] || [ "${probe_rc}" -ne 2 ] || [ -n "${blkid_raw}" ] || [ -n "${probe_out}" ]; then
    log_error "Refusing to format ${dev}: unable to confirm blank unformatted volume (blkid rc=${blkid_rc}, probe rc=${probe_rc})."
    exit 1
  fi

  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Blank volume confirmed on ${dev}; would run: mkfs.ext4 -F -L brainsos-user ${dev}"
    return 0
  fi

  log_info "Blank unformatted volume confirmed on ${dev} — formatting ext4 (label: brainsos-user)..."
  mkfs.ext4 -F -L brainsos-user "${dev}"
  log_success "Formatted ${dev} as ext4 (label: brainsos-user)."
}

# ------------------------------------------------------------------------------
# 1. Block Device Inspection, Conditional Formatting & Mount
# ------------------------------------------------------------------------------
ALREADY_MOUNTED=false
if command -v mountpoint >/dev/null 2>&1 && [ -d "${MOUNT_PATH}" ] && mountpoint -q "${MOUNT_PATH}"; then
  ALREADY_MOUNTED=true
fi

if [ "${SKIP_MOUNT}" = true ]; then
  # When --device is also explicitly provided alongside --skip-mount (e.g. .img file tests),
  # run the production blkid/mkfs.ext4 probe against DEVICE and skip only the mount syscall.
  if [ -n "${DEVICE}" ] && [ "${ALREADY_MOUNTED}" = false ]; then
    command -v udevadm >/dev/null 2>&1 && udevadm settle --timeout=10 2>/dev/null || true
    if [ ! -b "${DEVICE}" ] && [ ! -f "${DEVICE}" ]; then
      log_error "Device or image file not found: ${DEVICE}"
      exit 1
    fi
    REAL_DEV="$(readlink -f "${DEVICE}" 2>/dev/null || printf '%s' "${DEVICE}")"
    ensure_device_filesystem "${REAL_DEV}"
  fi
  if [ "${DRY_RUN}" = false ]; then
    mkdir -p "${MOUNT_PATH}"
  fi
else
  if [ "${DRY_RUN}" = false ]; then
    mkdir -p "${MOUNT_PATH}"
  fi

  if [ "${ALREADY_MOUNTED}" = true ]; then
    CURRENT_SRC="$(findmnt -n -o SOURCE "${MOUNT_PATH}" 2>/dev/null || true)"
    if [ -n "${DEVICE}" ]; then
      EXPECTED_REAL="$(readlink -f "${DEVICE}" 2>/dev/null || printf '%s' "${DEVICE}")"
      CURRENT_REAL="$(readlink -f "${CURRENT_SRC}" 2>/dev/null || printf '%s' "${CURRENT_SRC}")"
      LOOP_BACK=""
      if [[ "${CURRENT_REAL}" == /dev/loop* ]] && command -v losetup >/dev/null 2>&1; then
        LOOP_BACK="$(losetup -n -O BACK-FILE "${CURRENT_REAL}" 2>/dev/null | head -n 1 || true)"
        [ -n "${LOOP_BACK}" ] && LOOP_BACK="$(readlink -f "${LOOP_BACK}" 2>/dev/null || printf '%s' "${LOOP_BACK}")"
      fi
      if [ "${CURRENT_REAL}" != "${EXPECTED_REAL}" ] && [ "${LOOP_BACK}" != "${EXPECTED_REAL}" ]; then
        log_error "${MOUNT_PATH} is already mounted from ${CURRENT_SRC} (expected ${DEVICE})."
        exit 1
      fi
    fi
    log_info "${MOUNT_PATH} is already mounted (${CURRENT_SRC}); skipping format and mount."
  else
    command -v udevadm >/dev/null 2>&1 && udevadm settle --timeout=10 2>/dev/null || true
    if [ -z "${DEVICE}" ]; then
      if [ "${DRY_RUN}" = true ]; then
        DEVICE="$(detect_unmounted_ebs_device || echo "/dev/nvme1n1")"
        log_info "[DRY-RUN] Auto-selected target device: ${DEVICE}"
      else
        if ! DEVICE="$(detect_unmounted_ebs_device)"; then
          log_error "No unmounted secondary EBS block device detected. Attach an EBS volume first or pass --device <dev>."
          exit 1
        fi
        log_info "Auto-detected unmounted secondary block device: ${DEVICE}"
      fi
    fi

    if [ "${DRY_RUN}" = false ] || [ -e "${DEVICE}" ]; then
      for _wait_i in $(seq 1 10); do
        if [ -b "${DEVICE}" ] || [ -f "${DEVICE}" ]; then
          break
        fi
        [ "${DRY_RUN}" = true ] && break
        sleep 1
      done
      if [ ! -b "${DEVICE}" ] && [ ! -f "${DEVICE}" ]; then
        log_error "Device not found (expected block device or raw image): ${DEVICE}"
        exit 1
      fi
      REAL_DEV="$(readlink -f "${DEVICE}" 2>/dev/null || printf '%s' "${DEVICE}")"
      ensure_device_filesystem "${REAL_DEV}"
    else
      REAL_DEV="${DEVICE}"
      log_info "[DRY-RUN] Would probe ${REAL_DEV} via blkid and format ext4 if blank."
    fi

    if [ "${DRY_RUN}" = true ]; then
      if [ -f "${REAL_DEV}" ]; then
        log_info "[DRY-RUN] Would mount image ${REAL_DEV} at ${MOUNT_PATH} (-o loop,noatime)"
      else
        log_info "[DRY-RUN] Would mount device ${REAL_DEV} at ${MOUNT_PATH} (-o noatime)"
      fi
    else
      if [ -f "${REAL_DEV}" ]; then
        log_info "Mounting loop image ${REAL_DEV} at ${MOUNT_PATH} (-o loop,noatime)..."
        mount -o loop,noatime "${REAL_DEV}" "${MOUNT_PATH}"
      else
        log_info "Mounting block device ${REAL_DEV} at ${MOUNT_PATH} (-o noatime)..."
        mount -o noatime "${REAL_DEV}" "${MOUNT_PATH}"
      fi
      log_success "Mounted ${REAL_DEV} at ${MOUNT_PATH}."
    fi
  fi
fi

if [ "${DRY_RUN}" = false ]; then
  mkdir -p "${MOUNT_PATH}/data"
fi

# ------------------------------------------------------------------------------
# 2. First-Time User Volume vs. Returning User Volume
# ------------------------------------------------------------------------------
if [ ! -f "${MOUNT_PATH}/.env" ]; then
  log_info "No existing environment at ${MOUNT_PATH}/.env — initializing new user volume via firstboot.sh..."
  FIRSTBOOT_ARGS=(--claim --mount-root "${MOUNT_PATH}")
  [ -n "${NORM_CLAIM_DOMAIN}" ] && FIRSTBOOT_ARGS+=(--domain "${NORM_CLAIM_DOMAIN}")
  [ -n "${USER_SUB}" ] && FIRSTBOOT_ARGS+=(--user-sub "${USER_SUB}")
  [ "${SKIP_PORTAL_REBUILD}" = "true" ] && FIRSTBOOT_ARGS+=(--skip-portal)
  [ "${BRAINSOS_FIRSTBOOT_SKIP_IMDS:-false}" = "true" ] && FIRSTBOOT_ARGS+=(--skip-imds)
  [ "${DRY_RUN}" = "true" ] && FIRSTBOOT_ARGS+=(--dry-run)

  BRAINSOS_REPO_ROOT="${REPO_ROOT}" \
  BRAINSOS_CLAIM_ACTIVE="true" \
  BRAINSOS_MOUNT_ROOT="${MOUNT_PATH}" \
  BRAINSOS_DATA_DIR="${MOUNT_PATH}/data" \
  BRAINSOS_FIRSTBOOT_SKIP_PORTAL="${SKIP_PORTAL_REBUILD}" \
  "${SCRIPT_DIR}/firstboot.sh" "${FIRSTBOOT_ARGS[@]}"

  if [ "${DRY_RUN}" = false ]; then
    ln -sfn "${MOUNT_PATH}/.env" "${REPO_ROOT}/.env"
    ln -sfn "${MOUNT_PATH}/.brainsos-initialized" "${REPO_ROOT}/.brainsos-initialized"
  fi
else
  log_info "Existing user environment detected at ${MOUNT_PATH}/.env — resuming persistent state (preserving DB/service credentials)."

  # Query current host IMDSv2 for updated instance ID, IPs, and region
  IMDS_TOKEN=""
  INSTANCE_ID=""
  LOCAL_IPV4=""
  PUBLIC_IPV4=""
  AWS_REGION_DETECTED=""

  if [ "${BRAINSOS_FIRSTBOOT_SKIP_IMDS:-false}" != "true" ] && command -v curl >/dev/null 2>&1; then
    IMDS_TOKEN="$(curl -s -f -X PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
      --connect-timeout 2 --max-time 3 2>/dev/null || true)"
    if [ -n "${IMDS_TOKEN}" ]; then
      imds_get() {
        curl -s -f -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
          "http://169.254.169.254/latest/meta-data/$1" --connect-timeout 2 --max-time 3 2>/dev/null || true
      }
      INSTANCE_ID="$(imds_get instance-id)"
      LOCAL_IPV4="$(imds_get local-ipv4)"
      PUBLIC_IPV4="$(imds_get public-ipv4)"
      AWS_REGION_DETECTED="$(imds_get placement/region)"
    fi
  fi

  # Test & baremetal overrides
  [ -n "${BRAINSOS_FIRSTBOOT_INSTANCE_ID:-}" ] && INSTANCE_ID="${BRAINSOS_FIRSTBOOT_INSTANCE_ID}"
  [ -n "${BRAINSOS_FIRSTBOOT_PUBLIC_IPV4:-}" ] && PUBLIC_IPV4="${BRAINSOS_FIRSTBOOT_PUBLIC_IPV4}"
  [ -n "${BRAINSOS_FIRSTBOOT_LOCAL_IPV4:-}" ] && LOCAL_IPV4="${BRAINSOS_FIRSTBOOT_LOCAL_IPV4}"
  [ -n "${BRAINSOS_FIRSTBOOT_REGION:-}" ] && AWS_REGION_DETECTED="${BRAINSOS_FIRSTBOOT_REGION}"

  EFFECTIVE_DOMAIN="${NORM_CLAIM_DOMAIN}"
  if [ -z "${EFFECTIVE_DOMAIN}" ]; then
    EFFECTIVE_DOMAIN="$(grep -E '^BRAINSOS_DOMAIN=' "${MOUNT_PATH}/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\"'" || true)"
  fi

  # Build host-specific overrides ONLY (never touch DB or Authentik/Portal passwords)
  RESUME_OVERRIDES=(
    "BRAINSOS_MOUNT_ROOT=${MOUNT_PATH}"
    "BRAINSOS_DATA_DIR=${MOUNT_PATH}/data"
    "COMPOSE_FILE=${REPO_ROOT}/docker-compose.yml:${REPO_ROOT}/docker/compose/compose.appliance.yml"
    "LITELLM_CONFIG=${REPO_ROOT}/config/litellm/config.bedrock.yaml"
  )
  if [ -n "${INSTANCE_ID}" ]; then
    RESUME_OVERRIDES+=("BRAINSOS_INSTANCE_ID=${INSTANCE_ID}")
  fi
  if [ -n "${PUBLIC_IPV4}" ] || [ -n "${LOCAL_IPV4}" ]; then
    IP_SITES=""
    for ip in "${PUBLIC_IPV4}" "${LOCAL_IPV4}"; do
      if [ -n "${ip}" ] && is_ipv4 "${ip}" && [ "${ip}" != "${EFFECTIVE_DOMAIN}" ]; then
        case " ${IP_SITES} " in *" ${ip} "*) ;; *) IP_SITES="${IP_SITES:+${IP_SITES} }${ip}" ;; esac
      fi
    done
    [ -z "${IP_SITES}" ] && IP_SITES="127.0.0.1"
    RESUME_OVERRIDES+=("BRAINSOS_IP_SITES=${IP_SITES}")
    if [ -n "${PUBLIC_IPV4}" ]; then
      RESUME_OVERRIDES+=("BRAINSOS_LAST_SYNCED_IP=${PUBLIC_IPV4}")
    fi
  fi
  if [ -n "${AWS_REGION_DETECTED}" ]; then
    RESUME_OVERRIDES+=(
      "AWS_REGION=${AWS_REGION_DETECTED}"
      "AWS_DEFAULT_REGION=${AWS_REGION_DETECTED}"
    )
  fi
  if [ -n "${NORM_CLAIM_DOMAIN}" ]; then
    RESUME_OVERRIDES+=(
      "BRAINSOS_DOMAIN=${NORM_CLAIM_DOMAIN}"
      "BRAINSOS_URL=${NORM_CLAIM_DOMAIN}"
      "NEXTAUTH_URL=https://${NORM_CLAIM_DOMAIN}"
    )
  fi
  if [ -n "${USER_SUB}" ]; then
    RESUME_OVERRIDES+=("BRAINSOS_USER_SUB=${USER_SUB}")
  fi

  if [ "${DRY_RUN}" = true ]; then
    log_info "[DRY-RUN] Would link ${REPO_ROOT}/.env -> ${MOUNT_PATH}/.env"
    log_info "[DRY-RUN] Would upsert host overrides into ${MOUNT_PATH}/.env: ${RESUME_OVERRIDES[*]}"
  else
    if [ ! -f "${MOUNT_PATH}/.brainsos-initialized" ]; then
      date -u +"%Y-%m-%dT%H:%M:%SZ" > "${MOUNT_PATH}/.brainsos-initialized"
    fi
    chmod 644 "${MOUNT_PATH}/.brainsos-initialized"
    chmod 600 "${MOUNT_PATH}/.env"

    ln -sfn "${MOUNT_PATH}/.env" "${REPO_ROOT}/.env"
    ln -sfn "${MOUNT_PATH}/.brainsos-initialized" "${REPO_ROOT}/.brainsos-initialized"

    BRAINSOS_REPO_ROOT="${REPO_ROOT}" "${REPO_ROOT}/scripts/control/env-upsert.sh" \
      --file "${REPO_ROOT}/.env" \
      --section "Warm-Standby Resume Overrides (written by claim-user-volume.sh)" \
      "${RESUME_OVERRIDES[@]}"

    if [ "${BRAINSOS_FIRSTBOOT_SKIP_BOOTSTRAP:-false}" != "true" ] && [ -x "${REPO_ROOT}/scripts/control/bootstrap-env.sh" ]; then
      BRAINSOS_REPO_ROOT="${REPO_ROOT}" "${REPO_ROOT}/scripts/control/bootstrap-env.sh" \
        --data-dir "${MOUNT_PATH}/data" \
        --skip-images \
        --skip-portal \
        --skip-models </dev/null
    fi

    if [ "${SKIP_PORTAL_REBUILD}" = "false" ] && [ -x "${REPO_ROOT}/scripts/setup/setup-portal.sh" ]; then
      log_info "Rebuilding Portal SPA bundle (--rebuild-portal)..."
      "${REPO_ROOT}/scripts/setup/setup-portal.sh" || log_warn "Portal rebuild failed; keeping existing bundle."
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 3. Start Appliance Services & Wait for HTTPS Ingress Health Gate (:443)
# ------------------------------------------------------------------------------
if [ "${DRY_RUN}" = true ]; then
  if [ "${SKIP_SERVICE_START}" != true ]; then
    log_info "[DRY-RUN] Would start brainsos-system-api.service and brainsos.service"
  fi
  if [ "${SKIP_SERVICE_START}" != true ] && [ "${SKIP_HEALTH_WAIT}" != true ]; then
    log_info "[DRY-RUN] Would wait up to ${HEALTH_TIMEOUT}s for ${HEALTH_URL}"
  fi
  log_success "[DRY-RUN] User volume claim simulation complete."
  exit 0
fi

if [ "${SKIP_SERVICE_START}" != true ]; then
  if command -v systemctl >/dev/null 2>&1; then
    log_info "Starting brainsos-system-api.service and brainsos.service..."
    systemctl start brainsos-system-api.service 2>/dev/null || log_warn "brainsos-system-api.service start returned non-zero (continuing)."
    systemctl start brainsos.service
    log_success "Appliance systemd services started."
  else
    log_warn "systemctl not found on PATH; skipping systemd unit start."
  fi
fi

if [ "${SKIP_SERVICE_START}" != true ] && [ "${SKIP_HEALTH_WAIT}" != true ]; then
  log_info "Waiting up to ${HEALTH_TIMEOUT}s for ingress health gate (${HEALTH_URL})..."
  DEADLINE=$(( $(date +%s) + HEALTH_TIMEOUT ))
  HEALTH_OK=false
  LAST_HTTP="000"
  while [ "$(date +%s)" -le "${DEADLINE}" ]; do
    LAST_HTTP="$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 5 "${HEALTH_URL}" 2>/dev/null || echo "000")"
    if [[ "${LAST_HTTP}" =~ ^(200|301|302|303|307|308|401)$ ]]; then
      HEALTH_OK=true
      break
    fi
    sleep 2
  done

  if [ "${HEALTH_OK}" != true ]; then
    log_error "Ingress health gate timed out after ${HEALTH_TIMEOUT}s (${HEALTH_URL} last HTTP status: ${LAST_HTTP})."
    exit 1
  fi
  log_success "Ingress health gate passed (${HEALTH_URL} -> HTTP ${LAST_HTTP})."
fi

log_success "User volume claim complete at ${MOUNT_PATH}."
