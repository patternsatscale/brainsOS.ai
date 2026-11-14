#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Bulk Meeting-Roster EC2 Appliance Fleet Launcher & Day-2 Controller
# Ticket #377 (Milestone v0.5.1 — Dynamic Fleet DNS & Fast AMI Builder)
#
# Launches (or emits a 100% self-contained AWS CloudShell script to launch) a
# fleet of single-tenant brainsOS ARM64 Graviton appliances from a meeting
# participant list, binding each instance to a permanent Route 53 subdomain
# (<slug>.<base_domain>) with automatic Let's Encrypt TLS and streamlined
# 2-step First-Boot Operator Onboarding (#373).
#
# Usage Examples:
#   # 1. Safe Dry-Run Roster Preview (default):
#   ./scripts/control/launch-fleet.sh \
#     --participants "Alice Morgan, Alex Chen, Alex Rivera" \
#     --base-domain demo.infotechlabs.io
#
#   # 2. Emit Self-Contained AWS CloudShell Launch Script (zero local AWS creds needed):
#   ./scripts/control/launch-fleet.sh \
#     --participants "Alice Morgan, Bob Patel, Charlie Kim" \
#     --base-domain demo.infotechlabs.io \
#     --emit-script /tmp/launch-demo-fleet.sh
#
#   # 3. Direct Bulk Launch in Active AWS Account:
#   ./scripts/control/launch-fleet.sh \
#     --participants "Alice Morgan, Bob Patel, Charlie Kim" \
#     --base-domain demo.infotechlabs.io \
#     --fleet workshop-nov14 \
#     --apply
#
#   # 4. Day-2 Post-Meeting Lifecycle (Stop / Hibernate / Start / Terminate):
#   ./scripts/control/launch-fleet.sh --list
#   ./scripts/control/launch-fleet.sh --stop --fleet workshop-nov14
#   ./scripts/control/launch-fleet.sh --hibernate --fleet workshop-nov14
#   ./scripts/control/launch-fleet.sh --start --fleet workshop-nov14
#   ./scripts/control/launch-fleet.sh --terminate --fleet workshop-nov14 --yes
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*" >&2; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || cd "${SCRIPT_DIR}/../.." && pwd)"

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
INSTANCE_TYPE="m7g.xlarge"
VOLUME_SIZE=50
VOLUME_THROUGHPUT=500
VOLUME_IOPS=4000
IAM_PROFILE="instanceRoleBedrock"
SECURITY_GROUP_ID=""
SUBNET_ID=""
AMI_ID=""
BASE_DOMAIN=""
ZONE_ID=""
ACME_EMAIL=""
FLEET_ID=""
PARTICIPANTS_RAW=""
PARTICIPANTS_FILE=""
ROSTER_OUT=""
EMIT_SCRIPT=""
HIBERNATION_CAPABLE=false
ENSURE_IAM_DDNS=true
CONFIRM_YES=false

MODE="dry-run" # dry-run | apply | emit-script | list | stop | start | hibernate | terminate

