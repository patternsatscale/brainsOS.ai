#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Standalone Fleet Launcher & Launch-Template CLI Wizard
# Tickets #377 / #380 (Milestone v0.5.1)
#
# 100% standalone, zero-repo-dependency utility for macOS (Bash 3.2+), Linux,
# WSL, and AWS CloudShell. Requires only: bash, aws CLI v2, and python3.
#
# Quick Install & Run on Any Work Computer:
#   curl -fsSL https://raw.githubusercontent.com/patternsatscale/brainsOS.ai/main/scripts/control/launch-fleet.sh -o launch-fleet.sh
#   chmod +x launch-fleet.sh
#   ./launch-fleet.sh
#
# Interactive Mode (Default when run with no flags):
#   ./launch-fleet.sh
#
# Non-Interactive Examples:
#   # Launch 8 instances (user01..user08) from an existing EC2 Launch Template:
#   ./launch-fleet.sh --launch-template brainsos-demo --count 8 --base-domain demo.infotechlabs.io --apply
#
#   # Launch named participants from a Launch Template:
#   ./launch-fleet.sh --launch-template lt-0123456789abcdef0 \
#     --participants "Alice Morgan, Bob Patel" --base-domain demo.infotechlabs.io --apply
#
#   # Day-2 Fleet Lifecycle:
#   ./launch-fleet.sh --list
#   ./launch-fleet.sh --stop --fleet demo-20261114-1830
#   ./launch-fleet.sh --start --fleet demo-20261114-1830
#   ./launch-fleet.sh --terminate --fleet demo-20261114-1830 --yes
# ==============================================================================

set -euo pipefail

VERSION="0.5.1"

if [ -t 1 ] || [ -t 2 ]; then
  BOLD='\033[1m'
  DIM='\033[2m'
  CYAN='\033[0;36m'
  GREEN='\033[0;32m'
  BLUE='\033[0;34m'
  YELLOW='\033[1;33m'
  RED='\033[0;31m'
  NC='\033[0m'
else
  BOLD='' DIM='' CYAN='' GREEN='' BLUE='' YELLOW='' RED='' NC=''
fi

log_info()    { printf "%b[INFO]%b %s\n" "${BLUE}" "${NC}" "$*" >&2; }
log_success() { printf "%b[SUCCESS]%b %s\n" "${GREEN}" "${NC}" "$*" >&2; }
log_warn()    { printf "%b[WARN]%b %s\n" "${YELLOW}" "${NC}" "$*" >&2; }
log_error()   { printf "%b[ERROR]%b %s\n" "${RED}" "${NC}" "$*" >&2; }

on_interrupt() {
  printf "\n%bExiting brainsOS Fleet Utility. Goodbye!%b\n" "${DIM}" "${NC}" >&2
  exit 0
}
trap on_interrupt INT

AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
INSTANCE_TYPE=""
INSTANCE_TYPE_DEFAULT="m7g.xlarge"
VOLUME_SIZE=50
VOLUME_THROUGHPUT=500
VOLUME_IOPS=4000
IAM_PROFILE="instanceRoleBedrock"
SECURITY_GROUP_ID=""
SUBNET_ID=""
AMI_ID=""
LAUNCH_TEMPLATE=""
LT_VERSION="\$Latest"
BASE_DOMAIN=""
ZONE_ID=""
ACME_EMAIL=""
FLEET_ID=""
PARTICIPANTS_RAW=""
PARTICIPANTS_FILE=""
INSTANCE_COUNT=""
SLUG_PREFIX="user"
ROSTER_OUT=""
EMIT_SCRIPT=""
HIBERNATION_CAPABLE=false
ENSURE_IAM_DDNS=true
CONFIRM_YES=false

MODE="" # wizard | dry-run | apply | emit-script | list | stop | start | hibernate | terminate

usage() {
  cat <<EOF
brainsOS Fleet Launcher & Interactive Launch-Template Wizard (v${VERSION})

Usage:
  ./launch-fleet.sh                  Launch interactive menu & Launch-Template wizard
  ./launch-fleet.sh [OPTIONS]        Run via CLI flags (scriptable / CI / AI Skills)

Launch Template & Compute Options:
  --wizard                    Start interactive TUI menu & Launch-Template picker
  --launch-template ID|NAME   EC2 Launch Template ID (lt-...) or Name
  --lt-version VERSION        Launch Template version (default: \$Latest)
  --ami AMI_ID                brainsOS ARM64 AMI ID (if not using a Launch Template)
  --region REGION             Target AWS region (default: active AWS CLI region or us-east-1)
  --profile PROFILE           AWS CLI named profile (--profile / \$AWS_PROFILE)
  --instance-type TYPE        Override EC2 instance type (default in Direct AMI mode: ${INSTANCE_TYPE_DEFAULT})
  --volume-size GB            Root gp3 EBS size in GB in Direct AMI mode (default: ${VOLUME_SIZE})
  --profile-name NAME         IAM Instance Profile in Direct AMI mode (default: ${IAM_PROFILE})
  --security-group SG_ID      Security Group ID in Direct AMI mode
  --subnet-id SUBNET_ID       Explicit VPC Subnet ID
  --hibernation-capable       Enable encrypted root EBS + EC2 Hibernation

Instance Naming & Sizing Options:
  --count N                   Create N numbered instances (<prefix>01 .. <prefix>N)
  --prefix PREFIX             Subdomain prefix when using --count (default: ${SLUG_PREFIX})
  --participants LIST         Comma- or newline-separated names (or "slug=Full Name")
  --participants-file PATH    File with one participant name per line
  --base-domain DOMAIN        Parent subdomain for fleet URLs (e.g. demo.infotechlabs.io)
  --zone-id ZONE_ID           Route 53 Hosted Zone ID (auto-discovered from --base-domain if omitted)
  --email EMAIL               ACME TLS email (default: ops@<root-domain>)
  --fleet FLEET_ID            Fleet tag identifier (default: demo-YYYYMMDD-HHMM)
  --roster-out PREFIX         Write <PREFIX>.md and <PREFIX>.csv handoff tables
  --no-ensure-iam-ddns        Skip best-effort inline Route 53 DDNS policy check on IAM role

Execution & Day-2 Lifecycle Modes:
  --dry-run                   Preview sanitized slugs, URLs, and launch plan without AWS writes
  --apply                     Launch the EC2 fleet immediately using active AWS CLI credentials
  --emit-script PATH          Write a self-contained bash launch script (use '-' for stdout)
  --list                      List active brainsOS fleet instances (filterable by --fleet)
  --stop                      Stop running instances in --fleet (EBS preserved; DDNS updates on start)
  --hibernate                 Hibernate running instances in --fleet (RAM preserved on EBS swap)
  --start                     Start stopped/hibernated instances in --fleet
  --terminate                 Terminate instances in --fleet (requires --yes)
  --yes, -y                   Confirm destructive operations (--terminate)
  -h, --help                  Show this help message
EOF
}

require_arg() {
  if [ -z "${2:-}" ] || { [[ "${2}" == --* ]] && [ "${2}" != "-" ]; }; then
    log_error "Option $1 requires a value."
    exit 1
  fi
}

ORIGINAL_ARGC=$#

