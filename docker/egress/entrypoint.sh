#!/usr/bin/env bash
set -euo pipefail

# Fail closed at container startup when proxy auth is required (default true)
# and neither TOOL_EGRESS_PROXY_SECRET nor TOOL_EGRESS_PROXY_TOKENS is configured.
_req_auth="$(printf '%s' "${TOOL_EGRESS_REQUIRE_PROXY_AUTH:-true}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
if [ "${_req_auth}" = "1" ] || [ "${_req_auth}" = "true" ] || [ "${_req_auth}" = "yes" ]; then
  if [ -z "${TOOL_EGRESS_PROXY_SECRET:-}" ] && [ -z "${TOOL_EGRESS_PROXY_TOKENS:-}" ]; then
    echo "[ERROR] TOOL_EGRESS_REQUIRE_PROXY_AUTH is enabled but TOOL_EGRESS_PROXY_SECRET and TOOL_EGRESS_PROXY_TOKENS are empty; refusing to start egress proxy fail-open." >&2
    exit 1
  fi
fi

# Determine runtime UID/GID matching mitmproxy's /usr/local/bin/docker-entrypoint.sh usermod logic
MITMPROXY_PATH="/home/mitmproxy/.mitmproxy"
if [ -f "${MITMPROXY_PATH}/mitmproxy-ca.pem" ]; then
  _owner_ref="${MITMPROXY_PATH}/mitmproxy-ca.pem"
else
  _owner_ref="${MITMPROXY_PATH}"
fi

# Generate mitmweb config outside the shared tool_egress_proxy_data volume
# so warm runners mounting /etc/ssl/mitmproxy:ro cannot read web_password.
mkdir -p /run/mitmproxy
chmod 0700 /run/mitmproxy

if [ -n "${TOOL_EGRESS_WEB_PASSWORD:-}" ]; then
  python3 - << 'EOF'
import json
import os

pw = os.environ.get("TOOL_EGRESS_WEB_PASSWORD", "")
if pw:
    val = pw
    try:
        import argon2  # type: ignore[import-not-found]
        if not pw.startswith("$argon2"):
            val = argon2.PasswordHasher().hash(pw)
    except ImportError:
        pass
    cfg_path = "/run/mitmproxy/config.yaml"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(f"web_password: {json.dumps(val)}\n")
    os.chmod(cfg_path, 0o600)
EOF
fi

if [ "$(id -u)" -eq 0 ] && [ -e "${_owner_ref}" ]; then
  _target_uid="$(stat -c '%u' "${_owner_ref}")"
  _target_gid="$(stat -c '%g' "${_owner_ref}")"
  chown -R "${_target_uid}:${_target_gid}" /run/mitmproxy
fi

unset TOOL_EGRESS_WEB_PASSWORD

exec /usr/local/bin/docker-entrypoint.sh "$@"
