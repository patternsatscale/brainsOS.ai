#!/usr/bin/env bash
# ==============================================================================
# brainsOS: In-Transit Egress Credential Injection Verification Suite
# Validates M2/M3 zero-trust egress architecture (#387, #399, #400):
#   1. Fleet & runner manifests + Docker Compose topology validation
#   2. EphemeralDockerRunnerClient & OpenBaoEgressAddon security contracts
#      (Proxy-Authorization, GITHUB_ALLOWED_REPOS, SNI/peer SSRF, Tavily scrub)
#   3. Offline unit & security test verification (pytest)
#   4. Rule 1 memory plane purity check (zero non-OKF runtime artifacts)
#   5. Optional live container checks (--live, or auto when proxy is running
#      and --dry-run is not set) without destructive `docker compose up -d`
#
# Usage:
#   ./scripts/verify/verify-egress-token-injection.sh [--dry-run] [--live]
# ==============================================================================

set -euo pipefail

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

DRY_RUN=false
LIVE_MODE="auto"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      LIVE_MODE="off"
      shift
      ;;
    --live)
      LIVE_MODE="required"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [--live]"
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -f "${_check_dir}/config/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

# Load environment without mutating .env
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
elif [ -f .env.example ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.example
  set +a
fi

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
[ ! -x "${PYTHON_BIN}" ] && PYTHON_BIN="$(command -v python3 || echo python3)"
PYTEST_BIN="${REPO_ROOT}/.venv/bin/pytest"

log_info "================================================================="
log_info "  Running M3 Egress Credential Injection & Proxy Verification    "
log_info "================================================================="

# ------------------------------------------------------------------------------
# Step 1: Manifest & Docker Compose Topology Verification
# ------------------------------------------------------------------------------
log_info "Step 1: Validating fleet/runner manifests & Docker Compose topology..."

if [ ! -f "${REPO_ROOT}/config/default_settings/agents.yaml" ] && [ ! -f "${REPO_ROOT}/config/agents.yaml" ]; then
  log_error "Fleet agents manifest is missing."
  exit 1
fi
if [ ! -f "${REPO_ROOT}/config/default_settings/runners.yaml" ]; then
  log_error "Runners manifest (config/default_settings/runners.yaml) is missing."
  exit 1
fi
log_success "Fleet & runner manifests verified."

docker compose config -q
docker compose -f docker-compose.yml -f docker/compose/compose.appliance.yml config -q
log_success "Docker Compose base & appliance topologies validated."

"${PYTHON_BIN}" - << 'EOF'
from pathlib import Path
import yaml

compose_agents = yaml.safe_load(Path("docker/compose/compose.agents.yml").read_text(encoding="utf-8"))
services = compose_agents.get("services", {})

for svc_name, svc in services.items():
    nets = svc.get("networks") or {}
    net_names = list(nets.keys()) if isinstance(nets, dict) else list(nets)
    if "brainsos-ingress-net" in net_names:
        raise SystemExit(f"Service '{svc_name}' must NOT attach to brainsos-ingress-net")

proxy = services.get("tool-egress-proxy")
if not proxy:
    raise SystemExit("Missing tool-egress-proxy service in compose.agents.yml")

proxy_nets = proxy.get("networks") or {}
for required_net in ("brainsos-internal-net", "brainsos-secrets-net"):
    if required_net not in proxy_nets:
        raise SystemExit(f"tool-egress-proxy missing network '{required_net}'")

proxy_env = [str(x) for x in (proxy.get("environment") or [])]
for required_proxy_env in ("TOOL_EGRESS_PROXY_TOKENS=", "TOOL_EGRESS_PROXY_SECRET=", "GITHUB_ALLOWED_REPOS=", "OPENBAO_CACERT="):
    if not any(item.startswith(required_proxy_env) for item in proxy_env):
        raise SystemExit(f"tool-egress-proxy missing '{required_proxy_env}' env wiring")

for runner_name in ("runner-hermes", "runner-openai", "runner-claude"):
    rsvc = services.get(runner_name)
    if not rsvc:
        raise SystemExit(f"Missing runner service '{runner_name}' in compose.agents.yml")
    env_items = [str(x) for x in (rsvc.get("environment") or [])]
    for forbidden in ("GH_TOKEN=", "GITHUB_TOKEN=", "GITHUB_PAT=", "LANGFUSE_SECRET_KEY="):
        for item in env_items:
            if item.startswith(forbidden):
                raise SystemExit(f"Forbidden ambient secret '{item}' found in {runner_name}")
    if "HTTPS_PROXY=http://brainsos-net-egress-proxy:8082" not in env_items:
        raise SystemExit(f"Missing HTTPS_PROXY=http://brainsos-net-egress-proxy:8082 in {runner_name}")
    if runner_name == "runner-hermes" and not any("in-transit-openbao-managed" in item for item in env_items):
        raise SystemExit("Missing in-transit-openbao-managed placeholder env in runner-hermes")

print("[OK] compose.agents.yml satisfies ingress detachment, proxy networks, and zero ambient secrets.")
EOF

# ------------------------------------------------------------------------------
# Step 2: EphemeralDockerRunnerClient & OpenBaoEgressAddon Contracts
# ------------------------------------------------------------------------------
log_info "Step 2: Validating EphemeralDockerRunnerClient & OpenBaoEgressAddon contracts..."

"${PYTHON_BIN}" - << 'EOF'
from pathlib import Path

docker_client_src = Path("packages/brainsOS-runner/brainsos_runner/clients/docker.py").read_text(encoding="utf-8")
for required in (
    "class EphemeralDockerRunnerClient",
    "--cap-drop=ALL",
    '"--security-opt"',
    '"no-new-privileges:true"',
    "--pids-limit=256",
    "--user=10001:10001",
    "--read-only",
    "brainsos.tenant=",
    "_mint_proxy_token",
    "_extract_tenant_proxy_token",
    "GITHUB_ALLOWED_REPOS",
    "LANGFUSE_SECRET_KEY",
    "LITELLM_MASTER_KEY",
):
    if required not in docker_client_src:
        raise SystemExit(f"Missing M3 runner security contract '{required}' in docker.py")

addon_src = Path("config/egress/addons/github_auth.py").read_text(encoding="utf-8")
for required in (
    "class OpenBaoEgressAddon",
    'REDACTED_MARKER = "[INJECTED_OPENBAO_SECRET]"',
    "Proxy-Authorization",
    "_authenticate_proxy_flow",
    "_check_github_allowed_repos",
    "_verify_tls_and_sni",
    "def http_connect(",
    "def server_connect(",
    "api.tavily.com",
    "Authorization",
):
    if required not in addon_src:
        raise SystemExit(f"Missing egress proxy contract '{required}' in github_auth.py")

print("[OK] EphemeralDockerRunnerClient & OpenBaoEgressAddon contracts verified.")
EOF

# ------------------------------------------------------------------------------
# Step 3: Offline Security & Egress Unit Test Verification
# ------------------------------------------------------------------------------
if [ -x "${PYTEST_BIN}" ]; then
  log_info "Step 3: Running offline runner & OpenBao egress unit tests..."
  "${PYTEST_BIN}" \
    packages/brainsOS-runner/tests/test_docker_runner.py \
    packages/brainsOS-runner/tests/test_runner_images_and_compose.py \
    -q
  "${PYTEST_BIN}" \
    packages/brainsOS-telemetry/tests/test_openbao_security.py \
    -k "egress or sni or tavily or proxy_auth or allowed_repos" \
    -q
  log_success "Offline egress & ephemeral runner unit tests passed."
else
  log_warn "Pytest virtualenv not found at ${PYTEST_BIN}; skipping Step 3 unit tests."
fi

# ------------------------------------------------------------------------------
# Step 4: Rule 1 Memory Plane Purity Check
# ------------------------------------------------------------------------------
log_info "Step 4: Checking Rule 1 memory plane purity..."
DATA_ROOT="${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}"
CINDY_MEM_DIR="${DATA_ROOT}/agents/bawtford/memories"
if [ ! -d "${CINDY_MEM_DIR}" ]; then
  CINDY_MEM_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${DATA_ROOT}/agent_memories}/bawtford"
