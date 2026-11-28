#!/usr/bin/env bash
# ==============================================================================
# brainsOS: v0.5.3 RC2 Pre-AMI Audit Hardening — Offline E2E Verification Runner
# Executes:
#   1. 4-Tier Offline E2E Pytest Suite (packages/brainsOS-appliance/tests/e2e/)
#   2. Infra TypeScript typecheck + Vitest suite
#   3. Shell script syntax validation (bash -n)
#   4. Docker Compose appliance overlay configuration validation
#   5. Private fleet reference audit (verify-no-private-refs.sh)
#   6. Appliance ingress lockdown audit (verify-appliance-ingress.sh)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

if ! command -v npm >/dev/null 2>&1 && [ -x "${HOME}/.local/bin/npm" ]; then
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [ ! -x "${REPO_ROOT}/.venv/bin/pytest" ]; then
  echo "[ERROR] Missing ${REPO_ROOT}/.venv/bin/pytest" >&2
  exit 1
fi

echo "[1/6] Running v0.5.3 RC2 4-tier offline E2E suite..."
"${REPO_ROOT}/.venv/bin/pytest" "${REPO_ROOT}/packages/brainsOS-appliance/tests/e2e/" -q

echo "[2/6] Running infra TypeScript typecheck and Vitest suite..."
npm --prefix "${REPO_ROOT}/infra" run typecheck
npm --prefix "${REPO_ROOT}/infra" test

echo "[3/6] Running shell syntax checks (bash -n)..."
find "${REPO_ROOT}/scripts" "${REPO_ROOT}/packages/brainsOS-appliance" -type f -name "*.sh" -exec bash -n {} +

echo "[4/6] Validating Docker Compose appliance configuration..."
TMP_COMPOSE_ENV=""
COMPOSE_ENV_ARGS=()
if [ ! -f "${REPO_ROOT}/.env" ] && [ -f "${REPO_ROOT}/.env.example" ]; then
  TMP_COMPOSE_ENV="$(mktemp)"
  trap 'rm -f "${TMP_COMPOSE_ENV}"' EXIT
  while IFS= read -r _line || [ -n "${_line}" ]; do
    case "${_line}" in
      ""|\#*) continue ;;
      *=*)
        _k="${_line%%=*}"
        _v="${_line#*=}"
        _k="${_k#"${_k%%[![:space:]]*}"}"
        _k="${_k%"${_k##*[![:space:]]}"}"
        [ -z "${_v}" ] && _v="verify-dummy-${_k}"
        printf '%s=%s\n' "${_k}" "${_v}" >> "${TMP_COMPOSE_ENV}"
        ;;
    esac
  done < "${REPO_ROOT}/.env.example"
  COMPOSE_ENV_ARGS=("--env-file" "${TMP_COMPOSE_ENV}")
fi
docker compose "${COMPOSE_ENV_ARGS[@]}" -f "${REPO_ROOT}/docker-compose.yml" -f "${REPO_ROOT}/docker/compose/compose.appliance.yml" config -q

echo "[5/6] Running private fleet reference audit..."
"${REPO_ROOT}/scripts/verify/verify-no-private-refs.sh"

echo "[6/6] Running appliance ingress verification..."
"${REPO_ROOT}/scripts/verify/verify-appliance-ingress.sh"

echo "[SUCCESS] All v0.5.3 RC2 E2E and repository verification gates passed!"