usage() {
  cat <<EOF
brainsOS Bulk EC2 Appliance Fleet Launcher & Day-2 Lifecycle CLI (Ticket #377)

Usage:
  ./scripts/control/launch-fleet.sh [OPTIONS]

Roster & Domain Options:
  --participants LIST         Comma- or newline-separated participant names (or "slug=Full Name")
  --participants-file PATH    File with one participant name per line
  --base-domain DOMAIN        Parent subdomain for fleet URLs (e.g. demo.infotechlabs.io)
  --zone-id ZONE_ID           Route 53 Hosted Zone ID (auto-discovered from --base-domain if omitted)
  --email EMAIL               ACME TLS email (default: ops@<root-domain>)
  --fleet FLEET_ID            Fleet tag identifier (default: demo-YYYYMMDD-HHMM)
  --roster-out PREFIX         Write <PREFIX>.md and <PREFIX>.csv handoff tables

Compute & IAM Options:
  --ami AMI_ID                brainsOS ARM64 AMI ID (auto-discovers newest self/shared brainsos-* AMI)
  --region REGION             Target AWS region (default: ${AWS_REGION})
  --instance-type TYPE        Graviton ARM64 instance type (default: ${INSTANCE_TYPE})
  --volume-size GB            Root gp3 EBS volume size in GB (default: ${VOLUME_SIZE})
  --profile-name NAME         EC2 IAM Instance Profile (default: ${IAM_PROFILE})
  --security-group SG_ID      Existing Security Group ID (auto-creates/reuses brainsos-fleet-https-sg)
  --subnet-id SUBNET_ID       Explicit VPC Subnet ID (default VPC public subnet if omitted)
  --hibernation-capable       Launch with encrypted root EBS + EC2 Hibernation enabled
  --no-ensure-iam-ddns        Skip best-effort inline Route 53 DDNS policy attachment on IAM role

Execution Modes:
  --dry-run                   Preview sanitized slugs, URLs, and launch plan without AWS writes (default)
  --apply                     Launch the EC2 fleet immediately using active AWS CLI credentials
  --emit-script PATH          Write a 100% self-contained bash script for AWS CloudShell (use '-' for stdout)

Day-2 Fleet Lifecycle Modes:
  --list                      List active brainsOS fleet instances (filterable by --fleet)
  --stop                      Stop running instances in --fleet (EBS preserved; DDNS updates on next start)
  --hibernate                 Hibernate running instances in --fleet (RAM preserved on EBS swap)
  --start                     Start stopped/hibernated instances in --fleet
  --terminate                 Terminate instances in --fleet (requires --yes to execute)
  --yes                       Confirm destructive operations (--terminate)
  -h, --help                  Show this help message
EOF
}

require_arg() {
  if [ -z "${2:-}" ] || { [[ "${2}" == --* ]] && [ "${2}" != "-" ]; }; then
    log_error "Option $1 requires a value."
    exit 1
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --participants)       require_arg "$1" "${2:-}"; PARTICIPANTS_RAW="${PARTICIPANTS_RAW:+${PARTICIPANTS_RAW}$'\n'}$2"; shift 2 ;;
    --participants-file)  require_arg "$1" "${2:-}"; PARTICIPANTS_FILE="$2"; shift 2 ;;
    --base-domain)        require_arg "$1" "${2:-}"; BASE_DOMAIN="$2"; shift 2 ;;
    --zone-id)            require_arg "$1" "${2:-}"; ZONE_ID="$2"; shift 2 ;;
    --email)              require_arg "$1" "${2:-}"; ACME_EMAIL="$2"; shift 2 ;;
    --fleet)              require_arg "$1" "${2:-}"; FLEET_ID="$2"; shift 2 ;;
    --roster-out)         require_arg "$1" "${2:-}"; ROSTER_OUT="$2"; shift 2 ;;
    --ami)                require_arg "$1" "${2:-}"; AMI_ID="$2"; shift 2 ;;
    --region)             require_arg "$1" "${2:-}"; AWS_REGION="$2"; shift 2 ;;
    --instance-type)      require_arg "$1" "${2:-}"; INSTANCE_TYPE="$2"; shift 2 ;;
    --volume-size)        require_arg "$1" "${2:-}"; VOLUME_SIZE="$2"; shift 2 ;;
    --profile-name)       require_arg "$1" "${2:-}"; IAM_PROFILE="$2"; shift 2 ;;
    --security-group)     require_arg "$1" "${2:-}"; SECURITY_GROUP_ID="$2"; shift 2 ;;
    --subnet-id)          require_arg "$1" "${2:-}"; SUBNET_ID="$2"; shift 2 ;;
    --hibernation-capable) HIBERNATION_CAPABLE=true; shift ;;
    --no-ensure-iam-ddns) ENSURE_IAM_DDNS=false; shift ;;
    --dry-run)            MODE="dry-run"; shift ;;
    --apply)              MODE="apply"; shift ;;
    --emit-script)        require_arg "$1" "${2:-}"; EMIT_SCRIPT="$2"; MODE="emit-script"; shift 2 ;;
    --list)               MODE="list"; shift ;;
    --stop)               MODE="stop"; shift ;;
    --hibernate|--pause)  MODE="hibernate"; shift ;;
    --start)              MODE="start"; shift ;;
    --terminate)          MODE="terminate"; shift ;;
    --yes|-y)             CONFIRM_YES=true; shift ;;
    -h|--help)            usage; exit 0 ;;
    *)
      log_error "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

require_aws() {
  if ! command -v aws >/dev/null 2>&1; then
    log_error "AWS CLI v2 is required for --${MODE} (or use --emit-script to generate a CloudShell script)."
    exit 1
  fi
  if ! aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1; then
    log_error "AWS credentials are not configured or expired. Configure AWS CLI or use --emit-script."
    exit 1
  fi
}