while [ $# -gt 0 ]; do
  case "$1" in
    --wizard|-i)          MODE="wizard"; shift ;;
    --launch-template|--lt) require_arg "$1" "${2:-}"; LAUNCH_TEMPLATE="$2"; shift 2 ;;
    --lt-version)         require_arg "$1" "${2:-}"; LT_VERSION="$2"; shift 2 ;;
    --count|-n)           require_arg "$1" "${2:-}"; INSTANCE_COUNT="$2"; shift 2 ;;
    --prefix)             require_arg "$1" "${2:-}"; SLUG_PREFIX="$2"; shift 2 ;;
    --participants)       require_arg "$1" "${2:-}"; PARTICIPANTS_RAW="${PARTICIPANTS_RAW:+${PARTICIPANTS_RAW}$'\n'}$2"; shift 2 ;;
    --participants-file)  require_arg "$1" "${2:-}"; PARTICIPANTS_FILE="$2"; shift 2 ;;
    --base-domain)        require_arg "$1" "${2:-}"; BASE_DOMAIN="$2"; shift 2 ;;
    --zone-id)            require_arg "$1" "${2:-}"; ZONE_ID="$2"; shift 2 ;;
    --email)              require_arg "$1" "${2:-}"; ACME_EMAIL="$2"; shift 2 ;;
    --fleet)              require_arg "$1" "${2:-}"; FLEET_ID="$2"; shift 2 ;;
    --roster-out)         require_arg "$1" "${2:-}"; ROSTER_OUT="$2"; shift 2 ;;
    --ami)                require_arg "$1" "${2:-}"; AMI_ID="$2"; shift 2 ;;
    --region)             require_arg "$1" "${2:-}"; AWS_REGION="$2"; shift 2 ;;
    --profile)            require_arg "$1" "${2:-}"; export AWS_PROFILE="$2"; shift 2 ;;
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

# Default to interactive wizard if invoked with zero arguments
if [ "${ORIGINAL_ARGC}" -eq 0 ] && [ -z "${MODE}" ]; then
  MODE="wizard"
elif [ -z "${MODE}" ]; then
  MODE="dry-run"
fi

# Resolve default region from AWS config if not explicitly set
if [ -z "${AWS_REGION}" ]; then
  if command -v aws >/dev/null 2>&1; then
    AWS_REGION="$(aws configure get region 2>/dev/null || true)"
  fi
  AWS_REGION="${AWS_REGION:-us-east-1}"
fi

# ==============================================================================
# Core Helpers (AWS Pre-flight, Discovery, Sanitizer & Launch Engine)
# ==============================================================================
require_prereqs() {
  if ! command -v python3 >/dev/null 2>&1; then
    log_error "python3 is required on PATH."
    exit 1
  fi
}

AWS_ACCOUNT_ID=""
AWS_CALLER_ARN=""

require_aws() {
  require_prereqs
  if ! command -v aws >/dev/null 2>&1; then
    log_error "AWS CLI v2 is required (https://docs.aws.amazon.com/cli/)."
    exit 1
  fi
  local ident
  ident="$(aws sts get-caller-identity --region "${AWS_REGION}" --output json 2>/dev/null || true)"
  if [ -z "${ident}" ]; then
    log_error "AWS credentials are not configured or expired (profile: ${AWS_PROFILE:-default})."
    log_info "Run 'aws sso login' or 'aws configure' and try again."
    exit 1
  fi
  AWS_ACCOUNT_ID="$(IDENT="${ident}" python3 -c 'import json,os; print(json.loads(os.environ["IDENT"]).get("Account",""))')"
  AWS_CALLER_ARN="$(IDENT="${ident}" python3 -c 'import json,os; print(json.loads(os.environ["IDENT"]).get("Arn",""))')"
}

clean_domain() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's|^https?://||; s|/.*$||; s|^\.+||; s|\.+$||; s|[[:space:]]||g'
}

validate_domain() {
  printf '%s' "$1" | grep -qE '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'
}

default_email_for_domain() {
  printf '%s' "$1" | awk -F. '{if (NF>=2) print "ops@"$(NF-1)"."$NF; else print "ops@"$0}'
}

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

# Inspect a Launch Template (by lt-... ID or Name) and return JSON metadata
inspect_launch_template_json() {
  local lt_ref="$1"
  local ver="${2:-\$Latest}"
  local lt_desc=""
  if [[ "${lt_ref}" =~ ^lt-[0-9a-f]+$ ]]; then
    lt_desc="$(aws ec2 describe-launch-templates --region "${AWS_REGION}" --launch-template-ids "${lt_ref}" --output json 2>/dev/null || true)"
  else
    lt_desc="$(aws ec2 describe-launch-templates --region "${AWS_REGION}" --launch-template-names "${lt_ref}" --output json 2>/dev/null || true)"
  fi
  if [ -z "${lt_desc}" ]; then
    return 1
  fi
  local lt_id
  lt_id="$(LT_DESC="${lt_desc}" python3 -c 'import json,os; lts=json.loads(os.environ["LT_DESC"]).get("LaunchTemplates",[]); print(lts[0]["LaunchTemplateId"] if lts else "")')"
  if [ -z "${lt_id}" ]; then
    return 1
  fi
  local ver_desc
  ver_desc="$(aws ec2 describe-launch-template-versions --region "${AWS_REGION}" --launch-template-id "${lt_id}" --versions "${ver}" --output json 2>/dev/null || true)"
  if [ -z "${ver_desc}" ]; then
    return 1
  fi
  LT_DESC="${lt_desc}" VER_DESC="${ver_desc}" python3 - <<'PY'
import base64, json, os, re

lt = json.loads(os.environ["LT_DESC"])["LaunchTemplates"][0]
vers = json.loads(os.environ["VER_DESC"]).get("LaunchTemplateVersions", [])
if not vers:
    raise SystemExit(1)
v = vers[0]
data = v.get("LaunchTemplateData", {})

ud_b64 = data.get("UserData", "")
ud_text = ""
if ud_b64:
    try:
        ud_text = base64.b64decode(ud_b64).decode("utf-8", errors="replace")
    except Exception:
        ud_text = ""

ud_base_domain = ""
ud_zone_id = ""
ud_email = ""
for line in ud_text.splitlines():
    s = line.strip()
    m_bd = re.match(r"^(?:BRAINSOS_BASE_DOMAIN|base_domain)\s*[=:]\s*(.+)$", s)
    if m_bd:
        ud_base_domain = m_bd.group(1).split("#")[0].strip().strip("\"'")
    m_z = re.match(r"^(?:BRAINSOS_ROUTE53_ZONE_ID|HOSTED_ZONE_ID|route53_zone_id)\s*[=:]\s*(.+)$", s)
    if m_z:
        ud_zone_id = m_z.group(1).split("#")[0].strip().strip("\"'").split("hostedzone/")[-1]
    m_e = re.match(r"^(?:ACME_EMAIL|email)\s*[=:]\s*(.+)$", s)
    if m_e:
        ud_email = m_e.group(1).split("#")[0].strip().strip("\"'")

iam_prof = data.get("IamInstanceProfile", {})
iam_name = iam_prof.get("Name") or (iam_prof.get("Arn", "").split("/")[-1] if iam_prof.get("Arn") else "")

inst_tags = {}
for ts in data.get("TagSpecifications", []):
    if ts.get("ResourceType") == "instance":
        for t in ts.get("Tags", []):
            if "Key" in t and "Value" in t:
                inst_tags[t["Key"]] = t["Value"]

out = {
    "id": lt["LaunchTemplateId"],
    "name": lt["LaunchTemplateName"],
    "resolved_version": str(v.get("VersionNumber", "")),
    "default_version": str(lt.get("DefaultVersionNumber", "")),
    "latest_version": str(lt.get("LatestVersionNumber", "")),
    "image_id": data.get("ImageId", ""),
    "instance_type": data.get("InstanceType", ""),
    "iam_profile": iam_name,
    "has_network_interfaces": bool(data.get("NetworkInterfaces")),
    "user_data": ud_text,
    "ud_base_domain": ud_base_domain,
    "ud_zone_id": ud_zone_id,
    "ud_email": ud_email,
    "instance_tags": inst_tags,
}
print(json.dumps(out))
PY
}

