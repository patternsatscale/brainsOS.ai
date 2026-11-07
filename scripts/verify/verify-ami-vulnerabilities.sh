#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Golden AMI Vulnerability Audit Gate
# Ticket #338 (Epic #309 / #321)
#
# Queries AWS EC2 / Amazon Inspector image findings (ec2:GetImageFindings) for a
# candidate Golden AMI (or inspects a local findings JSON payload) and asserts
# zero Critical/High vulnerabilities with a fix available (FixAvailable: true).
#
# Usage:
#   ./scripts/verify/verify-ami-vulnerabilities.sh --ami <ami-id> [OPTIONS]
#
# Options:
#   --ami AMI_ID            Target AMI ID to inspect (Required unless --findings-file)
#   --region REGION         AWS Region (Default: us-east-1 or $AWS_REGION)
#   --findings-file FILE    Read GetImageFindings JSON payload from local file (offline/test)
#   --zero-fixable          Fail if ANY finding (including Medium/Low) has FixAvailable=true
#   --json                  Emit structured JSON summary to stdout
#   --dry-run               Validate CLI options without calling AWS APIs
#   -h, --help              Show this help message
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

AMI_ID=""
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
FINDINGS_FILE=""
ZERO_FIXABLE=false
JSON_OUTPUT=false
DRY_RUN=false

usage() {
  cat <<EOF
brainsOS Automated Golden AMI Vulnerability Audit Gate (Ticket #338)

Usage:
  ./scripts/verify/verify-ami-vulnerabilities.sh --ami <ami-id> [OPTIONS]

Options:
  --ami AMI_ID            Target AMI ID to inspect (e.g. ami-0123456789abcdef0)
  --region REGION         AWS Region (Default: ${AWS_REGION})
  --findings-file FILE    Inspect a local ec2:GetImageFindings JSON file (offline/CI)
  --zero-fixable          Require 0 FixAvailable=true findings across all severities
  --json                  Output structured JSON report
  --dry-run               Validate arguments without querying AWS EC2
  -h, --help              Show this help message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ami)           AMI_ID="${2:-}"; shift 2 ;;
    --region)        AWS_REGION="${2:-}"; shift 2 ;;
    --findings-file) FINDINGS_FILE="${2:-}"; shift 2 ;;
    --zero-fixable)  ZERO_FIXABLE=true; shift ;;
    --json)          JSON_OUTPUT=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    -h|--help)       usage; exit 0 ;;
    *)               log_error "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [ -z "${FINDINGS_FILE}" ]; then
  if [[ ! "${AMI_ID}" =~ ^ami-[0-9a-f]{8,17}$ ]]; then
    log_error "A valid --ami <ami-id> or --findings-file <path> is required."
    usage
    exit 1
  fi
fi

if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Would query ec2:GetImageFindings for ${AMI_ID:-${FINDINGS_FILE}} in ${AWS_REGION}"
  log_info "[DRY-RUN] Would assert 0 Critical/High FixAvailable=true findings (zero-fixable=${ZERO_FIXABLE})"
  log_success "[DRY-RUN] AMI vulnerability audit dry-run passed."
  exit 0
fi

TMP_JSON=""
cleanup() {
  if [ -n "${TMP_JSON}" ] && [ -f "${TMP_JSON}" ]; then
    rm -f "${TMP_JSON}"
  fi
}
trap cleanup EXIT

if [ -n "${FINDINGS_FILE}" ]; then
  if [ ! -f "${FINDINGS_FILE}" ]; then
    log_error "Findings file not found: ${FINDINGS_FILE}"
    exit 1
  fi
  TARGET_JSON="${FINDINGS_FILE}"
else
  if ! command -v aws >/dev/null 2>&1; then
    log_error "AWS CLI v2 is required to query ec2:GetImageFindings."
    exit 1
  fi
  TMP_JSON="$(mktemp "${TMPDIR:-/tmp}/brainsos-ami-findings.XXXXXX.json")"
  log_info "Querying ec2:GetImageFindings for ${AMI_ID} in ${AWS_REGION}..."
  if ! aws ec2 get-image-findings --region "${AWS_REGION}" --image-id "${AMI_ID}" --output json > "${TMP_JSON}" 2>/dev/null; then
    if ! python3 - "${AMI_ID}" "${AWS_REGION}" "${TMP_JSON}" <<'PY_FETCH'
import json, sys, urllib.parse, urllib.request, xml.etree.ElementTree as ET
import boto3, botocore.auth, botocore.awsrequest

ami_id, region, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
session = boto3.Session(region_name=region)
creds = session.get_credentials()
if creds is None:
    sys.exit(1)
frozen = creds.get_frozen_credentials()
ns = {"ec2": "http://ec2.amazonaws.com/doc/2016-11-15/"}
next_token = None
findings = []