# ==============================================================================
# Day-2 Fleet Lifecycle Operations (--list, --stop, --hibernate, --start, --terminate)
# ==============================================================================
case "${MODE}" in
  list)
    require_aws
    FILTERS=("Name=instance-state-name,Values=pending,running,stopping,stopped")
    if [ -n "${FLEET_ID}" ]; then
      FILTERS+=("Name=tag:BrainsOSFleet,Values=${FLEET_ID}")
    else
      FILTERS+=("Name=tag-key,Values=BrainsOSFleet")
    fi
    aws ec2 describe-instances --region "${AWS_REGION}" --filters "${FILTERS[@]}" \
      --query 'Reservations[].Instances[].{
        Fleet: (Tags[?Key==`BrainsOSFleet`]|[0].Value) || `-`,
        Participant: (Tags[?Key==`BrainsOSParticipant`]|[0].Value) || (Tags[?Key==`Name`]|[0].Value) || `-`,
        Domain: (Tags[?Key==`BrainsOSDomain`]|[0].Value) || `-`,
        InstanceId: InstanceId,
        State: State.Name,
        PublicIP: PublicIpAddress || `-`,
        Type: InstanceType
      }' --output table
    exit 0
    ;;

  stop|hibernate|start|terminate)
    if [ -z "${FLEET_ID}" ]; then
      log_error "--${MODE} requires --fleet <fleet-id> to prevent accidental cross-fleet impact."
      exit 1
    fi
    require_aws
    STATE_FILTER="running"
    [ "${MODE}" = "start" ] && STATE_FILTER="stopped"
    [ "${MODE}" = "terminate" ] && STATE_FILTER="pending,running,stopping,stopped"

    mapfile -t TARGET_IDS < <(
      aws ec2 describe-instances --region "${AWS_REGION}" \
        --filters "Name=tag:BrainsOSFleet,Values=${FLEET_ID}" "Name=instance-state-name,Values=${STATE_FILTER}" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null | tr '\t' '\n' | grep -E '^i-' || true
    )

    if [ "${#TARGET_IDS[@]}" -eq 0 ]; then
      log_warn "No matching instances in state [${STATE_FILTER}] found for fleet '${FLEET_ID}' in ${AWS_REGION}."
      exit 0
    fi

    log_info "Fleet '${FLEET_ID}' (${AWS_REGION}) matched ${#TARGET_IDS[@]} instance(s): ${TARGET_IDS[*]}"
    case "${MODE}" in
      stop)
        aws ec2 stop-instances --region "${AWS_REGION}" --instance-ids "${TARGET_IDS[@]}" >/dev/null
        log_success "Initiated stop for ${#TARGET_IDS[@]} instance(s) in fleet '${FLEET_ID}'."
        ;;
      hibernate)
        aws ec2 stop-instances --region "${AWS_REGION}" --hibernate --instance-ids "${TARGET_IDS[@]}" >/dev/null
        log_success "Initiated hibernation for ${#TARGET_IDS[@]} instance(s) in fleet '${FLEET_ID}'."
        ;;
      start)
        aws ec2 start-instances --region "${AWS_REGION}" --instance-ids "${TARGET_IDS[@]}" >/dev/null
        log_success "Initiated start for ${#TARGET_IDS[@]} instance(s) in fleet '${FLEET_ID}'. Route 53 A records will self-update within ~60s of boot."
        ;;
      terminate)
        if [ "${CONFIRM_YES}" != true ]; then
          log_warn "[SAFETY GATE] Re-run with --terminate --fleet ${FLEET_ID} --yes to permanently terminate: ${TARGET_IDS[*]}"
          exit 1
        fi
        aws ec2 terminate-instances --region "${AWS_REGION}" --instance-ids "${TARGET_IDS[@]}" >/dev/null
        log_success "Terminated ${#TARGET_IDS[@]} instance(s) in fleet '${FLEET_ID}'."
        ;;
    esac
    exit 0
    ;;
esac

# ==============================================================================
# Roster Parsing, Noise Stripping & Deterministic DNS Slug Disambiguation
# ==============================================================================
if [ -n "${PARTICIPANTS_FILE}" ]; then
  if [ ! -f "${PARTICIPANTS_FILE}" ]; then
    log_error "Participants file not found: ${PARTICIPANTS_FILE}"
    exit 1
  fi
  PARTICIPANTS_RAW="${PARTICIPANTS_RAW:+${PARTICIPANTS_RAW}$'\n'}$(cat "${PARTICIPANTS_FILE}")"
fi

if [ -z "${PARTICIPANTS_RAW}" ]; then
  log_error "Provide --participants \"Alice Morgan, Bob Patel\" or --participants-file <path>."
  exit 1
fi

if [ -z "${BASE_DOMAIN}" ]; then
  log_error "--base-domain <domain> is required (e.g. --base-domain demo.infotechlabs.io)."
  exit 1
fi