# Build ROSTER_LINES array ("slug|Display Name") from either INSTANCE_COUNT or PARTICIPANTS_RAW
ROSTER_LINES=()
build_roster_lines() {
  ROSTER_LINES=()
  if [ -n "${INSTANCE_COUNT}" ]; then
    if ! [[ "${INSTANCE_COUNT}" =~ ^[0-9]+$ ]] || [ "${INSTANCE_COUNT}" -lt 1 ] || [ "${INSTANCE_COUNT}" -gt 200 ]; then
      log_error "--count must be an integer between 1 and 200 (got: ${INSTANCE_COUNT})."
      return 1
    fi
    while IFS= read -r line; do
      [ -n "${line}" ] && ROSTER_LINES+=("${line}")
    done < <(
      COUNT="${INSTANCE_COUNT}" PREFIX="${SLUG_PREFIX}" python3 - <<'PY'
import os, re
count = int(os.environ["COUNT"])
prefix = re.sub(r"[^a-z0-9-]+", "", os.environ.get("PREFIX", "user").lower()).strip("-") or "user"
if prefix in {"admin", "akadmin", "root", "api", "www", "mail", "sogo", "git", "proxy"}:
    prefix = f"{prefix}-box"
width = max(2, len(str(count)))
for i in range(1, count + 1):
    num = str(i).zfill(width)
    slug = f"{prefix}{num}"
    label = f"{prefix.capitalize()} {num}"
    print(f"{slug}|{label}")
PY
    )
    return 0
  fi

  if [ -z "${PARTICIPANTS_RAW}" ]; then
    log_error "Provide --participants, --participants-file, or --count <N>."
    return 1
  fi

  while IFS= read -r line; do
    [ -n "${line}" ] && ROSTER_LINES+=("${line}")
  done < <(
    PARTICIPANTS_INPUT="${PARTICIPANTS_RAW}" python3 - <<'PY'
import os, re, sys, unicodedata

RESERVED = {
    "admin", "akadmin", "root", "system", "operator", "api", "www",
    "mail", "sogo", "git", "proxy", "lens", "langfuse", "ns1", "ns2",
}
UI_NOISE_PARENS = re.compile(
    r"\s*[\(\[\{]\s*(?:host|co-host|you|me|guest|presenter|organizer|external|unverified|"
    r"she/her|he/him|they/them|muted|speaking)[^)\]\}]*[\)\]\}]\s*",
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
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—•·|.")
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned)
    cleaned = TITLES.sub("", cleaned).strip()
    if not cleaned:
        continue

    words = [ascii_slug(w) for w in cleaned.split() if ascii_slug(w)]
    if not words:
        continue

    first = words[0]
    last = words[-1] if len(words) > 1 else ""
    entries.append({"display": cleaned, "explicit": explicit_slug, "first": first, "last": last})

if not entries:
    sys.exit(2)

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
    log_error "No valid participant names could be parsed."
    return 1
  }
  return 0
}

ensure_iam_ddns_policy() {
  local profile_name="$1"
  local zone_id="$2"
  [ "${ENSURE_IAM_DDNS}" = "true" ] || return 0
  [ -n "${profile_name}" ] && [ -n "${zone_id}" ] || return 0

  local role_name
  role_name="$(aws iam get-instance-profile --instance-profile-name "${profile_name}" \
    --query 'InstanceProfile.Roles[0].RoleName' --output text 2>/dev/null || true)"
  if [ -n "${role_name}" ] && [ "${role_name}" != "None" ]; then
    local policy_doc
    policy_doc="$(cat <<POL
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BrainsOSDynamicFleetDNS",
      "Effect": "Allow",
      "Action": ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"],
      "Resource": "arn:aws:route53:::hostedzone/${zone_id}"
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
    if aws iam put-role-policy --role-name "${role_name}" \
      --policy-name "brainsos-route53-ddns-${zone_id}" \
      --policy-document "${policy_doc}" >/dev/null 2>&1; then
      log_info "Verified Route 53 DDNS permission on role '${role_name}' (zone ${zone_id})."
    else
      log_warn "Skipped IAM role inline policy update on '${role_name}' (ensure route53:ChangeResourceRecordSets is attached for ${zone_id})."
    fi
  fi
}

# Build merged User-Data for an instance, preserving Launch Template UserData if present
compose_instance_userdata() {
  local base_ud="$1"
  local fqdn="$2"
  local zone_id="$3"
  local email="$4"

  BASE_UD="${base_ud}" FQDN="${fqdn}" ZID="${zone_id}" EMAIL="${email}" python3 - <<'PY'
import os, re

base = os.environ.get("BASE_UD", "")
fqdn = os.environ["FQDN"]
zid = os.environ["ZID"]
email = os.environ["EMAIL"]

if not base.strip():
    print(f"#cloud-config\nbrainsos:\n  domain: {fqdn}\n  route53_zone_id: {zid}\n  email: {email}")
elif base.lstrip().startswith("#!"):
    # Shell script UserData: strip any stale BRAINSOS_DOMAIN assignment and append clean shell assignments
    kept = [
        ln for ln in base.splitlines()
        if not re.match(r"^\s*(?:BRAINSOS_DOMAIN|RECORD_NAME|BRAINSOS_ROUTE53_ZONE_ID|HOSTED_ZONE_ID|ACME_EMAIL)\s*=", ln)
    ]
    kept.append(f'BRAINSOS_DOMAIN="{fqdn}"')
    kept.append(f'BRAINSOS_ROUTE53_ZONE_ID="{zid}"')
    kept.append(f'ACME_EMAIL="{email}"')
    print("\n".join(kept))
else:
    # Cloud-config or KEY=VALUE UserData: append unambiguous top-level KEY=VALUE lines honoured by firstboot.sh
    kept = [
        ln for ln in base.splitlines()
        if not re.match(r"^\s*(?:BRAINSOS_DOMAIN|RECORD_NAME|domain|BRAINSOS_ROUTE53_ZONE_ID|HOSTED_ZONE_ID|route53_zone_id|ACME_EMAIL|email)\s*[=:]", ln)
    ]
    if not kept or not kept[0].startswith("#"):
        kept.insert(0, "#cloud-config")
    kept.append(f"BRAINSOS_DOMAIN={fqdn}")
    kept.append(f"BRAINSOS_ROUTE53_ZONE_ID={zid}")
    kept.append(f"ACME_EMAIL={email}")
    print("\n".join(kept))
PY
}

