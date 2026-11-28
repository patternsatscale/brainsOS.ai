#!/usr/bin/env bash
# ==============================================================================
# brainsOS: EC2 Instance Metadata Service (IMDS) Container Isolation Guard
# Ticket #330 (B6)
#
# Restricts container access to the AWS EC2 Instance Metadata Service
# (169.254.169.254/32) via the DOCKER-USER iptables chain:
#   - Only current IPv4 addresses of brainsos-control-litellm are allowed
#     (RETURN) so LiteLLM can fetch ambient Bedrock instance-role credentials.
#   - All other container traffic to 169.254.169.254/32 is dropped (DROP).
#   - If LiteLLM is not running, the chain fails closed (DROP only).
#   - Host processes use OUTPUT and are unaffected.
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
REPO_ROOT="${BRAINSOS_REPO_ROOT:-}"
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -z "${REPO_ROOT}" ]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

show_help() {
  cat <<EOF
Usage: scripts/setup/imds-guard.sh [--apply | --check | --remove] [--dry-run] [--force]
  --apply   (default) create/refresh chain BRAINSOS-IMDS and the DOCKER-USER jump
  --check   exit 0 only if the jump exists AND the chain ends with DROP AND every current LiteLLM IP has a RETURN rule
  --remove  delete the jump and the chain
  --dry-run print the iptables commands instead of executing them
  --force   run even when BRAINSOS_APPLIANCE != true
EOF
}

ACTION="apply"
DRY_RUN=false
FORCE=false

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)
      ACTION="apply"
      shift
      ;;
    --check)
      ACTION="check"
      shift
      ;;
    --remove)
      ACTION="remove"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

ENV_FILE="${BRAINSOS_ENV_FILE:-${REPO_ROOT}/.env}"
if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

# No-op guard: Linux + iptables + (BRAINSOS_APPLIANCE=true or --force)
if [ "$(uname -s)" != "Linux" ] || ! command -v iptables >/dev/null 2>&1 || { [ "${FORCE}" != true ] && [ "${BRAINSOS_APPLIANCE:-false}" != "true" ]; }; then
  log_info "IMDS guard not applicable on this host; skipping."
  exit 0
fi

if [ "${DRY_RUN}" != true ] && [ "$(id -u)" -ne 0 ]; then
  log_error "Root privileges are required to ${ACTION} the IMDS iptables guard (run with sudo or --dry-run)."
  exit 1
fi

run_ipt() {
  if [ "${DRY_RUN}" = true ]; then
    echo "iptables $*"
  else
    iptables "$@"
  fi
}

run_ip6t() {
  if [ "${DRY_RUN}" = true ]; then
    echo "ip6tables $*"
  elif command -v ip6tables >/dev/null 2>&1; then
    ip6tables "$@"
  fi
}

is_valid_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