BASE_DOMAIN="$(printf '%s' "${BASE_DOMAIN}" | tr '[:upper:]' '[:lower:]' | sed -E 's|^https?://||; s|/.*$||; s|^\.+||; s|\.+$||')"
if ! printf '%s' "${BASE_DOMAIN}" | grep -qE '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'; then
  log_error "Invalid --base-domain: ${BASE_DOMAIN}"
  exit 1
fi

if [ -z "${ACME_EMAIL}" ]; then
  ROOT_DOMAIN="$(printf '%s' "${BASE_DOMAIN}" | awk -F. '{if (NF>=2) print $(NF-1)"."$NF; else print $0}')"
  ACME_EMAIL="ops@${ROOT_DOMAIN}"
fi

if [ -z "${FLEET_ID}" ]; then
  FLEET_ID="demo-$(date +%Y%m%d-%H%M)"
fi

ZONE_ID="${ZONE_ID#*hostedzone/}"

mapfile -t ROSTER_LINES < <(
  PARTICIPANTS_INPUT="${PARTICIPANTS_RAW}" python3 - <<'PY'
import os
import re
import sys
import unicodedata

RESERVED = {
    "admin", "akadmin", "root", "system", "operator", "api", "www",
    "mail", "sogo", "git", "proxy", "lens", "langfuse", "ns1", "ns2",
}

UI_NOISE_PARENS = re.compile(
    r"\s*[\(\[\{]\s*(?:host|co-host|you|me|guest|presenter|organizer|external|unverified|"
    r"she/her|he/him|they/them| muted|speaking)[^)\]\}]*[\)\]\}]\s*",
    re.IGNORECASE,
)
TITLES = re.compile(r"^(?:dr|mr|mrs|ms|prof|sir|rev)\.?\s+", re.IGNORECASE)


def ascii_slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:32].strip("-")


raw = os.environ.get("PARTICIPANTS_INPUT", "")
tokens = []
for line in raw.splitlines():
    for part in line.split(","):
        part = part.strip()
        if part and not part.startswith("#"):
            tokens.append(part)

entries = []
for tok in tokens:
    explicit_slug = None
    display = tok
    if "=" in tok:
        left, right = tok.split("=", 1)
        cand = ascii_slug(left)
        if cand:
            explicit_slug = cand
            display = right.strip()

    cleaned = UI_NOISE_PARENS.sub(" ", display)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—•·|0123456789.")
    cleaned = TITLES.sub("", cleaned).strip()
    if not cleaned:
        continue

    words = [ascii_slug(w) for w in cleaned.split() if ascii_slug(w)]
    if not words:
        continue

    first = words[0]
    last = words[-1] if len(words) > 1 else ""
    entries.append({
        "display": cleaned,
        "explicit": explicit_slug,
        "first": first,
        "last": last,
    })

if not entries:
    sys.exit(2)

# Count first-name collisions among non-explicit entries
first_counts = {}
for e in entries:
    if not e["explicit"]:
        first_counts[e["first"]] = first_counts.get(e["first"], 0) + 1

used = set()
for e in entries:
    if e["explicit"]:
        base = e["explicit"]
        if base in RESERVED:
            base = f"{base}-u"
        slug = base
    else:
        first, last = e["first"], e["last"]
        if first_counts.get(first, 0) > 1 and last:
            cand = f"{first}{last[0]}"
            if cand in used or cand in RESERVED:
                cand = f"{first}-{last}"
            slug = cand[:32].strip("-")
        else:
            slug = first

        if slug in RESERVED:
            slug = f"{slug}{last[0]}" if last else f"{slug}-u"

    orig = slug
    idx = 2
    while slug in used or slug in RESERVED:
        slug = f"{orig}-{idx}"
        idx += 1
    used.add(slug)
    print(f"{slug}|{e['display']}")
PY
) || {
  log_error "No valid participant names could be parsed from input."
  exit 1
}

log_info "Parsed ${#ROSTER_LINES[@]} participant(s) for fleet '${FLEET_ID}' under *.${BASE_DOMAIN}."