# ==============================================================================
# Core Day-2 Lifecycle Runner
# ==============================================================================
run_day2_action() {
  local action="$1"
  local target_fleet="${2:-}"
  local auto_yes="${3:-false}"

  if [ "${action}" = "list" ]; then
    local filters=("Name=instance-state-name,Values=pending,running,stopping,stopped")
    if [ -n "${target_fleet}" ]; then
      filters+=("Name=tag:BrainsOSFleet,Values=${target_fleet}")
    else
      filters+=("Name=tag-key,Values=BrainsOSFleet")
    fi
    aws ec2 describe-instances --region "${AWS_REGION}" --filters "${filters[@]}" \
      --query 'Reservations[].Instances[].{
        Fleet: (Tags[?Key==`BrainsOSFleet`]|[0].Value) || `-`,
        Participant: (Tags[?Key==`BrainsOSParticipant`]|[0].Value) || (Tags[?Key==`Name`]|[0].Value) || `-`,
        URL: join(``, [`https://`, (Tags[?Key==`BrainsOSDomain`]|[0].Value) || `-`]),
        InstanceId: InstanceId,
        State: State.Name,
        PublicIP: PublicIpAddress || `-`,
        Type: InstanceType
      }' --output table
    return 0
  fi

  if [ -z "${target_fleet}" ]; then
    log_error "--${action} requires --fleet <fleet-id>."
    return 1
  fi

  local state_filter="running"
  [ "${action}" = "start" ] && state_filter="stopped"
  [ "${action}" = "terminate" ] && state_filter="pending,running,stopping,stopped"

  local target_ids=()
  while IFS= read -r iid; do
    [[ "${iid}" =~ ^i- ]] && target_ids+=("${iid}")
  done < <(
    aws ec2 describe-instances --region "${AWS_REGION}" \
      --filters "Name=tag:BrainsOSFleet,Values=${target_fleet}" "Name=instance-state-name,Values=${state_filter}" \
      --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null | tr '\t' '\n' || true
  )

  if [ "${#target_ids[@]}" -eq 0 ]; then
    log_warn "No matching instances in state [${state_filter}] found for fleet '${target_fleet}' in ${AWS_REGION}."
    return 0
  fi

  log_info "Fleet '${target_fleet}' (${AWS_REGION}) matched ${#target_ids[@]} instance(s): ${target_ids[*]}"
  case "${action}" in
    stop)
      aws ec2 stop-instances --region "${AWS_REGION}" --instance-ids "${target_ids[@]}" >/dev/null
      log_success "Initiated stop for ${#target_ids[@]} instance(s) in fleet '${target_fleet}'."
      ;;
    hibernate)
      aws ec2 stop-instances --region "${AWS_REGION}" --hibernate --instance-ids "${target_ids[@]}" >/dev/null
      log_success "Initiated hibernation for ${#target_ids[@]} instance(s) in fleet '${target_fleet}'."
      ;;
    start)
      aws ec2 start-instances --region "${AWS_REGION}" --instance-ids "${target_ids[@]}" >/dev/null
      log_success "Initiated start for ${#target_ids[@]} instance(s) in fleet '${target_fleet}'. Route 53 A records self-update within ~60s of boot."
      ;;
    terminate)
      if [ "${auto_yes}" != "true" ]; then
        log_warn "[SAFETY GATE] Re-run with --terminate --fleet ${target_fleet} --yes to permanently terminate: ${target_ids[*]}"
        return 1
      fi
      aws ec2 terminate-instances --region "${AWS_REGION}" --instance-ids "${target_ids[@]}" >/dev/null
      log_success "Terminated ${#target_ids[@]} instance(s) in fleet '${target_fleet}'."
      ;;
  esac
}

# ==============================================================================
# Core Fleet Launch Execution (Supports Launch Template Mode & Direct AMI Mode)
# ==============================================================================
execute_fleet_launch() {
  local lt_json=""
  local lt_id=""
  local lt_name=""
  local lt_base_ud=""
  local lt_iam_profile=""
  local lt_image_id=""
  local lt_inst_type=""
  local lt_tags_json="{}"

  if [ -n "${LAUNCH_TEMPLATE}" ]; then
    lt_json="$(inspect_launch_template_json "${LAUNCH_TEMPLATE}" "${LT_VERSION}" || true)"
    if [ -z "${lt_json}" ]; then
      log_error "Could not find EC2 Launch Template '${LAUNCH_TEMPLATE}' (version ${LT_VERSION}) in ${AWS_REGION}."
      return 1
    fi
    lt_id="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["id"])')"
    lt_name="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["name"])')"
    lt_base_ud="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["user_data"])')"
    lt_iam_profile="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["iam_profile"])')"
    lt_image_id="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["image_id"])')"
    lt_inst_type="$(J="${lt_json}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["instance_type"])')"
    lt_tags_json="$(J="${lt_json}" python3 -c 'import json,os; print(json.dumps(json.loads(os.environ["J"])["instance_tags"]))')"
    log_info "Using Launch Template: ${lt_name} (${lt_id}, version ${LT_VERSION})"
  fi

  # 1. Resolve Zone ID
  if [ -z "${ZONE_ID}" ]; then
    ZONE_ID="$(discover_zone_id "${BASE_DOMAIN}" || true)"
  fi
  if [ -z "${ZONE_ID}" ]; then
    log_error "Could not auto-discover a public Route 53 Hosted Zone for '${BASE_DOMAIN}'. Pass --zone-id Z..."
    return 1
  fi
  log_info "Using Route 53 Hosted Zone: ${ZONE_ID} (*.${BASE_DOMAIN})"

  # 2. If Direct AMI mode (or Launch Template omitted ImageId), resolve AMI / SG / IAM
  local need_ami=false
  if [ -z "${lt_id}" ] || { [ -z "${lt_image_id}" ] && [ -z "${AMI_ID}" ]; }; then
    need_ami=true
  fi
  if [ "${need_ami}" = true ] && [ -z "${AMI_ID}" ]; then
    AMI_ID="$(discover_ami_id || true)"
    if [ -z "${AMI_ID}" ]; then
      log_error "No available brainsos-* ARM64 AMI found in ${AWS_REGION}. Specify --ami ami-... or configure ImageId in your Launch Template."
      return 1
    fi
  fi
  [ -n "${AMI_ID}" ] && log_info "Using AMI Override/Target: ${AMI_ID}"

  if [ -n "${lt_id}" ]; then
    ensure_iam_ddns_policy "${lt_iam_profile}" "${ZONE_ID}"
  else
    # Direct AMI mode: resolve IAM profile & Security Group
    if ! aws iam get-instance-profile --instance-profile-name "${IAM_PROFILE}" >/dev/null 2>&1; then
      local fb_prof
      fb_prof="$(aws iam list-instance-profiles \
        --query "InstanceProfiles[?contains(InstanceProfileName, 'Bedrock') || contains(InstanceProfileName, 'brainsos')].[InstanceProfileName] | [0][0]" \
        --output text 2>/dev/null || true)"
      if [ -n "${fb_prof}" ] && [ "${fb_prof}" != "None" ]; then
        IAM_PROFILE="${fb_prof}"
      else
        log_error "IAM Instance Profile '${IAM_PROFILE}' not found. Pass --profile-name <name> or use --launch-template."
        return 1
      fi
    fi
    log_info "Using IAM Instance Profile: ${IAM_PROFILE}"
    ensure_iam_ddns_policy "${IAM_PROFILE}" "${ZONE_ID}"

    local vpc_id=""
    if [ -n "${SUBNET_ID}" ]; then
      vpc_id="$(aws ec2 describe-subnets --region "${AWS_REGION}" --subnet-ids "${SUBNET_ID}" --query 'Subnets[0].VpcId' --output text)"
    else
      vpc_id="$(aws ec2 describe-vpcs --region "${AWS_REGION}" --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text 2>/dev/null || true)"
      if [ -z "${vpc_id}" ] || [ "${vpc_id}" = "None" ]; then
        vpc_id="$(aws ec2 describe-vpcs --region "${AWS_REGION}" --query 'Vpcs[0].VpcId' --output text)"
      fi
    fi

    if [ -z "${SECURITY_GROUP_ID}" ]; then
      SECURITY_GROUP_ID="$(aws ec2 describe-security-groups --region "${AWS_REGION}" \
        --filters "Name=vpc-id,Values=${vpc_id}" "Name=group-name,Values=brainsos-fleet-https-sg" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
      if [ -z "${SECURITY_GROUP_ID}" ] || [ "${SECURITY_GROUP_ID}" = "None" ]; then
        SECURITY_GROUP_ID="$(aws ec2 create-security-group --region "${AWS_REGION}" \
          --vpc-id "${vpc_id}" \
          --group-name "brainsos-fleet-https-sg" \
          --description "brainsOS Appliance Fleet HTTPS Ingress (ports 80/443 only)" \
          --query 'GroupId' --output text)"
        aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SECURITY_GROUP_ID}" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
        aws ec2 authorize-security-group-ingress --region "${AWS_REGION}" --group-id "${SECURITY_GROUP_ID}" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
      fi
    fi
    log_info "Using Security Group: ${SECURITY_GROUP_ID} (ports 80/443 open, port 22 closed)"
  fi

  # 3. Prepare output roster files
  local out_prefix="${ROSTER_OUT:-./${FLEET_ID}-roster}"
  mkdir -p "$(dirname "${out_prefix}")"
  local roster_md="${out_prefix}.md"
  local roster_csv="${out_prefix}.csv"

  printf "participant,url,instance_id,fqdn,fleet_id\n" > "${roster_csv}"
  {
    echo "### 🎉 brainsOS Participant Handoff Roster (\`${FLEET_ID}\`)"
    echo ""
    echo "| Participant | Permanent Appliance URL | First-Boot Instance ID Key |"
    echo "|---|---|---|"
  } > "${roster_md}"

  # 4. Launch each instance
  local entry slug name fqdn user_data tag_spec_json inst_id
  for entry in "${ROSTER_LINES[@]}"; do
    slug="${entry%%|*}"
    name="${entry#*|}"
    fqdn="${slug}.${BASE_DOMAIN}"
    user_data="$(compose_instance_userdata "${lt_base_ud}" "${fqdn}" "${ZONE_ID}" "${ACME_EMAIL}")"

    tag_spec_json="$(BASE_TAGS="${lt_tags_json}" SLUG="${slug}" FLEET="${FLEET_ID}" PNAME="${name}" FQDN="${fqdn}" python3 -c '