while True:
    params = {"Action": "GetImageFindings", "Version": "2016-11-15", "ImageId": ami_id}
    if next_token:
        params["NextToken"] = next_token
    url = f"https://ec2.{region}.amazonaws.com/?" + urllib.parse.urlencode(params)
    req = botocore.awsrequest.AWSRequest(method="GET", url=url)
    botocore.auth.SigV4Auth(frozen, "ec2", region).add_auth(req)
    prep = req.prepare()
    with urllib.request.urlopen(urllib.request.Request(prep.url, headers=dict(prep.headers))) as resp:
        root = ET.fromstring(resp.read())
    for item in root.findall(".//ec2:imageFindingSet/ec2:item", ns):
        sev = (item.findtext("ec2:severityLabel", "", ns) or "UNSPECIFIED").upper()
        fix = (item.findtext("ec2:fixAvailable", "", ns) or "").lower() == "true"
        title = item.findtext("ec2:title", "", ns) or "unknown"
        paths = [p.text for p in item.findall(".//ec2:pathSet/ec2:item", ns) if p.text]
        findings.append({
            "Severity": sev,
            "FixAvailable": fix,
            "Title": title,
            "PackageName": paths[0] if paths else "unknown",
        })
    next_token = root.findtext("ec2:nextToken", None, ns)
    if not next_token:
        break

with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"Findings": findings}, f)
PY_FETCH
    then
      log_error "Failed to query ec2:GetImageFindings for ${AMI_ID} in ${AWS_REGION}."
      exit 1
    fi
  fi
  TARGET_JSON="${TMP_JSON}"
fi

python3 - "${TARGET_JSON}" "${AMI_ID:-local-file}" "${ZERO_FIXABLE}" "${JSON_OUTPUT}" <<'PY'
import json
import sys
from collections import Counter

findings_path = sys.argv[1]
ami_id = sys.argv[2]
zero_fixable = sys.argv[3].lower() == "true"
json_output = sys.argv[4].lower() == "true"

with open(findings_path, "r", encoding="utf-8") as f:
    payload = json.load(f)

findings = payload.get("Findings") or payload.get("findings") or []

total_by_sev = Counter()
fixable_by_sev = Counter()
blocking_samples = []

for item in findings:
    sev = str(item.get("Severity") or item.get("severity") or "UNSPECIFIED").upper()
    fix_raw = item.get("FixAvailable", item.get("fixAvailable", False))
    if isinstance(fix_raw, str):
        fix_avail = fix_raw.strip().upper() in ("TRUE", "YES", "1")
    else:
        fix_avail = bool(fix_raw)

    total_by_sev[sev] += 1
    if fix_avail:
        fixable_by_sev[sev] += 1
        if zero_fixable or sev in ("CRITICAL", "HIGH"):
            vuln_id = (
                item.get("VulnerabilityId")
                or item.get("Title")
                or item.get("FindingArn")
                or "unknown"
            )
            pkg = (
                item.get("PackageName")
                or (item.get("PackageVulnerabilityDetails", {}).get("VulnerablePackages") or [{}])[0].get("Name")
                or "unknown"
            )
            blocking_samples.append(
                {"severity": sev, "vulnerability_id": vuln_id, "package": pkg}
            )

fixable_critical = fixable_by_sev.get("CRITICAL", 0)
fixable_high = fixable_by_sev.get("HIGH", 0)
fixable_total = sum(fixable_by_sev.values())
total_count = sum(total_by_sev.values())

passed = (fixable_total == 0) if zero_fixable else (fixable_critical == 0 and fixable_high == 0)

report = {
    "ami_id": ami_id,
    "scan_status": payload.get("Status") or "ACTIVE",
    "total_findings": total_count,
    "fixable_total": fixable_total,
    "fixable_critical": fixable_critical,
    "fixable_high": fixable_high,
    "total_by_severity": dict(total_by_sev),
    "fixable_by_severity": dict(fixable_by_sev),
    "zero_fixable_enforced": zero_fixable,
    "passed": passed,
    "blocking_samples": blocking_samples[:20],
}

if json_output:
    print(json.dumps(report, indent=2))
else:
    print(f"AMI Vulnerability Scan Summary ({ami_id}):")
    print(f"  Total Findings:        {total_count}")
    print(f"  Fixable Findings:      {fixable_total} (Critical: {fixable_critical}, High: {fixable_high})")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL", "UNSPECIFIED"):
        if total_by_sev[sev] or fixable_by_sev[sev]:
            print(f"    - {sev:<14} total={total_by_sev[sev]:<5} fixable={fixable_by_sev[sev]}")
    if blocking_samples:
        print("  Blocking Fixable Findings (up to 20):")
        for sample in blocking_samples[:20]:
            print(f"    * [{sample['severity']}] {sample['vulnerability_id']} ({sample['package']})")

if not passed:
    sys.exit(1)
sys.exit(0)
PY
STATUS=$?

if [ "${STATUS}" -ne 0 ]; then
  log_error "AMI vulnerability gate FAILED for ${AMI_ID:-${FINDINGS_FILE}}."
  exit 1
fi

if [ "${JSON_OUTPUT}" != true ]; then
  log_success "AMI vulnerability gate PASSED: 0 blocking FixAvailable=true findings."
fi