# ==============================================================================
# Helper: Discover Route 53 Zone ID, AMI, IAM Profile & Security Group
# ==============================================================================
discover_zone_id() {
  local domain="$1"
  local candidate="${domain}"
  while [[ "${candidate}" == *.* ]]; do
    local zid
    zid="$(aws route53 list-hosted-zones-by-name --dns-name "${candidate}." --max-items 5 \
      --query "HostedZones[?Name=='${candidate}.' && Config.PrivateZone==\`false\`] | [0].Id" \
      --output text 2>/dev/null || true)"
    zid="${zid#*hostedzone/}"
    if [ -n "${zid}" ] && [ "${zid}" != "None" ]; then
      printf '%s' "${zid}"
      return 0
    fi
    candidate="${candidate#*.}"
  done
  return 1
}

discover_ami_id() {
  local found=""
  found="$(aws ec2 describe-images --region "${AWS_REGION}" --owners self \
    --filters "Name=name,Values=brainsos-*" "Name=architecture,Values=arm64" "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text 2>/dev/null || true)"
  if [ -z "${found}" ] || [ "${found}" = "None" ]; then
    found="$(aws ec2 describe-images --region "${AWS_REGION}" --executable-users self \
      --filters "Name=name,Values=brainsos-*" "Name=architecture,Values=arm64" "Name=state,Values=available" \
      --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text 2>/dev/null || true)"
  fi
  if [ -n "${found}" ] && [ "${found}" != "None" ]; then
    printf '%s' "${found}"
    return 0
  fi
  return 1
}

# ==============================================================================
# Mode 1: Dry-Run Preview (Default)
# ==============================================================================
if [ "${MODE}" = "dry-run" ]; then
  if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1; then
    [ -z "${ZONE_ID}" ] && ZONE_ID="$(discover_zone_id "${BASE_DOMAIN}" || true)"
    [ -z "${AMI_ID}" ] && AMI_ID="$(discover_ami_id || true)"
  fi

  echo ""
  echo "### 🚀 brainsOS Fleet Launch Preview (DRY-RUN)"
  echo ""
  echo "- **Fleet Tag (`BrainsOSFleet`)**: \`${FLEET_ID}\`"
  echo "- **Region / Instance Type**: \`${AWS_REGION}\` / \`${INSTANCE_TYPE}\` (\`${VOLUME_SIZE} GB gp3\`)"
  echo "- **AMI ID**: \`${AMI_ID:-<auto-discover newest self/shared brainsos-* ARM64 AMI>}\`"
  echo "- **Route 53 Zone ID**: \`${ZONE_ID:-<auto-discover from ${BASE_DOMAIN}>}\`"
  echo "- **IAM Instance Profile**: \`${IAM_PROFILE}\`"
  echo "- **Hibernation Capable**: \`${HIBERNATION_CAPABLE}\`"
  echo ""
  echo "| # | Participant | EC2 Name Tag | Permanent Appliance URL | Onboarding Flow |"
  echo "|---|---|---|---|---|"
  idx=1
  for entry in "${ROSTER_LINES[@]}"; do
    slug="${entry%%|*}"
    name="${entry#*|}"
    echo "| ${idx} | ${name} | \`${slug}\` | https://${slug}.${BASE_DOMAIN} | 2-Step Operator Account + SSL Auto |"
    idx=$((idx + 1))
  done
  echo ""
  log_info "Dry-run complete. Pass --apply to launch directly or --emit-script <file.sh> for AWS CloudShell."
  exit 0
fi

# ==============================================================================
# Mode 2: Emit Self-Contained AWS CloudShell Script (--emit-script)
# ==============================================================================
if [ "${MODE}" = "emit-script" ]; then
  render_cloudshell_script() {
    cat <<EOF
#!/usr/bin/env bash
# ==============================================================================
# brainsOS Self-Contained Bulk Fleet Launcher (AWS CloudShell / Local AWS CLI)
# Generated by scripts/control/launch-fleet.sh (#377)
# Fleet ID: ${FLEET_ID} | Domain: *.${BASE_DOMAIN} | Count: ${#ROSTER_LINES[@]}
# ==============================================================================
set -euo pipefail

AWS_REGION="\${AWS_REGION:-${AWS_REGION}}"
BASE_DOMAIN="${BASE_DOMAIN}"
ZONE_ID="${ZONE_ID}"
AMI_ID="${AMI_ID}"
INSTANCE_TYPE="\${INSTANCE_TYPE:-${INSTANCE_TYPE}}"
VOLUME_SIZE="${VOLUME_SIZE}"
VOLUME_THROUGHPUT="${VOLUME_THROUGHPUT}"
VOLUME_IOPS="${VOLUME_IOPS}"
IAM_PROFILE="\${IAM_PROFILE:-${IAM_PROFILE}}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID}"
SUBNET_ID="${SUBNET_ID}"
ACME_EMAIL="${ACME_EMAIL}"
FLEET_ID="${FLEET_ID}"
HIBERNATION_CAPABLE="${HIBERNATION_CAPABLE}"
ENSURE_IAM_DDNS="${ENSURE_IAM_DDNS}"

ROSTER=(
EOF
    for entry in "${ROSTER_LINES[@]}"; do
      printf '  %q\n' "${entry}"
    done
    cat <<'EOF'
)

echo "[INFO] Verifying AWS caller identity in ${AWS_REGION}..."
ACCOUNT_ID="$(aws sts get-caller-identity --region "${AWS_REGION}" --query 'Account' --output text)"
echo "[INFO] Authenticated to AWS Account: ${ACCOUNT_ID} (Region: ${AWS_REGION})"

# 1. Auto-discover Route 53 Hosted Zone ID if not pinned
if [ -z "${ZONE_ID}" ]; then
  CAND="${BASE_DOMAIN}"
  while [[ "${CAND}" == *.* ]]; do
    ZID="$(aws route53 list-hosted-zones-by-name --dns-name "${CAND}." --max-items 5 \
      --query "HostedZones[?Name=='${CAND}.' && Config.PrivateZone==\`false\`] | [0].Id" --output text 2>/dev/null || true)"
    ZID="${ZID#*hostedzone/}"
    if [ -n "${ZID}" ] && [ "${ZID}" != "None" ]; then
      ZONE_ID="${ZID}"
      break
    fi
    CAND="${CAND#*.}"
  done
fi
if [ -z "${ZONE_ID}" ]; then
  echo "[ERROR] Could not auto-discover public Route 53 Hosted Zone for ${BASE_DOMAIN}. Set ZONE_ID=Z... and re-run." >&2
  exit 1
fi
echo "[INFO] Using Route 53 Hosted Zone: ${ZONE_ID}"

# 2. Auto-discover latest self-owned or shared brainsOS ARM64 AMI
if [ -z "${AMI_ID}" ]; then
  AMI_ID="$(aws ec2 describe-images --region "${AWS_REGION}" --owners self \
    --filters "Name=name,Values=brainsos-*" "Name=architecture,Values=arm64" "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text 2>/dev/null || true)"
  if [ -z "${AMI_ID}" ] || [ "${AMI_ID}" = "None" ]; then
    AMI_ID="$(aws ec2 describe-images --region "${AWS_REGION}" --executable-users self \
      --filters "Name=name,Values=brainsos-*" "Name=architecture,Values=arm64" "Name=state,Values=available" \
      --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text 2>/dev/null || true)"
  fi
fi
if [ -z "${AMI_ID}" ] || [ "${AMI_ID}" = "None" ]; then
  echo "[ERROR] No available brainsos-* ARM64 AMI found (self-owned or shared with ${ACCOUNT_ID}) in ${AWS_REGION}." >&2
  exit 1
fi
echo "[INFO] Using brainsOS ARM64 AMI: ${AMI_ID}"

# 3. Resolve IAM Instance Profile & best-effort attach Route 53 DDNS inline policy
if ! aws iam get-instance-profile --instance-profile-name "${IAM_PROFILE}" >/dev/null 2>&1; then
  FALLBACK_PROFILE="$(aws iam list-instance-profiles \
    --query "InstanceProfiles[?contains(InstanceProfileName, 'Bedrock') || contains(InstanceProfileName, 'brainsos')].[InstanceProfileName] | [0][0]" \
    --output text 2>/dev/null || true)"
  if [ -n "${FALLBACK_PROFILE}" ] && [ "${FALLBACK_PROFILE}" != "None" ]; then
    IAM_PROFILE="${FALLBACK_PROFILE}"
  else
    echo "[ERROR] IAM Instance Profile '${IAM_PROFILE}' not found. Set IAM_PROFILE=<profile-name>." >&2
    exit 1
  fi
fi
echo "[INFO] Using IAM Instance Profile: ${IAM_PROFILE}"

if [ "${ENSURE_IAM_DDNS}" = "true" ]; then
  ROLE_NAME="$(aws iam get-instance-profile --instance-profile-name "${IAM_PROFILE}" \
    --query 'InstanceProfile.Roles[0].RoleName' --output text 2>/dev/null || true)"
  if [ -n "${ROLE_NAME}" ] && [ "${ROLE_NAME}" != "None" ]; then
    POLICY_DOC="$(cat <<POL
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BrainsOSDynamicFleetDNS",
      "Effect": "Allow",
      "Action": ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"],
      "Resource": "arn:aws:route53:::hostedzone/${ZONE_ID}"
    },
    {
      "Sid": "BrainsOSGetChange",
      "Effect": "Allow",
      "Action": ["route53:GetChange"],
      "Resource": "*"
    }
  ]
}
POL
)"
    if aws iam put-role-policy --role-name "${ROLE_NAME}" \
      --policy-name "brainsos-route53-ddns-${ZONE_ID}" \
      --policy-document "${POLICY_DOC}" >/dev/null 2>&1; then
      echo "[INFO] Verified Route 53 DDNS policy on role '${ROLE_NAME}' for zone ${ZONE_ID}."
    else
      echo "[WARN] Could not auto-attach inline Route 53 policy to '${ROLE_NAME}' (ensure it has route53:ChangeResourceRecordSets on ${ZONE_ID})." >&2
    fi
  fi
fi

# 4. Resolve VPC & Security Group (TCP 80 + 443 inbound only; port 22 closed)
VPC_ID=""
if [ -n "${SUBNET_ID}" ]; then
  VPC_ID="$(aws ec2 describe-subnets --region "${AWS_REGION}" --subnet-ids "${SUBNET_ID}" \
    --query 'Subnets[0].VpcId' --output text)"
else
  VPC_ID="$(aws ec2 describe-vpcs --region "${AWS_REGION}" --filters "Name=isDefault,Values=true" \
    --query 'Vpcs[0].VpcId' --output text 2>/dev/null || true)"
  if [ -z "${VPC_ID}" ] || [ "${VPC_ID}" = "None" ]; then
    VPC_ID="$(aws ec2 describe-vpcs --region "${AWS_REGION}" --query 'Vpcs[0].VpcId' --output text)"
  fi
fi

if [ -z "${SECURITY_GROUP_ID}" ]; then
  SECURITY_GROUP_ID="$(aws ec2 describe-security-groups --region "${AWS_REGION}" \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=brainsos-fleet-https-sg" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
  if [ -z "${SECURITY_GROUP_ID}" ] || [ "${SECURITY_GROUP_ID}" = "None" ]; then
    SECURITY_GROUP_ID="$(aws ec2 create-security-group --region "${AWS_REGION}" \
      --vpc-id "${VPC_ID}" \
      --group-name "brainsos-fleet-https-sg" \
      --description "brainsOS Appliance Fleet HTTPS Ingress (ports 80/443 only)" \
      --query 'GroupId' --output text)"
    aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SECURITY_GROUP_ID}" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
    aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SECURITY_GROUP_ID}" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
  fi
fi
echo "[INFO] Using Security Group: ${SECURITY_GROUP_ID} (ports 80/443 open, port 22 closed)"

# 5. Launch Fleet Instances
ROSTER_MD="${FLEET_ID}-roster.md"
ROSTER_CSV="${FLEET_ID}-roster.csv"
printf "participant,url,instance_id,fqdn,fleet_id\n" > "${ROSTER_CSV}"
{
  echo "### 🎉 brainsOS Participant Handoff Roster (\`${FLEET_ID}\`)"
  echo ""
  echo "| Participant | Permanent Appliance URL | First-Boot Instance ID Key |"
  echo "|---|---|---|"
} > "${ROSTER_MD}"

for entry in "${ROSTER[@]}"; do
  slug="${entry%%|*}"
  name="${entry#*|}"
  fqdn="${slug}.${BASE_DOMAIN}"

  USER_DATA="$(cat <<UD
#cloud-config
brainsos:
  domain: ${fqdn}
  route53_zone_id: ${ZONE_ID}
  email: ${ACME_EMAIL}
UD
)"

  ENCRYPTED_FLAG="false"
  HIB_ARGS=()
  if [ "${HIBERNATION_CAPABLE}" = "true" ]; then
    ENCRYPTED_FLAG="true"
    HIB_ARGS=(--hibernation-options "Configured=true")
  fi

  SUBNET_ARGS=()
  if [ -n "${SUBNET_ID}" ]; then
    SUBNET_ARGS=(--subnet-id "${SUBNET_ID}" --associate-public-ip-address)
  fi

  TAG_SPEC_JSON="$(SLUG="${slug}" FLEET="${FLEET_ID}" PNAME="${name}" FQDN="${fqdn}" python3 -c '
import json, os
print(json.dumps([{
  "ResourceType": "instance",
  "Tags": [
    {"Key": "Name", "Value": os.environ["SLUG"]},
    {"Key": "BrainsOSFleet", "Value": os.environ["FLEET"]},
    {"Key": "BrainsOSParticipant", "Value": os.environ["PNAME"]},
    {"Key": "BrainsOSDomain", "Value": os.environ["FQDN"]},
  ],
}]))
')"

  INST_ID="$(aws ec2 run-instances --region "${AWS_REGION}" \
    --image-id "${AMI_ID}" \
    --instance-type "${INSTANCE_TYPE}" \
    --security-group-ids "${SECURITY_GROUP_ID}" \
    ${SUBNET_ARGS[@]+"${SUBNET_ARGS[@]}"} \
    --iam-instance-profile "Name=${IAM_PROFILE}" \
    --user-data "${USER_DATA}" \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=${VOLUME_SIZE},VolumeType=gp3,Throughput=${VOLUME_THROUGHPUT},Iops=${VOLUME_IOPS},DeleteOnTermination=true,Encrypted=${ENCRYPTED_FLAG}}" \
    ${HIB_ARGS[@]+"${HIB_ARGS[@]}"} \
    --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled,InstanceMetadataTags=enabled" \
    --tag-specifications "${TAG_SPEC_JSON}" \
    --query 'Instances[0].InstanceId' --output text)"

  echo "[SUCCESS] Launched ${name} -> https://${fqdn} (${INST_ID})"
  echo "| ${name} | https://${fqdn} | \`${INST_ID}\` |" >> "${ROSTER_MD}"
  printf '"%s","https://%s","%s","%s","%s"\n' "${name}" "${fqdn}" "${INST_ID}" "${fqdn}" "${FLEET_ID}" >> "${ROSTER_CSV}"
done

echo ""
cat "${ROSTER_MD}"
echo ""
echo "[INFO] Saved handoff files: ${ROSTER_MD} and ${ROSTER_CSV}"
echo "[INFO] Note: Allow ~60-90 seconds for Route 53 DNS + Let's Encrypt TLS initialization."
echo "[INFO] Post-demo cleanup:"
echo "  Stop all:      aws ec2 stop-instances --region ${AWS_REGION} --instance-ids \$(aws ec2 describe-instances --region ${AWS_REGION} --filters Name=tag:BrainsOSFleet,Values=${FLEET_ID} Name=instance-state-name,Values=running --query 'Reservations[].Instances[].InstanceId' --output text)"
echo "  Terminate all: aws ec2 terminate-instances --region ${AWS_REGION} --instance-ids \$(aws ec2 describe-instances --region ${AWS_REGION} --filters Name=tag:BrainsOSFleet,Values=${FLEET_ID} Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text)"
EOF
  }

  if [ "${EMIT_SCRIPT}" = "-" ]; then
    render_cloudshell_script
  else
    mkdir -p "$(dirname "${EMIT_SCRIPT}")"
    render_cloudshell_script > "${EMIT_SCRIPT}"
    chmod +x "${EMIT_SCRIPT}"
    log_success "Wrote self-contained bulk fleet launcher script to: ${EMIT_SCRIPT}"
    log_info "Upload/run in AWS CloudShell or execute locally: bash ${EMIT_SCRIPT}"
  fi
  exit 0
fi

# ==============================================================================
# Mode 3: Direct Bulk Launch (--apply)
# ==============================================================================
require_aws

TMP_LAUNCH_SH="$(mktemp "${TMPDIR:-/tmp}/brainsos-launch-fleet.XXXXXX.sh")"
trap 'rm -f "${TMP_LAUNCH_SH}"' EXIT

"${BASH_SOURCE[0]}" \
  --participants "${PARTICIPANTS_RAW}" \
  --base-domain "${BASE_DOMAIN}" \
  ${ZONE_ID:+--zone-id "${ZONE_ID}"} \
  --email "${ACME_EMAIL}" \
  --fleet "${FLEET_ID}" \
  ${AMI_ID:+--ami "${AMI_ID}"} \
  --region "${AWS_REGION}" \
  --instance-type "${INSTANCE_TYPE}" \
  --volume-size "${VOLUME_SIZE}" \
  --profile-name "${IAM_PROFILE}" \
  ${SECURITY_GROUP_ID:+--security-group "${SECURITY_GROUP_ID}"} \
  ${SUBNET_ID:+--subnet-id "${SUBNET_ID}"} \
  $([ "${HIBERNATION_CAPABLE}" = true ] && echo "--hibernation-capable") \
  $([ "${ENSURE_IAM_DDNS}" = false ] && echo "--no-ensure-iam-ddns") \
  --emit-script "${TMP_LAUNCH_SH}"

WORK_DIR="$(pwd)"
if [ -n "${ROSTER_OUT}" ]; then
  mkdir -p "$(dirname "${ROSTER_OUT}")"
fi

bash "${TMP_LAUNCH_SH}"

if [ -n "${ROSTER_OUT}" ]; then
  mv -f "${WORK_DIR}/${FLEET_ID}-roster.md" "${ROSTER_OUT}.md" 2>/dev/null || true
  mv -f "${WORK_DIR}/${FLEET_ID}-roster.csv" "${ROSTER_OUT}.csv" 2>/dev/null || true
  log_success "Roster exported to ${ROSTER_OUT}.md and ${ROSTER_OUT}.csv"
fi