import json, os
tags = json.loads(os.environ.get("BASE_TAGS", "{}") or "{}")
tags.update({
    "Name": os.environ["SLUG"],
    "BrainsOSFleet": os.environ["FLEET"],
    "BrainsOSParticipant": os.environ["PNAME"],
    "BrainsOSDomain": os.environ["FQDN"],
})
print(json.dumps([{"ResourceType": "instance", "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}]))
')"

    local run_args=(--region "${AWS_REGION}")
    if [ -n "${lt_id}" ]; then
      run_args+=(--launch-template "LaunchTemplateId=${lt_id},Version=${LT_VERSION}")
      [ -n "${AMI_ID}" ] && run_args+=(--image-id "${AMI_ID}")
      if [ -n "${INSTANCE_TYPE}" ]; then
        run_args+=(--instance-type "${INSTANCE_TYPE}")
      elif [ -z "${lt_inst_type}" ]; then
        run_args+=(--instance-type "${INSTANCE_TYPE_DEFAULT}")
      fi
      [ -n "${SUBNET_ID}" ] && run_args+=(--subnet-id "${SUBNET_ID}")
    else
      local eff_type="${INSTANCE_TYPE:-${INSTANCE_TYPE_DEFAULT}}"
      local enc_flag="false"
      [ "${HIBERNATION_CAPABLE}" = true ] && enc_flag="true"
      run_args+=(
        --image-id "${AMI_ID}"
        --instance-type "${eff_type}"
        --security-group-ids "${SECURITY_GROUP_ID}"
        --iam-instance-profile "Name=${IAM_PROFILE}"
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=${VOLUME_SIZE},VolumeType=gp3,Throughput=${VOLUME_THROUGHPUT},Iops=${VOLUME_IOPS},DeleteOnTermination=true,Encrypted=${enc_flag}}"
      )
      [ -n "${SUBNET_ID}" ] && run_args+=(--subnet-id "${SUBNET_ID}" --associate-public-ip-address)
    fi

    if [ "${HIBERNATION_CAPABLE}" = true ]; then
      run_args+=(--hibernation-options "Configured=true")
    fi

    run_args+=(
      --user-data "${user_data}"
      --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled,InstanceMetadataTags=enabled"
      --tag-specifications "${tag_spec_json}"
      --query 'Instances[0].InstanceId'
      --output text
    )

    inst_id="$(aws ec2 run-instances "${run_args[@]}")"
    log_success "Launched ${name} -> https://${fqdn} (${inst_id})"
    echo "| ${name} | https://${fqdn} | \`${inst_id}\` |" >> "${roster_md}"
    printf '"%s","https://%s","%s","%s","%s"\n' "${name}" "${fqdn}" "${inst_id}" "${fqdn}" "${FLEET_ID}" >> "${roster_csv}"
  done

  echo ""
  cat "${roster_md}"
  echo ""
  log_success "Saved handoff files: ${roster_md} and ${roster_csv}"
  log_info "Allow ~60-90 seconds for Route 53 DNS + Let's Encrypt TLS initialization."
  log_info "Day-2 commands: ./$(basename "$0") --stop --fleet ${FLEET_ID}  |  ./$(basename "$0") --terminate --fleet ${FLEET_ID} --yes"
}

# ==============================================================================
# Interactive Wizard TUI Mode
# ==============================================================================
PROMPT_REPLY=""
prompt_read() {
  local prompt_text="$1"
  local default_val="${2:-}"
  local reply=""
  if [ -n "${default_val}" ]; then
    printf "%b%s%b [%b%s%b]: " "${BOLD}" "${prompt_text}" "${NC}" "${CYAN}" "${default_val}" "${NC}" >&2
  else
    printf "%b%s%b: " "${BOLD}" "${prompt_text}" "${NC}" >&2
  fi
  if ! IFS= read -r reply; then
    printf "\n%bExiting brainsOS Fleet Utility. Goodbye!%b\n" "${DIM}" "${NC}" >&2
    exit 0
  fi
  reply="$(printf '%s' "${reply}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  case "${reply}" in
    q|Q|quit|QUIT|exit|EXIT)
      printf "%bExiting brainsOS Fleet Utility. Goodbye!%b\n" "${DIM}" "${NC}" >&2
      exit 0
      ;;
  esac
  if [ -z "${reply}" ]; then
    PROMPT_REPLY="${default_val}"
  else
    PROMPT_REPLY="${reply}"
  fi
}

wizard_pick_fleet_and_run() {
  local action="$1"
  local fleets_raw
  fleets_raw="$(aws ec2 describe-instances --region "${AWS_REGION}" \
    --filters "Name=tag-key,Values=BrainsOSFleet" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --output json 2>/dev/null || true)"

  local fleet_rows=()
  while IFS= read -r row; do
    [ -n "${row}" ] && fleet_rows+=("${row}")
  done < <(
    RAW="${fleets_raw}" python3 - <<'PY'
import collections, json, os
data = json.loads(os.environ.get("RAW") or "{}")
counts = collections.defaultdict(lambda: collections.Counter())
for res in data.get("Reservations", []):
    for inst in res.get("Instances", []):
        fid = next((t["Value"] for t in inst.get("Tags", []) if t.get("Key") == "BrainsOSFleet"), "")
        if fid:
            counts[fid][inst.get("State", {}).get("Name", "unknown")] += 1
for fid in sorted(counts.keys()):
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts[fid].items()))
    print(f"{fid}|{summary}")
PY
  )

  if [ "${#fleet_rows[@]}" -eq 0 ]; then
    log_warn "No active fleets found in ${AWS_REGION}."
    return 0
  fi

  printf "\n%bActive brainsOS Fleets in %s:%b\n" "${BOLD}" "${AWS_REGION}" "${NC}" >&2
  local i=1
  for r in "${fleet_rows[@]}"; do
    printf "  [%d] %b%s%b  (%s)\n" "${i}" "${CYAN}" "${r%%|*}" "${NC}" "${r#*|}" >&2
    i=$((i + 1))
  done
  printf "  [0] Cancel / Back\n\n" >&2

  prompt_read "Select fleet number (or 'q' to exit)" "1"
  local sel="${PROMPT_REPLY}"
  if [ "${sel}" = "0" ]; then
    return 0
  fi
  if ! [[ "${sel}" =~ ^[0-9]+$ ]] || [ "${sel}" -lt 1 ] || [ "${sel}" -gt "${#fleet_rows[@]}" ]; then
    log_warn "Invalid selection: ${sel}"
    return 0
  fi

  local chosen_fleet="${fleet_rows[$((sel - 1))]%%|*}"
  prompt_read "Confirm '${action}' on fleet '${chosen_fleet}'? (y/N)" "n"
  local confirm="${PROMPT_REPLY}"
  case "${confirm}" in
    y|Y|yes|YES)
      run_day2_action "${action}" "${chosen_fleet}" "true"
      ;;
    *)
      log_info "Cancelled."
      ;;
  esac
}