append_unique_ip() {
  local candidate="$1"
  local arr_name="$2"
  is_valid_ipv4 "${candidate}" || return 0
  local existing
  eval "for existing in \"\${${arr_name}[@]+\"\${${arr_name}[@]}\"}\"; do
    if [ \"\${existing}\" = \"\${candidate}\" ]; then
      return 0
    fi
  done"
  eval "${arr_name}+=(\"\${candidate}\")"
}

inspect_container_internal_ip() {
  local cname="$1"
  local raw
  raw="$(docker inspect -f '{{with index .NetworkSettings.Networks "brainsos-internal-net"}}{{.IPAddress}}{{end}}' "${cname}" 2>/dev/null || true)"
  raw="$(printf '%s' "${raw}" | awk '{print $1}')"
  if is_valid_ipv4 "${raw}"; then
    printf '%s' "${raw}"
  fi
}

route53_tls_enabled() {
  [ "${BRAINSOS_TLS_MODE:-internal}" = "route53" ] || [ "${ACME_DNS_PROVIDER:-}" = "route53" ]
}

docker_user_is_ordered() {
  local ipt_bin="$1"
  local imds_dst="$2"
  local imds_chain="$3"
  local egress_chain="$4"
  local imds_expected="-A DOCKER-USER -d ${imds_dst} -j ${imds_chain}"
  local egress_expected="-A DOCKER-USER -i ${INTERNAL_BRIDGE} -j ${egress_chain}"
  local rules rule1 rule2 imds_count egress_count

  "${ipt_bin}" -C DOCKER-USER -d "${imds_dst}" -j "${imds_chain}" 2>/dev/null || return 1
  "${ipt_bin}" -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j "${egress_chain}" 2>/dev/null || return 1

  rules="$("${ipt_bin}" -S DOCKER-USER 2>/dev/null | grep '^-A DOCKER-USER ' || true)"
  if [ -z "${rules}" ]; then
    # Stateless test shim (-C passed but -S unimplemented): treat as already present/ordered
    return 0
  fi

  rule1="$(printf '%s\n' "${rules}" | sed -n '1p')"
  rule2="$(printf '%s\n' "${rules}" | sed -n '2p')"
  imds_count="$(printf '%s\n' "${rules}" | grep -Fx -- "${imds_expected}" | wc -l | tr -d ' ')"
  egress_count="$(printf '%s\n' "${rules}" | grep -Fx -- "${egress_expected}" | wc -l | tr -d ' ')"

  [ "${rule1}" = "${imds_expected}" ] && [ "${rule2}" = "${egress_expected}" ] \
    && [ "${imds_count}" -eq 1 ] && [ "${egress_count}" -eq 1 ]
}

ensure_docker_user_order() {
  local ipt_bin="$1"
  local imds_dst="$2"
  local imds_chain="$3"
  local egress_chain="$4"
  local runner="run_ipt"
  if [ "${ipt_bin}" = "ip6tables" ]; then
    runner="run_ip6t"
  fi

  if [ "${DRY_RUN}" = true ]; then
    "${runner}" -N DOCKER-USER
    if docker_user_is_ordered "${ipt_bin}" "${imds_dst}" "${imds_chain}" "${egress_chain}"; then
      return 0
    fi
    if "${ipt_bin}" -C DOCKER-USER -d "${imds_dst}" -j "${imds_chain}" 2>/dev/null; then
      "${runner}" -D DOCKER-USER -d "${imds_dst}" -j "${imds_chain}"
    fi
    if "${ipt_bin}" -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j "${egress_chain}" 2>/dev/null; then
      "${runner}" -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j "${egress_chain}"
    fi
    "${runner}" -I DOCKER-USER 1 -i "${INTERNAL_BRIDGE}" -j "${egress_chain}"
    "${runner}" -I DOCKER-USER 1 -d "${imds_dst}" -j "${imds_chain}"
    return 0
  fi

  "${ipt_bin}" -N DOCKER-USER 2>/dev/null || true
  if docker_user_is_ordered "${ipt_bin}" "${imds_dst}" "${imds_chain}" "${egress_chain}"; then
    return 0
  fi
  while "${ipt_bin}" -C DOCKER-USER -d "${imds_dst}" -j "${imds_chain}" 2>/dev/null; do
    "${ipt_bin}" -D DOCKER-USER -d "${imds_dst}" -j "${imds_chain}" 2>/dev/null || break
  done
  while "${ipt_bin}" -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j "${egress_chain}" 2>/dev/null; do
    "${ipt_bin}" -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j "${egress_chain}" 2>/dev/null || break
  done
  if [ "${ipt_bin}" = "ip6tables" ]; then
    "${ipt_bin}" -I DOCKER-USER 1 -i "${INTERNAL_BRIDGE}" -j "${egress_chain}" 2>/dev/null || true
    "${ipt_bin}" -I DOCKER-USER 1 -d "${imds_dst}" -j "${imds_chain}" 2>/dev/null || true
  else
    "${ipt_bin}" -I DOCKER-USER 1 -i "${INTERNAL_BRIDGE}" -j "${egress_chain}"
    "${ipt_bin}" -I DOCKER-USER 1 -d "${imds_dst}" -j "${imds_chain}"
  fi
}

check_docker_user_order() {
  local ipt_bin="$1"
  local imds_dst="$2"
  local imds_chain="$3"
  local egress_chain="$4"
  local imds_expected="-A DOCKER-USER -d ${imds_dst} -j ${imds_chain}"
  local egress_expected="-A DOCKER-USER -i ${INTERNAL_BRIDGE} -j ${egress_chain}"
  local rules rule1 rule2 imds_count egress_count

  rules="$("${ipt_bin}" -S DOCKER-USER 2>/dev/null | grep '^-A DOCKER-USER ' || true)"
  rule1="$(printf '%s\n' "${rules}" | sed -n '1p')"
  rule2="$(printf '%s\n' "${rules}" | sed -n '2p')"
  imds_count="$(printf '%s\n' "${rules}" | grep -Fx -- "${imds_expected}" | wc -l | tr -d ' ')"
  egress_count="$(printf '%s\n' "${rules}" | grep -Fx -- "${egress_expected}" | wc -l | tr -d ' ')"

  if [ "${rule1}" != "${imds_expected}" ] || [ "${rule2}" != "${egress_expected}" ] \
    || [ "${imds_count}" -ne 1 ] || [ "${egress_count}" -ne 1 ]; then
    log_error "${ipt_bin} DOCKER-USER rule order/uniqueness invalid (expected #1 '${imds_expected}' [count=${imds_count}], #2 '${egress_expected}' [count=${egress_count}]; got #1 '${rule1}', #2 '${rule2}')."
    return 1
  fi
  return 0
}

is_valid_bridge_name() {
  [[ "$1" =~ ^(br-[a-zA-Z0-9_-]{1,28}|docker0)$ ]]
}

append_unique_bridge() {
  local candidate="$1"
  local arr_name="$2"
  is_valid_bridge_name "${candidate}" || return 0
  if [ "${candidate}" = "${INTERNAL_BRIDGE:-}" ]; then
    return 0
  fi
  local existing
  eval "for existing in \"\${${arr_name}[@]+\"\${${arr_name}[@]}\"}\"; do
    if [ \"\${existing}\" = \"\${candidate}\" ]; then
      return 0
    fi
  done"
  eval "${arr_name}+=(\"\${candidate}\")"
}

linklocal_jump_is_valid() {
  local br="$1"
  local expected="-A DOCKER-USER -i ${br} -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL"
  local rules count jump_line ret_line

  iptables -C DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null || return 1
  rules="$(iptables -S DOCKER-USER 2>/dev/null | grep '^-A DOCKER-USER ' || true)"
  if [ -z "${rules}" ]; then
    # Stateless test shim (-C passed but -S unimplemented)
    return 0
  fi
  count="$(printf '%s\n' "${rules}" | grep -Fx -- "${expected}" | wc -l | tr -d ' ')"
  [ "${count}" -eq 1 ] || return 1
  jump_line="$(printf '%s\n' "${rules}" | grep -nxF -- "${expected}" | head -n 1 | cut -d: -f1 || true)"
  [ -n "${jump_line}" ] && [ "${jump_line}" -ge 3 ] || return 1
  ret_line="$(printf '%s\n' "${rules}" | grep -nxF -- "-A DOCKER-USER -j RETURN" | head -n 1 | cut -d: -f1 || true)"
  if [ -n "${ret_line}" ] && [ "${jump_line}" -ge "${ret_line}" ]; then
    return 1
  fi
  return 0
}

ensure_linklocal_jumps() {
  local br
  for br in "${LINKLOCAL_BRIDGES[@]+"${LINKLOCAL_BRIDGES[@]}"}"; do
    [ -n "${br}" ] || continue
    if linklocal_jump_is_valid "${br}"; then
      continue
    fi
    if [ "${DRY_RUN}" = true ]; then
      if iptables -C DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null; then
        run_ipt -D DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL
      fi
      run_ipt -I DOCKER-USER 3 -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL
    else
      while iptables -C DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null; do
        iptables -D DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null || break
      done
      iptables -I DOCKER-USER 3 -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL
    fi
  done
}

# 1. Collect IMDS-authorized container IPs (LiteLLM + Caddy only when Route 53 DNS-01 TLS is active)
RAW_LITELLM_IPS="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' brainsos-control-litellm 2>/dev/null || true)"
LITELLM_IPS=()
for ip in ${RAW_LITELLM_IPS}; do
  append_unique_ip "${ip}" LITELLM_IPS
done
if [ "${#LITELLM_IPS[@]}" -eq 0 ] && [ -n "${BRAINSOS_LITELLM_STATIC_IP:-}" ]; then
  for ip in ${BRAINSOS_LITELLM_STATIC_IP//,/ }; do
    append_unique_ip "${ip}" LITELLM_IPS
  done
fi

CADDY_IMDS_IPS=()
if route53_tls_enabled; then
  RAW_CADDY_IPS="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' brainsos-ingress-caddy 2>/dev/null || true)"
  for ip in ${RAW_CADDY_IPS}; do
    append_unique_ip "${ip}" CADDY_IMDS_IPS
  done
  if [ "${#CADDY_IMDS_IPS[@]}" -eq 0 ] && [ -n "${BRAINSOS_CADDY_STATIC_IP:-}" ]; then
    for ip in ${BRAINSOS_CADDY_STATIC_IP//,/ }; do
      append_unique_ip "${ip}" CADDY_IMDS_IPS
    done
  fi
  if [ "${#CADDY_IMDS_IPS[@]}" -eq 0 ] && [ -n "${CADDY_INGRESS_IP:-}" ]; then
    append_unique_ip "${CADDY_INGRESS_IP}" CADDY_IMDS_IPS
  fi
fi

ALLOWED_IMDS_IPS=()
for ip in "${LITELLM_IPS[@]+"${LITELLM_IPS[@]}"}" "${CADDY_IMDS_IPS[@]+"${CADDY_IMDS_IPS[@]}"}"; do
  append_unique_ip "${ip}" ALLOWED_IMDS_IPS
done

# 2. Discover brainsos-internal-net bridge & WAN-egress-authorized container IPs (route agent WAN via tool-egress-proxy:8082)
INTERNAL_BRIDGE="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' brainsos-internal-net 2>/dev/null || true)"
INTERNAL_BRIDGE="$(printf '%s' "${INTERNAL_BRIDGE}" | awk '{print $1}')"
if [[ ! "${INTERNAL_BRIDGE}" =~ ^(br-[a-zA-Z0-9_-]{1,12}|docker0)$ ]]; then
  INTERNAL_BRIDGE="${BRAINSOS_INTERNAL_BRIDGE:-br-internal}"
fi

LINKLOCAL_BRIDGES=()
for _net_spec in \
  "brainsos-ingress-net:${BRAINSOS_INGRESS_BRIDGE:-br-ingress}" \
  "brainsos-control-net:${BRAINSOS_CONTROL_BRIDGE:-br-control}" \
  "brainsos-auth-net:${BRAINSOS_AUTH_BRIDGE:-br-auth}" \
  "brainsos-secrets-net:${BRAINSOS_SECRETS_BRIDGE:-br-secrets}" \
  "brainsos-mail-net:${BRAINSOS_MAIL_BRIDGE:-br-mail}" \
  "brainsos-ide-net:${BRAINSOS_IDE_BRIDGE:-br-ide}" \
  "brainsos-telemetry-net:${BRAINSOS_TELEMETRY_BRIDGE:-br-telemetry}" \
  "brainsos-sandbox-net:${BRAINSOS_SANDBOX_BRIDGE:-br-sandbox}"
do
  _n_name="${_net_spec%%:*}"
  _n_fallback="${_net_spec#*:}"
  _n_br="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "${_n_name}" 2>/dev/null || true)"
  _n_br="$(printf '%s' "${_n_br}" | awk '{print $1}')"
  if ! is_valid_bridge_name "${_n_br}"; then
    _n_br="${_n_fallback}"
  fi
  append_unique_bridge "${_n_br}" LINKLOCAL_BRIDGES
done

while IFS= read -r _dyn_net; do
  _dyn_net="$(printf '%s' "${_dyn_net}" | tr -d '\r' | awk '{print $1}')"
  if [[ "${_dyn_net}" =~ ^brainsos-[a-zA-Z0-9_-]+-net$ ]]; then
    _dyn_br="$(docker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "${_dyn_net}" 2>/dev/null || true)"
    _dyn_br="$(printf '%s' "${_dyn_br}" | awk '{print $1}')"
    append_unique_bridge "${_dyn_br}" LINKLOCAL_BRIDGES
  fi
done < <(docker network ls --format '{{.Name}}' 2>/dev/null || true)

append_unique_bridge "docker0" LINKLOCAL_BRIDGES

PROXY_IP="$(inspect_container_internal_ip brainsos-agent-egress-proxy)"
if [ -z "${PROXY_IP}" ]; then
  PROXY_IP="${BRAINSOS_EGRESS_PROXY_STATIC_IP:-${TOOL_EGRESS_INTERNAL_IP:-172.28.1.2}}"
fi

CADDY_INTERNAL_ADDR="$(inspect_container_internal_ip brainsos-ingress-caddy)"
if [ -z "${CADDY_INTERNAL_ADDR}" ]; then
  CADDY_INTERNAL_ADDR="${CADDY_INTERNAL_IP:-172.28.1.10}"
fi

LITELLM_INTERNAL_ADDR="$(inspect_container_internal_ip brainsos-control-litellm)"

EGRESS_ALLOWED_IPS=()
append_unique_ip "${PROXY_IP}" EGRESS_ALLOWED_IPS
append_unique_ip "${CADDY_INTERNAL_ADDR}" EGRESS_ALLOWED_IPS
if [ -n "${LITELLM_INTERNAL_ADDR}" ]; then
  append_unique_ip "${LITELLM_INTERNAL_ADDR}" EGRESS_ALLOWED_IPS
fi

if docker ps --format '{{.Names}}' 2>/dev/null | grep -qw "brainsos-agent-mail-ingress"; then
  MAIL_INGRESS_IP="$(inspect_container_internal_ip brainsos-agent-mail-ingress)"
  append_unique_ip "${MAIL_INGRESS_IP}" EGRESS_ALLOWED_IPS
fi

case "${ACTION}" in
  apply)
    log_info "Applying IMDS & link-local/WAN egress container isolation guards (BRAINSOS-IMDS, BRAINSOS-EGRESS, BRAINSOS-LINKLOCAL)..."
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -N BRAINSOS-IMDS
      run_ipt -F BRAINSOS-IMDS
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -A BRAINSOS-IMDS -s "${ip}/32" -j RETURN
        fi
      done
      run_ipt -A BRAINSOS-IMDS -j DROP

      # Restrict brainsos-internal-net WAN egress exclusively to tool-egress-proxy:8082 (+ caddy/active mail-ingress)
      run_ipt -N BRAINSOS-EGRESS
      run_ipt -F BRAINSOS-EGRESS
      run_ipt -A BRAINSOS-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
      run_ipt -A BRAINSOS-EGRESS -o "${INTERNAL_BRIDGE}" -j RETURN
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -A BRAINSOS-EGRESS -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
        fi
      done
      run_ipt -A BRAINSOS-EGRESS -d 169.254.0.0/16 -j DROP
      for ip in "${EGRESS_ALLOWED_IPS[@]+"${EGRESS_ALLOWED_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -A BRAINSOS-EGRESS -s "${ip}/32" -j RETURN
        fi
      done
      run_ipt -A BRAINSOS-EGRESS -j DROP

      # Drop 169.254.0.0/16 (IMDSv4, ECS task metadata 169.254.170.2, link-local) across all other Docker bridges
      run_ipt -N BRAINSOS-LINKLOCAL
      run_ipt -F BRAINSOS-LINKLOCAL
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -A BRAINSOS-LINKLOCAL -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
        fi
      done
      run_ipt -A BRAINSOS-LINKLOCAL -d 169.254.0.0/16 -j DROP

      ensure_docker_user_order iptables "169.254.169.254/32" BRAINSOS-IMDS BRAINSOS-EGRESS
      ensure_linklocal_jumps

      # IPv6 EC2 IMDS (fd00:ec2::254/128) & internal-net WAN egress DROP
      run_ip6t -N BRAINSOS-IMDS6
      run_ip6t -F BRAINSOS-IMDS6
      run_ip6t -A BRAINSOS-IMDS6 -j DROP
      run_ip6t -N BRAINSOS-EGRESS6
      run_ip6t -F BRAINSOS-EGRESS6
      run_ip6t -A BRAINSOS-EGRESS6 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
      run_ip6t -A BRAINSOS-EGRESS6 -o "${INTERNAL_BRIDGE}" -j RETURN
      run_ip6t -A BRAINSOS-EGRESS6 -j DROP
      if command -v ip6tables >/dev/null 2>&1; then
        ensure_docker_user_order ip6tables "fd00:ec2::254/128" BRAINSOS-IMDS6 BRAINSOS-EGRESS6
      else
        run_ip6t -N DOCKER-USER
      fi
    else
      iptables -N BRAINSOS-IMDS 2>/dev/null || true
      iptables -F BRAINSOS-IMDS
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          iptables -A BRAINSOS-IMDS -s "${ip}/32" -j RETURN
        fi
      done
      iptables -A BRAINSOS-IMDS -j DROP

      iptables -N BRAINSOS-EGRESS 2>/dev/null || true
      iptables -F BRAINSOS-EGRESS
      iptables -A BRAINSOS-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
      iptables -A BRAINSOS-EGRESS -o "${INTERNAL_BRIDGE}" -j RETURN
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          iptables -A BRAINSOS-EGRESS -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
        fi
      done
      iptables -A BRAINSOS-EGRESS -d 169.254.0.0/16 -j DROP
      for ip in "${EGRESS_ALLOWED_IPS[@]+"${EGRESS_ALLOWED_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          iptables -A BRAINSOS-EGRESS -s "${ip}/32" -j RETURN
        fi
      done
      iptables -A BRAINSOS-EGRESS -j DROP

      iptables -N BRAINSOS-LINKLOCAL 2>/dev/null || true
      iptables -F BRAINSOS-LINKLOCAL
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          iptables -A BRAINSOS-LINKLOCAL -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
        fi
      done
      iptables -A BRAINSOS-LINKLOCAL -d 169.254.0.0/16 -j DROP

      ensure_docker_user_order iptables "169.254.169.254/32" BRAINSOS-IMDS BRAINSOS-EGRESS
      ensure_linklocal_jumps

      if command -v ip6tables >/dev/null 2>&1; then
        ip6tables -N BRAINSOS-IMDS6 2>/dev/null || true
        ip6tables -F BRAINSOS-IMDS6
        ip6tables -A BRAINSOS-IMDS6 -j DROP
        ip6tables -N BRAINSOS-EGRESS6 2>/dev/null || true
        ip6tables -F BRAINSOS-EGRESS6
        ip6tables -A BRAINSOS-EGRESS6 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
        ip6tables -A BRAINSOS-EGRESS6 -o "${INTERNAL_BRIDGE}" -j RETURN
        ip6tables -A BRAINSOS-EGRESS6 -j DROP
        ensure_docker_user_order ip6tables "fd00:ec2::254/128" BRAINSOS-IMDS6 BRAINSOS-EGRESS6
      fi
      log_info "Active BRAINSOS-IMDS rules:"
      iptables -S BRAINSOS-IMDS
      log_info "Active BRAINSOS-EGRESS rules:"
      iptables -S BRAINSOS-EGRESS
      log_info "Active BRAINSOS-LINKLOCAL rules:"
      iptables -S BRAINSOS-LINKLOCAL
    fi
    log_success "IMDS & WAN egress guards applied (${#ALLOWED_IMDS_IPS[@]} IMDS IP(s) allowed; ${INTERNAL_BRIDGE} WAN egress gated via tool-egress-proxy:8082; ${#LINKLOCAL_BRIDGES[@]} bridge(s) protected by BRAINSOS-LINKLOCAL)."
    ;;

  check)
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS
      run_ipt -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS
      run_ipt -S DOCKER-USER
      run_ipt -S BRAINSOS-IMDS
      run_ipt -S BRAINSOS-EGRESS
      run_ipt -S BRAINSOS-LINKLOCAL
      for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
        if [ -n "${ip}" ]; then
          run_ipt -C BRAINSOS-EGRESS -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
          run_ipt -C BRAINSOS-LINKLOCAL -s "${ip}/32" -d 169.254.169.254/32 -j RETURN
        fi
      done
      for br in "${LINKLOCAL_BRIDGES[@]+"${LINKLOCAL_BRIDGES[@]}"}"; do
        [ -n "${br}" ] && run_ipt -C DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL
      done
      run_ip6t -C DOCKER-USER -d fd00:ec2::254/128 -j BRAINSOS-IMDS6
      run_ip6t -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS6
      run_ip6t -S DOCKER-USER
      run_ip6t -S BRAINSOS-IMDS6
      run_ip6t -S BRAINSOS-EGRESS6
      run_ip6t -C BRAINSOS-EGRESS6 -o "${INTERNAL_BRIDGE}" -j RETURN
      exit 0
    fi
    if ! iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null; then
      log_error "DOCKER-USER jump to BRAINSOS-IMDS is missing."
      exit 1
    fi
    CHAIN_RULES="$(iptables -S BRAINSOS-IMDS 2>/dev/null || true)"
    if [ -z "${CHAIN_RULES}" ]; then
      log_error "Chain BRAINSOS-IMDS does not exist or is empty."
      exit 1
    fi
    LAST_RULE="$(printf '%s\n' "${CHAIN_RULES}" | tail -n 1)"
    if [ "${LAST_RULE}" != "-A BRAINSOS-IMDS -j DROP" ]; then
      log_error "Chain BRAINSOS-IMDS does not end with -j DROP (last rule: ${LAST_RULE})."
      exit 1
    fi
    for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
      if [ -n "${ip}" ]; then
        if ! iptables -C BRAINSOS-IMDS -s "${ip}/32" -j RETURN 2>/dev/null; then
          log_error "Missing RETURN rule in BRAINSOS-IMDS for authorized IP ${ip}/32."
          exit 1
        fi
      fi
    done

    if ! iptables -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS 2>/dev/null; then
      log_error "DOCKER-USER jump to BRAINSOS-EGRESS is missing."
      exit 1
    fi
    if ! check_docker_user_order iptables "169.254.169.254/32" BRAINSOS-IMDS BRAINSOS-EGRESS; then
      exit 1
    fi
    EGRESS_RULES="$(iptables -S BRAINSOS-EGRESS 2>/dev/null || true)"
    if [ -z "${EGRESS_RULES}" ]; then
      log_error "Chain BRAINSOS-EGRESS does not exist or is empty."
      exit 1
    fi
    EGRESS_LAST="$(printf '%s\n' "${EGRESS_RULES}" | tail -n 1)"
    if [ "${EGRESS_LAST}" != "-A BRAINSOS-EGRESS -j DROP" ]; then
      log_error "Chain BRAINSOS-EGRESS does not end with -j DROP (last rule: ${EGRESS_LAST})."
      exit 1
    fi
    if ! iptables -C BRAINSOS-EGRESS -o "${INTERNAL_BRIDGE}" -j RETURN 2>/dev/null; then
      log_error "Chain BRAINSOS-EGRESS missing intra-plane RETURN for ${INTERNAL_BRIDGE}."
      exit 1
    fi
    if ! iptables -C BRAINSOS-EGRESS -d 169.254.0.0/16 -j DROP 2>/dev/null; then
      log_error "Chain BRAINSOS-EGRESS missing link-local/IMDS drop rule (-d 169.254.0.0/16 -j DROP)."
      exit 1
    fi
    drop_ll_line="$(printf '%s\n' "${EGRESS_RULES}" | grep -nxF -- "-A BRAINSOS-EGRESS -d 169.254.0.0/16 -j DROP" | head -n 1 | cut -d: -f1 || true)"
    for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
      if [ -n "${ip}" ]; then
        if ! iptables -C BRAINSOS-EGRESS -s "${ip}/32" -d 169.254.169.254/32 -j RETURN 2>/dev/null; then
          log_error "Chain BRAINSOS-EGRESS missing IMDS RETURN rule for authorized IP ${ip}/32."
          exit 1
        fi
        imds_egress_line="$(printf '%s\n' "${EGRESS_RULES}" | grep -nxF -- "-A BRAINSOS-EGRESS -s ${ip}/32 -d 169.254.169.254/32 -j RETURN" | head -n 1 | cut -d: -f1 || true)"
        if [ -z "${imds_egress_line}" ] || [ -z "${drop_ll_line}" ] || [ "${imds_egress_line}" -ge "${drop_ll_line}" ]; then
          log_error "Chain BRAINSOS-EGRESS IMDS RETURN rule for ${ip}/32 must precede -d 169.254.0.0/16 -j DROP."
          exit 1
        fi
      fi
    done
    if [ -n "${PROXY_IP}" ] && ! iptables -C BRAINSOS-EGRESS -s "${PROXY_IP}/32" -j RETURN 2>/dev/null; then
      log_error "Chain BRAINSOS-EGRESS missing RETURN for tool-egress-proxy (${PROXY_IP}/32)."
      exit 1
    fi

    LINKLOCAL_RULES="$(iptables -S BRAINSOS-LINKLOCAL 2>/dev/null || true)"
    if [ -z "${LINKLOCAL_RULES}" ]; then
      log_error "Chain BRAINSOS-LINKLOCAL does not exist or is empty."
      exit 1
    fi
    LINKLOCAL_LAST="$(printf '%s\n' "${LINKLOCAL_RULES}" | tail -n 1)"
    if [ "${LINKLOCAL_LAST}" != "-A BRAINSOS-LINKLOCAL -d 169.254.0.0/16 -j DROP" ]; then
      log_error "Chain BRAINSOS-LINKLOCAL must end with -d 169.254.0.0/16 -j DROP (last rule: ${LINKLOCAL_LAST})."
      exit 1
    fi
    for ip in "${ALLOWED_IMDS_IPS[@]+"${ALLOWED_IMDS_IPS[@]}"}"; do
      if [ -n "${ip}" ]; then
        if ! iptables -C BRAINSOS-LINKLOCAL -s "${ip}/32" -d 169.254.169.254/32 -j RETURN 2>/dev/null; then
          log_error "Chain BRAINSOS-LINKLOCAL missing IMDS RETURN rule for authorized IP ${ip}/32."
          exit 1
        fi
      fi
    done
    for br in "${LINKLOCAL_BRIDGES[@]+"${LINKLOCAL_BRIDGES[@]}"}"; do
      [ -n "${br}" ] || continue
      if ! linklocal_jump_is_valid "${br}"; then
        log_error "DOCKER-USER missing or misordered BRAINSOS-LINKLOCAL jump for bridge '${br}'."
        exit 1
      fi
    done

    if command -v ip6tables >/dev/null 2>&1 && ip6tables -L DOCKER-USER >/dev/null 2>&1; then
      if ! ip6tables -C DOCKER-USER -d fd00:ec2::254/128 -j BRAINSOS-IMDS6 2>/dev/null; then
        log_error "DOCKER-USER IPv6 jump to BRAINSOS-IMDS6 is missing."
        exit 1
      fi
      if ! ip6tables -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS6 2>/dev/null; then
        log_error "DOCKER-USER IPv6 jump to BRAINSOS-EGRESS6 is missing."
        exit 1
      fi
      if ! check_docker_user_order ip6tables "fd00:ec2::254/128" BRAINSOS-IMDS6 BRAINSOS-EGRESS6; then
        exit 1
      fi
      IMDS6_RULES="$(ip6tables -S BRAINSOS-IMDS6 2>/dev/null | grep '^-A BRAINSOS-IMDS6 ' || true)"
      if [ -z "${IMDS6_RULES}" ]; then
        log_error "Chain BRAINSOS-IMDS6 does not exist or is empty."
        exit 1
      fi
      IMDS6_LAST="$(printf '%s\n' "${IMDS6_RULES}" | tail -n 1)"
      if [ "${IMDS6_LAST}" != "-A BRAINSOS-IMDS6 -j DROP" ]; then
        log_error "Chain BRAINSOS-IMDS6 does not end with -j DROP (last rule: ${IMDS6_LAST})."
        exit 1
      fi
      if grep -qE -- '-j (ACCEPT|RETURN)([[:space:]]|$)' <<<"${IMDS6_RULES}"; then
        log_error "Chain BRAINSOS-IMDS6 must not contain ACCEPT or RETURN rules."
        exit 1
      fi
      EGRESS6_RULES="$(ip6tables -S BRAINSOS-EGRESS6 2>/dev/null | grep '^-A BRAINSOS-EGRESS6 ' || true)"
      if [ -z "${EGRESS6_RULES}" ]; then
        log_error "Chain BRAINSOS-EGRESS6 does not exist or is empty."
        exit 1
      fi
      EGRESS6_LAST="$(printf '%s\n' "${EGRESS6_RULES}" | tail -n 1)"
      if [ "${EGRESS6_LAST}" != "-A BRAINSOS-EGRESS6 -j DROP" ]; then
        log_error "Chain BRAINSOS-EGRESS6 does not end with -j DROP (last rule: ${EGRESS6_LAST})."
        exit 1
      fi
      if grep -qE -- '-j ACCEPT([[:space:]]|$)' <<<"${EGRESS6_RULES}"; then
        log_error "Chain BRAINSOS-EGRESS6 must not contain ACCEPT rules."
        exit 1
      fi
      while IFS= read -r rule; do
        if [[ "${rule}" =~ -j[[:space:]]+RETURN([[:space:]]|$) ]]; then
          if [ "${rule}" != "-A BRAINSOS-EGRESS6 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN" ] \
            && [ "${rule}" != "-A BRAINSOS-EGRESS6 -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN" ] \
            && [ "${rule}" != "-A BRAINSOS-EGRESS6 -o ${INTERNAL_BRIDGE} -j RETURN" ]; then
            log_error "Chain BRAINSOS-EGRESS6 contains unexpected RETURN rule: ${rule}."
            exit 1
          fi
        fi
      done <<<"${EGRESS6_RULES}"
      if ! ip6tables -C BRAINSOS-EGRESS6 -o "${INTERNAL_BRIDGE}" -j RETURN 2>/dev/null; then
        log_error "Chain BRAINSOS-EGRESS6 missing intra-plane RETURN for ${INTERNAL_BRIDGE}."
        exit 1
      fi
    fi
    log_success "IMDS & WAN egress guards verified (${#ALLOWED_IMDS_IPS[@]} IMDS IP(s), ${INTERNAL_BRIDGE} gated via tool-egress-proxy:8082, ${#LINKLOCAL_BRIDGES[@]} bridge(s) protected by BRAINSOS-LINKLOCAL)."
    ;;

  remove)
    log_info "Removing IMDS & WAN egress container isolation guards..."
    if [ "${DRY_RUN}" = true ]; then
      run_ipt -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS
      run_ipt -F BRAINSOS-IMDS
      run_ipt -X BRAINSOS-IMDS
      run_ipt -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS
      run_ipt -F BRAINSOS-EGRESS
      run_ipt -X BRAINSOS-EGRESS
      for br in "${LINKLOCAL_BRIDGES[@]+"${LINKLOCAL_BRIDGES[@]}"}"; do
        [ -n "${br}" ] && run_ipt -D DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL
      done
      run_ipt -F BRAINSOS-LINKLOCAL
      run_ipt -X BRAINSOS-LINKLOCAL
      run_ip6t -D DOCKER-USER -d fd00:ec2::254/128 -j BRAINSOS-IMDS6
      run_ip6t -F BRAINSOS-IMDS6
      run_ip6t -X BRAINSOS-IMDS6
      run_ip6t -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS6
      run_ip6t -F BRAINSOS-EGRESS6
      run_ip6t -X BRAINSOS-EGRESS6
    else
      while iptables -C DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null; do
        iptables -D DOCKER-USER -d 169.254.169.254/32 -j BRAINSOS-IMDS 2>/dev/null || break
      done
      iptables -F BRAINSOS-IMDS 2>/dev/null || true
      iptables -X BRAINSOS-IMDS 2>/dev/null || true
      while iptables -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS 2>/dev/null; do
        iptables -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS 2>/dev/null || break
      done
      iptables -F BRAINSOS-EGRESS 2>/dev/null || true
      iptables -X BRAINSOS-EGRESS 2>/dev/null || true
      for br in "${LINKLOCAL_BRIDGES[@]+"${LINKLOCAL_BRIDGES[@]}"}"; do
        [ -n "${br}" ] || continue
        while iptables -C DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null; do
          iptables -D DOCKER-USER -i "${br}" -d 169.254.0.0/16 -j BRAINSOS-LINKLOCAL 2>/dev/null || break
        done
      done
      iptables -F BRAINSOS-LINKLOCAL 2>/dev/null || true
      iptables -X BRAINSOS-LINKLOCAL 2>/dev/null || true
      if command -v ip6tables >/dev/null 2>&1; then
        while ip6tables -C DOCKER-USER -d fd00:ec2::254/128 -j BRAINSOS-IMDS6 2>/dev/null; do
          ip6tables -D DOCKER-USER -d fd00:ec2::254/128 -j BRAINSOS-IMDS6 2>/dev/null || break
        done
        ip6tables -F BRAINSOS-IMDS6 2>/dev/null || true
        ip6tables -X BRAINSOS-IMDS6 2>/dev/null || true
        while ip6tables -C DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS6 2>/dev/null; do
          ip6tables -D DOCKER-USER -i "${INTERNAL_BRIDGE}" -j BRAINSOS-EGRESS6 2>/dev/null || break
        done
        ip6tables -F BRAINSOS-EGRESS6 2>/dev/null || true
        ip6tables -X BRAINSOS-EGRESS6 2>/dev/null || true
      fi
    fi
    log_success "IMDS & WAN egress guards removed."
    ;;
esac

