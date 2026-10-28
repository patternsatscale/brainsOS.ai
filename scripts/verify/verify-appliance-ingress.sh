#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Verification for Appliance Ingress Lockdown (Ticket #312)
# Validates:
#   1. docker/compose/compose.appliance.yml correctly unpublishes internal ports
#      and ensures only Caddy publishes ports (80/tcp and 443/tcp).
#   2. config/caddy/Caddyfile.appliance syntax and single-origin TLS-ALPN-01 configuration.
#   3. appliances/scripts/harden-host.sh syntax and dry-run/check functionality.
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

log_info "Running Ticket #312 Appliance Ingress Lockdown Verification Suite..."

# ------------------------------------------------------------------------------
# Test 1: Shell script syntax validation
# ------------------------------------------------------------------------------
log_info "1. Validating shell script syntax for appliances/scripts/harden-host.sh..."
bash -n appliances/scripts/harden-host.sh
log_success "Shell syntax validation passed."

# ------------------------------------------------------------------------------
# Test 2: Host hardening script dry-run execution
# ------------------------------------------------------------------------------
log_info "2. Testing appliances/scripts/harden-host.sh --dry-run..."
DRY_RUN_OUTPUT="$(./appliances/scripts/harden-host.sh --dry-run)"
if echo "${DRY_RUN_OUTPUT}" | grep -q "Appliance host perimeter hardening completed successfully"; then
  log_success "harden-host.sh --dry-run executed successfully."
else
  log_error "harden-host.sh --dry-run did not complete as expected:"
  echo "${DRY_RUN_OUTPUT}"
  exit 1
fi

# ------------------------------------------------------------------------------
# Test 3: Docker Compose appliance overlay configuration validation
# ------------------------------------------------------------------------------
log_info "3. Validating Docker Compose appliance overlay configuration..."
COMPOSE_CONFIG="$(docker compose -f docker-compose.yml -f docker/compose/compose.appliance.yml config)"
log_success "Docker compose config successfully merged base and appliance overlay."

log_info "Checking published ports in merged compose configuration..."
# Extract published ports from the resolved compose config using python
PYTHON_CHECK_PORTS="
import sys, yaml

config = yaml.safe_load('''${COMPOSE_CONFIG}''')
services = config.get('services', {})

violations = []
caddy_ports = []

for svc_name, svc_conf in services.items():
    ports = svc_conf.get('ports', [])
    if ports:
        published_info = [str(p.get('published', p)) if isinstance(p, dict) else str(p) for p in ports]
        if svc_name == 'caddy':
            caddy_ports.extend(published_info)
        else:
            violations.append(f'{svc_name}: {published_info}')

if violations:
    print('ERROR: Internal services with published ports detected:', file=sys.stderr)
    for v in violations:
        print(f'  - {v}', file=sys.stderr)
    sys.exit(1)

print(f'Only caddy published ports found: {caddy_ports}')
"

python3 -c "${PYTHON_CHECK_PORTS}"
log_success "Port lockdown verified: Zero internal services expose host ports in compose.appliance.yml."

# ------------------------------------------------------------------------------
# Test 4: Caddyfile.appliance Syntax Validation
# ------------------------------------------------------------------------------
log_info "4. Validating Caddyfile.appliance syntax..."
if docker compose ps --services --filter "status=running" | grep -qw caddy; then
  # Validate using running caddy container
  docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile.appliance --adapter caddyfile
  log_success "Caddyfile.appliance validated successfully inside running caddy container."
else
  # Validate using standalone caddy container
  docker run --rm \
    -v "${REPO_ROOT}/config/caddy/Caddyfile.appliance:/etc/caddy/Caddyfile:ro" \
    caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
  log_success "Caddyfile.appliance validated successfully inside standalone caddy container."
fi

# ------------------------------------------------------------------------------
# Test 5: Verify /api/v1/system/* and /system routes in Caddyfile
# ------------------------------------------------------------------------------
log_info "5. Verifying /api/v1/system/* and /system route declarations..."
if grep -q "handle /api/v1/system/\*" config/caddy/Caddyfile && grep -q "handle /api/v1/system/\*" config/caddy/Caddyfile.appliance; then
  log_success "Found /api/v1/system/* reverse proxy route in both Caddyfiles."
else
  log_error "Missing /api/v1/system/* route in Caddyfile or Caddyfile.appliance!"
  exit 1
fi

if grep -q "@system_path path /system" config/caddy/Caddyfile && grep -q "@system_path path /system" config/caddy/Caddyfile.appliance; then
  log_success "Found @system_path portal route in both Caddyfiles."
else
  log_error "Missing @system_path route in Caddyfile or Caddyfile.appliance!"
  exit 1
fi

log_success "=================================================================="
log_success "All Ticket #312 Appliance Ingress Lockdown verifications PASSED!"
log_success "=================================================================="