wizard_launch_flow() {
  # Reset per-run launch state
  LAUNCH_TEMPLATE=""
  LT_VERSION="\$Latest"
  AMI_ID=""
  INSTANCE_TYPE=""
  INSTANCE_COUNT=""
  SLUG_PREFIX="user"
  PARTICIPANTS_RAW=""
  ZONE_ID=""
  ACME_EMAIL=""
  FLEET_ID=""

  # 1. Discover EC2 Launch Templates
  printf "\n%bStep 1 of 4 — Select EC2 Launch Template (%s)%b\n" "${BOLD}" "${AWS_REGION}" "${NC}" >&2
  local lt_list_json
  lt_list_json="$(aws ec2 describe-launch-templates --region "${AWS_REGION}" --output json 2>/dev/null || echo '{}')"

  local lt_rows=()
  while IFS= read -r row; do
    [ -n "${row}" ] && lt_rows+=("${row}")
  done < <(
    RAW="${lt_list_json}" python3 - <<'PY'
import json, os
lts = json.loads(os.environ.get("RAW") or "{}").get("LaunchTemplates", [])
lts.sort(key=lambda x: x.get("CreateTime", ""), reverse=True)
for lt in lts:
    print(f"{lt['LaunchTemplateId']}|{lt['LaunchTemplateName']}|v{lt.get('DefaultVersionNumber',1)}|v{lt.get('LatestVersionNumber',1)}")
PY
  )

  local default_lt_choice="0"
  if [ "${#lt_rows[@]}" -gt 0 ]; then
    default_lt_choice="1"
    local idx=1
    for r in "${lt_rows[@]}"; do
      IFS='|' read -r lid lname ldef llat <<< "${r}"
      printf "  [%d] %b%-28s%b (%s | Default: %s, Latest: %s)\n" "${idx}" "${CYAN}" "${lname}" "${NC}" "${lid}" "${ldef}" "${llat}" >&2
      idx=$((idx + 1))
    done
  else
    printf "  %b(No EC2 Launch Templates found in %s)%b\n" "${DIM}" "${AWS_REGION}" "${NC}" >&2
  fi
  printf "  [0] Direct AMI Mode (launch without a Launch Template)\n\n" >&2

  prompt_read "Pick a Launch Template (or 'q' to exit)" "${default_lt_choice}"
  local lt_sel="${PROMPT_REPLY}"

  local lt_ud_domain=""
  local lt_ud_zone=""
  local lt_ud_email=""

  if [ "${lt_sel}" != "0" ]; then
    if [[ "${lt_sel}" =~ ^lt-[0-9a-f]+$ ]]; then
      LAUNCH_TEMPLATE="${lt_sel}"
    elif [[ "${lt_sel}" =~ ^[0-9]+$ ]] && [ "${lt_sel}" -ge 1 ] && [ "${lt_sel}" -le "${#lt_rows[@]}" ]; then
      LAUNCH_TEMPLATE="${lt_rows[$((lt_sel - 1))]%%|*}"
    else
      LAUNCH_TEMPLATE="${lt_sel}"
    fi

    prompt_read "Launch Template version (\$Latest, \$Default, or number)" "\$Latest"
    LT_VERSION="${PROMPT_REPLY}"
    local lt_meta
    lt_meta="$(inspect_launch_template_json "${LAUNCH_TEMPLATE}" "${LT_VERSION}" || true)"
    if [ -z "${lt_meta}" ]; then
      log_error "Could not load Launch Template '${LAUNCH_TEMPLATE}' (${LT_VERSION})."
      return 1
    fi

    local m_name m_id m_rver m_ami m_type m_iam
    m_name="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["name"])')"
    m_id="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["id"])')"
    m_rver="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["resolved_version"])')"
    m_ami="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["image_id"])')"
    m_type="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["instance_type"])')"
    m_iam="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["iam_profile"])')"
    lt_ud_domain="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["ud_base_domain"])')"
    lt_ud_zone="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["ud_zone_id"])')"
    lt_ud_email="$(J="${lt_meta}" python3 -c 'import json,os; print(json.loads(os.environ["J"])["ud_email"])')"

    printf "\n  %b✔ Selected:%b %s (%s, v%s)\n" "${GREEN}" "${NC}" "${m_name}" "${m_id}" "${m_rver}" >&2
    printf "    • AMI ID        : %s\n" "${m_ami:-<will auto-discover brainsos-* ARM64>}" >&2
    printf "    • Instance Type : %s\n" "${m_type:-${INSTANCE_TYPE_DEFAULT}}" >&2
    printf "    • IAM Profile   : %s\n" "${m_iam:-<configured in template / none>}" >&2
  else
    local disc_ami
    disc_ami="$(discover_ami_id || true)"
    prompt_read "brainsOS ARM64 AMI ID" "${disc_ami}"
    AMI_ID="${PROMPT_REPLY}"
    prompt_read "Graviton Instance Type" "${INSTANCE_TYPE_DEFAULT}"
    INSTANCE_TYPE="${PROMPT_REPLY}"
    prompt_read "IAM Instance Profile" "${IAM_PROFILE}"
    IAM_PROFILE="${PROMPT_REPLY}"
  fi

  # 2. Route 53 Hosted Zone & Base Subdomain
  printf "\n%bStep 2 of 4 — Route 53 Domain Configuration%b\n" "${BOLD}" "${NC}" >&2
  local zones_json
  zones_json="$(aws route53 list-hosted-zones --output json 2>/dev/null || echo '{}')"
  local zone_rows=()
  while IFS= read -r zrow; do
    [ -n "${zrow}" ] && zone_rows+=("${zrow}")
  done < <(
    RAW="${zones_json}" python3 - <<'PY'
import json, os
for z in json.loads(os.environ.get("RAW") or "{}").get("HostedZones", []):
    if not z.get("Config", {}).get("PrivateZone", False):
        zid = z["Id"].split("/")[-1]
        zname = z["Name"].rstrip(".")
        print(f"{zname}|{zid}")
PY
  )

  local suggested_domain="${lt_ud_domain}"
  if [ "${#zone_rows[@]}" -gt 0 ]; then
    printf "  Detected Public Route 53 Hosted Zones:\n" >&2
    for zr in "${zone_rows[@]}"; do
      printf "    • %b%s%b (%s)\n" "${CYAN}" "${zr%%|*}" "${NC}" "${zr#*|}" >&2
    done
    if [ -z "${suggested_domain}" ]; then
      suggested_domain="demo.${zone_rows[0]%%|*}"
    fi
  fi
  echo "" >&2

  prompt_read "Base subdomain for instance URLs (e.g. demo.infotechlabs.io)" "${suggested_domain}"
  BASE_DOMAIN="$(clean_domain "${PROMPT_REPLY}")"
  if ! validate_domain "${BASE_DOMAIN}"; then
    log_error "Invalid domain: '${BASE_DOMAIN}'"
    return 1
  fi

  ZONE_ID="${lt_ud_zone}"
  [ -z "${ZONE_ID}" ] && ZONE_ID="$(discover_zone_id "${BASE_DOMAIN}" || true)"
  if [ -z "${ZONE_ID}" ]; then
    prompt_read "Route 53 Hosted Zone ID (Z...)" ""
    ZONE_ID="${PROMPT_REPLY#*hostedzone/}"
  fi
  ACME_EMAIL="${lt_ud_email:-$(default_email_for_domain "${BASE_DOMAIN}")}"

  # 3. Sizing: Count OR Participant Names
  printf "\n%bStep 3 of 4 — How Many Instances (or Participant Names)?%b\n" "${BOLD}" "${NC}" >&2
  printf "  • Type a %bNUMBER%b (e.g. %b5%b or %b20%b) to launch numbered boxes (user01.%s, ...)\n" "${CYAN}" "${NC}" "${BOLD}" "${NC}" "${BOLD}" "${NC}" "${BASE_DOMAIN}" >&2
  printf "  • Or enter %bNAMES%b (e.g. %bAlice Morgan, Bob Patel%b) for personalized URLs\n" "${CYAN}" "${NC}" "${BOLD}" "${NC}" >&2
  printf "  • Or type %bpaste%b to paste a multi-line attendee list\n\n" "${CYAN}" "${NC}" >&2

  prompt_read "Count or Participant Names" "1"
  local sizing_in="${PROMPT_REPLY}"
  if [[ "${sizing_in}" =~ ^[0-9]+$ ]]; then
    INSTANCE_COUNT="${sizing_in}"
    prompt_read "Hostname prefix (creates <prefix>01.${BASE_DOMAIN})" "user"
    SLUG_PREFIX="${PROMPT_REPLY}"
  elif [ "${sizing_in}" = "paste" ]; then
    printf "Paste participant names (one per line; press ENTER on an empty line when done):\n" >&2
    local pline=""
    while IFS= read -r pline; do
      [ -z "${pline}" ] && break
      PARTICIPANTS_RAW="${PARTICIPANTS_RAW:+${PARTICIPANTS_RAW}$'\n'}${pline}"
    done
  else
    PARTICIPANTS_RAW="${sizing_in}"
  fi

  build_roster_lines || return 1

  # 4. Fleet Tag & Final Confirmation Table
  printf "\n%bStep 4 of 4 — Review & Launch%b\n" "${BOLD}" "${NC}" >&2
  local def_fleet="demo-$(date +%Y%m%d-%H%M)"
  prompt_read "Fleet tag ID (for 1-click stop/terminate)" "${def_fleet}"
  FLEET_ID="${PROMPT_REPLY}"

  printf "\n  %bLaunch Summary:%b\n" "${BOLD}" "${NC}" >&2
  printf "    • AWS Account / Region : %s / %s\n" "${AWS_ACCOUNT_ID}" "${AWS_REGION}" >&2
  if [ -n "${LAUNCH_TEMPLATE}" ]; then
    printf "    • Launch Template      : %s (%s)\n" "${LAUNCH_TEMPLATE}" "${LT_VERSION}" >&2
  else
    printf "    • Direct AMI / Type    : %s / %s\n" "${AMI_ID}" "${INSTANCE_TYPE:-${INSTANCE_TYPE_DEFAULT}}" >&2
  fi
  printf "    • Route 53 Zone        : %s (*.%s)\n" "${ZONE_ID}" "${BASE_DOMAIN}" >&2
  printf "    • Fleet Tag            : %s (%d instance(s))\n\n" "${FLEET_ID}" "${#ROSTER_LINES[@]}" >&2

  printf "    %-4s %-24s %s\n" "#" "Label / Participant" "Permanent URL" >&2
  printf "    %-4s %-24s %s\n" "---" "------------------------" "----------------------------------------" >&2
  local n=1
  for entry in "${ROSTER_LINES[@]}"; do
    printf "    %-4d %-24s https://%s.%s\n" "${n}" "${entry#*|}" "${entry%%|*}" "${BASE_DOMAIN}" >&2
    n=$((n + 1))
  done
  echo "" >&2

  prompt_read "Launch ${#ROSTER_LINES[@]} appliance instance(s) now? (y/N)" "n"
  local go="${PROMPT_REPLY}"
  case "${go}" in
    y|Y|yes|YES)
      echo "" >&2
      execute_fleet_launch
      ;;
    *)
      log_info "Launch cancelled. Returning to menu."
      ;;
  esac
}