fi
if [ -d "${CINDY_MEM_DIR}" ]; then
  MEM_FILES=$(find "${CINDY_MEM_DIR}" -type f ! -name "*.md" ! -name ".gitkeep" ! -name ".*" ! -name "subagents.json" 2>/dev/null || true)
  if [ -z "${MEM_FILES}" ]; then
    log_success "Rule 1 verified: Memory plane ${CINDY_MEM_DIR} is pure OKF Markdown."
  else
    log_error "Memory plane purity violation: non-markdown files detected: ${MEM_FILES}"
    exit 1
  fi
else
  log_info "No local memory partition at ${CINDY_MEM_DIR}; skipping directory scan."
fi

# ------------------------------------------------------------------------------
# Step 5: Non-Destructive Live Runtime Inspection (Optional / --live)
# ------------------------------------------------------------------------------
if [ "${DRY_RUN}" = true ]; then
  log_info "[DRY-RUN] Skipping live Docker container inspection."
  log_success "ALL M3 EGRESS VERIFICATION CHECKS PASSED (DRY-RUN MODE)."
  exit 0
fi

PROXY_CONTAINER=""
if command -v docker >/dev/null 2>&1; then
  PROXY_CONTAINER="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-(agent-|net-)?(tool-)?egress-proxy$' | head -n 1 || true)"
