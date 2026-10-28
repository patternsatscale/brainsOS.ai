#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Automated Verification for Appliance Ingress Lockdown (Ticket #312)
# Validates:
#   1. docker/compose/compose.appliance.yml correctly unpublishes internal ports
#      and ensures only Caddy publishes ports (80/tcp and 443/tcp).
#   2. config/caddy/Caddyfile.appliance syntax and single-origin TLS-ALPN-01 configuration.
#   3. packages/brainsOS-appliance/scripts/harden-host.sh syntax and dry-run/check functionality.
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
HARDEN_SCRIPT="packages/brainsOS-appliance/scripts/harden-host.sh"
if [ ! -f "${HARDEN_SCRIPT}" ]; then
  log_error "Missing ${HARDEN_SCRIPT}"
  exit 1
fi

log_info "1. Validating shell script syntax for ${HARDEN_SCRIPT}..."
bash -n "${HARDEN_SCRIPT}"
log_success "Shell syntax validation passed."

# ------------------------------------------------------------------------------
# Test 2: Host hardening script dry-run execution
# ------------------------------------------------------------------------------
log_info "2. Testing ${HARDEN_SCRIPT} --dry-run..."
DRY_RUN_OUTPUT="$("${HARDEN_SCRIPT}" --dry-run)"
if echo "${DRY_RUN_OUTPUT}" | grep -q "Appliance host perimeter hardening"; then
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

# ------------------------------------------------------------------------------
# Test 6: Verify Explicit Site Addresses & Dynamic TLS Modes (Ticket #323)
# ------------------------------------------------------------------------------
log_info "6. Verifying Ticket #323 Ingress & TLS invariants..."

# 6A. Ensure no bare :443 listener exists in Caddyfile.appliance
if grep -qE '^:443\s*\{' config/caddy/Caddyfile.appliance; then
  log_error "Caddyfile.appliance must not define a bare :443 site block (must use explicit {$BRAINSOS_DOMAIN})."
  exit 1
fi
log_success "No bare :443 block found; explicit hostname listeners verified."

# 6B. Ensure all defined (tls_*) snippets are imported or dynamically selected
python3 -c "
with open('config/caddy/Caddyfile.appliance') as f:
    content = f.read()

import re
defined_snippets = re.findall(r'^\((tls_[a-zA-Z0-9_]+)\)\s*\{', content, re.MULTILINE)
assert defined_snippets, 'No tls_* snippets found in Caddyfile.appliance'

# Check that import tls_{\$BRAINSOS_TLS_MODE...} or direct imports exist
assert 'import tls_{\$BRAINSOS_TLS_MODE' in content or all(f'import {s}' in content for s in defined_snippets), \
    f'Defined tls snippets {defined_snippets} not imported or dynamically selected!'
print(f'Verified TLS snippets: {defined_snippets}')
"
log_success "All TLS snippets in Caddyfile.appliance are dynamically imported."

# 6C. Verify /system/ca.crt endpoint exists for operator trust
if grep -q "handle /system/ca.crt" config/caddy/Caddyfile.appliance; then
  log_success "Found /system/ca.crt root CA download route in Caddyfile.appliance."
else
  log_error "Missing /system/ca.crt download route in Caddyfile.appliance!"
  exit 1
fi

# 6D. Verify Caddyfile.appliance syntax across all TLS modes
for mode in internal acme route53; do
  docker run --rm \
    -e BRAINSOS_TLS_MODE="${mode}" \
    -e ACME_EMAIL="ops@example.com" \
    -e BRAINSOS_DOMAIN="test.brainsos.ai" \
    -e BRAINSOS_IP_SITES="127.0.0.1" \
    -v "${REPO_ROOT}/config/caddy:/etc/caddy:ro" \
    --entrypoint caddy brainsos-caddy:latest validate --config /etc/caddy/Caddyfile.appliance --adapter caddyfile >/dev/null 2>&1
done
log_success "Caddyfile.appliance successfully validated for all TLS modes (internal, acme, route53)."

# 6E. Verify compose.ingress.yml supports runtime CADDYFILE selection
if grep -q "CADDYFILE=\${CADDYFILE:-Caddyfile}" docker/compose/compose.ingress.yml; then
  log_success "Verified CADDYFILE runtime selection in docker/compose/compose.ingress.yml."
else
  log_error "Missing CADDYFILE runtime selection in docker/compose/compose.ingress.yml!"
  exit 1
fi

log_success "=================================================================="
log_success "All Ticket #312 / #323 Appliance Ingress verifications PASSED!"
log_success "=================================================================="