run_interactive_wizard() {
  require_aws
  while true; do
    printf "\n%b╔══════════════════════════════════════════════════════════════════════╗%b\n" "${CYAN}" "${NC}" >&2
    printf "%b║         brainsOS Fleet Launcher & Lifecycle Utility (v%-6s)        ║%b\n" "${CYAN}" "${VERSION}" "${NC}" >&2
    printf "%b╚══════════════════════════════════════════════════════════════════════╝%b\n" "${CYAN}" "${NC}" >&2
    printf "  AWS Account : %b%s%b (%s)\n" "${BOLD}" "${AWS_ACCOUNT_ID}" "${NC}" "${AWS_CALLER_ARN}" >&2
    printf "  AWS Region  : %b%s%b (Profile: %s)\n\n" "${BOLD}" "${AWS_REGION}" "${NC}" "${AWS_PROFILE:-default}" >&2

    printf "  [1] 🚀 Launch New Appliance Fleet (Pick Launch Template or Direct AMI)\n" >&2
    printf "  [2] 📋 List Active Fleets & Instances\n" >&2
    printf "  [3] ⏸️  Stop a Fleet (save compute; preserves EBS & Route 53 URLs)\n" >&2
    printf "  [4] 💤 Hibernate a Fleet (freeze RAM to disk)\n" >&2
    printf "  [5] ▶️  Start / Resume a Fleet (auto-updates DNS IPs on boot)\n" >&2
    printf "  [6] 🗑️  Terminate a Fleet (clean teardown)\n" >&2
    printf "  [7] 🌎 Switch AWS Region / Profile\n" >&2
    printf "  [q] 🚪 Exit\n\n" >&2

    prompt_read "Select an option" "1"
    local choice="${PROMPT_REPLY}"
    case "${choice}" in
      1) wizard_launch_flow || true ;;
      2) echo "" >&2; run_day2_action "list" "" "false" || true ;;
      3) wizard_pick_fleet_and_run "stop" || true ;;
      4) wizard_pick_fleet_and_run "hibernate" || true ;;
      5) wizard_pick_fleet_and_run "start" || true ;;
      6) wizard_pick_fleet_and_run "terminate" || true ;;
      7)
        prompt_read "AWS Region" "${AWS_REGION}"
        AWS_REGION="${PROMPT_REPLY}"
        prompt_read "AWS Profile (leave as '${AWS_PROFILE:-default}' to keep)" "${AWS_PROFILE:-}"
        local new_prof="${PROMPT_REPLY}"
        if [ -n "${new_prof}" ] && [ "${new_prof}" != "default" ]; then
          export AWS_PROFILE="${new_prof}"
        fi
        require_aws
        ;;
      0)
        printf "%bExiting brainsOS Fleet Utility. Goodbye!%b\n" "${DIM}" "${NC}" >&2
        exit 0
        ;;
      *)
        log_warn "Unrecognized choice: '${choice}' (enter 1-7 or 'q' to exit)."
        ;;
    esac

    echo "" >&2
    prompt_read "Press ENTER for main menu, or 'q' to exit" ""
  done
}