fi

if [ -z "${PROXY_CONTAINER}" ]; then
  if [ "${LIVE_MODE}" = "required" ]; then
    log_error "Live egress proxy container is not running (--live requires running stack)."
    exit 1
  fi
  log_info "Live egress proxy container is not running; offline static & unit verification passed (pass --live when stack is up)."
  log_success "ALL M3 EGRESS VERIFICATION CHECKS PASSED (OFFLINE SAFE MODE)."
  exit 0
fi

log_info "Step 5: Inspecting running egress proxy (${PROXY_CONTAINER}) & active runner containers..."
PROXY_STATUS="$(docker inspect "${PROXY_CONTAINER}" --format '{{.State.Status}}' 2>/dev/null || echo "unknown")"
if [ "${PROXY_STATUS}" != "running" ]; then
  log_error "Proxy container ${PROXY_CONTAINER} status is '${PROXY_STATUS}'."
  exit 1
fi
log_success "Proxy container ${PROXY_CONTAINER} is running."

ACTIVE_RUNNERS="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^brainsos-agent-runner-' || true)"
for rc in ${ACTIVE_RUNNERS}; do
  ENV_TOKENS="$(docker exec "${rc}" env 2>/dev/null | grep -i -E '^(gh_token|github_token|github_pat)=' || true)"
  if [ -n "${ENV_TOKENS}" ]; then
    log_error "Security Boundary Violation in ${rc}: GitHub tokens detected in container environment!"
    exit 1
  fi
  if docker exec "${rc}" test -S /var/run/docker.sock 2>/dev/null; then
    log_error "Security Violation: Host Docker socket mounted in ${rc}!"
    exit 1
  fi
  log_success "Verified running runner ${rc} has zero ambient GitHub tokens and no Docker socket."
done

WEB_PORT="${TOOL_EGRESS_WEB_PORT:-8081}"
WEB_PASSWORD="${TOOL_EGRESS_WEB_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-}}"
if [ -n "${WEB_PASSWORD}" ] && command -v curl >/dev/null 2>&1; then
  FLOWS_JSON="$(curl -fsS -H "Authorization: Bearer ${WEB_PASSWORD}" "http://127.0.0.1:${WEB_PORT}/flows" 2>/dev/null || true)"
  if [ -n "${FLOWS_JSON}" ] && [ -n "${GITHUB_TOKEN_CINDY:-}" ] && echo "${FLOWS_JSON}" | grep -Fq "${GITHUB_TOKEN_CINDY}"; then
    log_error "SECURITY VIOLATION: Raw GITHUB_TOKEN_CINDY found in mitmweb /flows!"
    exit 1
  fi
fi

echo ""
log_success "================================================================="
log_success "  ALL M3 EGRESS CREDENTIAL INJECTION CHECKS PASSED!              "
log_success "================================================================="