# ==============================================================================
# Dispatch Execution Mode
# ==============================================================================
if [ "${MODE}" = "wizard" ]; then
  run_interactive_wizard
  exit 0
fi

case "${MODE}" in
  list|stop|hibernate|start|terminate)
    require_aws
    run_day2_action "${MODE}" "${FLEET_ID}" "${CONFIRM_YES}"
    exit $?
    ;;
esac

# Non-interactive Launch / Dry-Run / Emit-Script Modes
require_prereqs

if [ -n "${PARTICIPANTS_FILE}" ]; then
  if [ ! -f "${PARTICIPANTS_FILE}" ]; then
    log_error "Participants file not found: ${PARTICIPANTS_FILE}"
    exit 1
  fi
  PARTICIPANTS_RAW="${PARTICIPANTS_RAW:+${PARTICIPANTS_RAW}$'\n'}$(cat "${PARTICIPANTS_FILE}")"
fi

if [ -z "${BASE_DOMAIN}" ]; then
  log_error "--base-domain <domain> is required (or run './$(basename "$0")' with no arguments for the interactive wizard)."
  exit 1
fi

BASE_DOMAIN="$(clean_domain "${BASE_DOMAIN}")"
if ! validate_domain "${BASE_DOMAIN}"; then
  log_error "Invalid --base-domain: ${BASE_DOMAIN}"
  exit 1
fi

[ -z "${ACME_EMAIL}" ] && ACME_EMAIL="$(default_email_for_domain "${BASE_DOMAIN}")"
[ -z "${FLEET_ID}" ] && FLEET_ID="demo-$(date +%Y%m%d-%H%M)"
ZONE_ID="${ZONE_ID#*hostedzone/}"

build_roster_lines || exit 1
log_info "Prepared ${#ROSTER_LINES[@]} instance(s) for fleet '${FLEET_ID}' under *.${BASE_DOMAIN}."

if [ "${MODE}" = "dry-run" ]; then
  if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity --region "${AWS_REGION}" >/dev/null 2>&1; then
    [ -z "${ZONE_ID}" ] && ZONE_ID="$(discover_zone_id "${BASE_DOMAIN}" || true)"
    [ -z "${LAUNCH_TEMPLATE}" ] && [ -z "${AMI_ID}" ] && AMI_ID="$(discover_ami_id || true)"
  fi

  echo ""
  echo "### 🚀 brainsOS Fleet Launch Preview (DRY-RUN)"
  echo ""
  echo "- **Fleet Tag (\`BrainsOSFleet\`)**: \`${FLEET_ID}\`"
  if [ -n "${LAUNCH_TEMPLATE}" ]; then
    echo "- **Launch Template**: \`${LAUNCH_TEMPLATE}\` (\`${LT_VERSION}\`) in \`${AWS_REGION}\`"
  else
    echo "- **Region / Instance Type**: \`${AWS_REGION}\` / \`${INSTANCE_TYPE:-${INSTANCE_TYPE_DEFAULT}}\` (\`${VOLUME_SIZE} GB gp3\`)"
    echo "- **AMI ID**: \`${AMI_ID:-<auto-discover newest self/shared brainsos-* ARM64 AMI>}\`"
    echo "- **IAM Instance Profile**: \`${IAM_PROFILE}\`"
  fi
  echo "- **Route 53 Zone ID**: \`${ZONE_ID:-<auto-discover from ${BASE_DOMAIN}>}\`"
  echo "- **Hibernation Capable**: \`${HIBERNATION_CAPABLE}\`"
  echo ""
  echo "| # | Participant / Label | EC2 Name Tag | Permanent Appliance URL | Onboarding Flow |"
  echo "|---|---|---|---|---|"
  idx=1
  for entry in "${ROSTER_LINES[@]}"; do
    slug="${entry%%|*}"
    name="${entry#*|}"
    echo "| ${idx} | ${name} | \`${slug}\` | https://${slug}.${BASE_DOMAIN} | 2-Step Operator Account + SSL Auto |"
    idx=$((idx + 1))
  done
  echo ""
  log_info "Dry-run complete. Pass --apply to launch directly, --emit-script <file.sh>, or run with no args for the interactive wizard."
  exit 0
fi

if [ "${MODE}" = "emit-script" ]; then
  # Embed this standalone script itself + pre-baked arguments for 1-click execution anywhere!
  SELF_B64="$(base64 < "${BASH_SOURCE[0]}" | tr -d '\n')"
  render_self_contained_bundle() {
    cat <<EOF
#!/usr/bin/env bash
# ==============================================================================
# brainsOS Pre-Configured Standalone Fleet Bundle
# Fleet ID: ${FLEET_ID} | Domain: *.${BASE_DOMAIN} | Count: ${#ROSTER_LINES[@]}
# ==============================================================================
set -euo pipefail
TMP_UTIL="\$(mktemp "\${TMPDIR:-/tmp}/brainsos-fleet-util.XXXXXX.sh")"
trap 'rm -f "\${TMP_UTIL}"' EXIT
printf '%s' '${SELF_B64}' | (base64 -d 2>/dev/null || base64 -D) > "\${TMP_UTIL}"
chmod +x "\${TMP_UTIL}"

PARTICIPANTS_PAYLOAD=\$(cat <<'ROSTER_EOF'
EOF
    for entry in "${ROSTER_LINES[@]}"; do
      printf '%s=%s\n' "${entry%%|*}" "${entry#*|}"
    done
    cat <<EOF
ROSTER_EOF
)

exec bash "\${TMP_UTIL}" \\
  --participants "\${PARTICIPANTS_PAYLOAD}" \\
  --base-domain $(printf '%q' "${BASE_DOMAIN}") \\
  ${ZONE_ID:+--zone-id $(printf '%q' "${ZONE_ID}")} \\
  --email $(printf '%q' "${ACME_EMAIL}") \\
  --fleet $(printf '%q' "${FLEET_ID}") \\
  ${LAUNCH_TEMPLATE:+--launch-template $(printf '%q' "${LAUNCH_TEMPLATE}") --lt-version $(printf '%q' "${LT_VERSION}")} \\
  ${AMI_ID:+--ami $(printf '%q' "${AMI_ID}")} \\
  --region "\${AWS_REGION:-${AWS_REGION}}" \\
  ${INSTANCE_TYPE:+--instance-type $(printf '%q' "${INSTANCE_TYPE}")} \\
  --volume-size "${VOLUME_SIZE}" \\
  --profile-name $(printf '%q' "${IAM_PROFILE}") \\
  ${SECURITY_GROUP_ID:+--security-group $(printf '%q' "${SECURITY_GROUP_ID}")} \\
  ${SUBNET_ID:+--subnet-id $(printf '%q' "${SUBNET_ID}")} \\
  $([ "${HIBERNATION_CAPABLE}" = true ] && echo "--hibernation-capable") \\
  $([ "${ENSURE_IAM_DDNS}" = false ] && echo "--no-ensure-iam-ddns") \\
  --apply "\$@"
EOF
  }

  if [ "${EMIT_SCRIPT}" = "-" ]; then
    render_self_contained_bundle
  else
    mkdir -p "$(dirname "${EMIT_SCRIPT}")"
    render_self_contained_bundle > "${EMIT_SCRIPT}"
    chmod +x "${EMIT_SCRIPT}"
    log_success "Wrote self-contained fleet launch bundle to: ${EMIT_SCRIPT}"
    log_info "Run on any machine with AWS CLI configured: ./${EMIT_SCRIPT}"
  fi
  exit 0
fi

if [ "${MODE}" = "apply" ]; then
  require_aws
  execute_fleet_launch
  exit 0
fi
