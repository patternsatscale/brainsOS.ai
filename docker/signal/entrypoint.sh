#!/bin/sh
set -e

# brainsOS: Signal Gateway Unified Entrypoint
# Multiplexes native signal-cli HTTP/JSON-RPC (8082) & REST API (8084) onto 8080.

SIGNAL_CLI_CONFIG_DIR="${SIGNAL_CLI_CONFIG_DIR:-/home/.local/share/signal-cli}"
SIGNAL_CLI_UID="${SIGNAL_CLI_UID:-1000}"
SIGNAL_CLI_GID="${SIGNAL_CLI_GID:-1000}"
SIGNAL_NATIVE_HTTP_PORT="${SIGNAL_NATIVE_HTTP_PORT:-8082}"
SIGNAL_REST_API_PORT="${SIGNAL_REST_API_PORT:-8084}"
PROXY_PORT="${PORT:-8080}"

export SIGNAL_CLI_CONFIG_DIR
export SIGNAL_NATIVE_HTTP_PORT
export SIGNAL_REST_API_PORT
export PORT="${PROXY_PORT}"

mkdir -p "${SIGNAL_CLI_CONFIG_DIR}" 2>/dev/null || true

if [ "$(id -u)" -eq 0 ]; then
    usermod -u "${SIGNAL_CLI_UID}" signal-api 2>/dev/null || true
    groupmod -o -g "${SIGNAL_CLI_GID}" signal-api 2>/dev/null || true
    if [ "${SIGNAL_CLI_CHOWN_ON_STARTUP}" != "false" ]; then
        chown -R "${SIGNAL_CLI_UID}:${SIGNAL_CLI_GID}" "${SIGNAL_CLI_CONFIG_DIR}" 2>/dev/null || true
    fi
fi

cap_prefix="-cap_"
caps="$cap_prefix$(seq -s ",$cap_prefix" 0 $(cat /proc/sys/kernel/cap_last_cap 2>/dev/null || echo 40))"

DAEMON_PID=""
# Initialize jsonrpc2 configuration for signal-cli
if [ "$MODE" = "json-rpc" ] || [ "$MODE" = "json-rpc-native" ]; then
    CONF_FILE="/etc/supervisor/conf.d/signal-cli-json-rpc-1.conf"
    if [ -d "/etc/supervisor/conf.d" ] && [ "$(id -u)" -eq 0 ]; then
        /usr/bin/jsonrpc2-helper || true
        if [ -f "${CONF_FILE}" ]; then
            sed -i "s|daemon  --tcp 127.0.0.1:6001.*|daemon  --tcp 127.0.0.1:6001 --http 127.0.0.1:${SIGNAL_NATIVE_HTTP_PORT}|" "${CONF_FILE}"
            sed -i "s|daemon --tcp 127.0.0.1:6001.*|daemon --tcp 127.0.0.1:6001 --http 127.0.0.1:${SIGNAL_NATIVE_HTTP_PORT}|" "${CONF_FILE}"
        fi
        if [ -n "$JAVA_OPTS" ]; then
            echo "export JAVA_OPTS='$JAVA_OPTS'" >> /etc/default/supervisor
        fi
        service supervisor start
        supervisorctl start all || true
    else
        # s6-overlay / rootless upstream image (bbernhard/signal-cli-rest-api >= 0.100):
        # jsonrpc2-helper runs signal-cli daemon in the foreground, so we write jsonrpc2.yml
        # and launch signal-cli daemon in the background with both --tcp and --http enabled.
        if [ ! -f "${SIGNAL_CLI_CONFIG_DIR}/jsonrpc2.yml" ]; then
            cat <<EOF > "${SIGNAL_CLI_CONFIG_DIR}/jsonrpc2.yml"
config:
  <multi-account>:
    tcp_port: 6001
EOF
        fi
        SIGNAL_BIN="/usr/bin/signal-cli"
        if [ "$MODE" = "json-rpc-native" ] && [ -x "/usr/bin/signal-cli-native" ]; then
            SIGNAL_BIN="/usr/bin/signal-cli-native"
        fi
        "${SIGNAL_BIN}" --config "${SIGNAL_CLI_CONFIG_DIR}" daemon \
            --tcp 127.0.0.1:6001 \
            --http "127.0.0.1:${SIGNAL_NATIVE_HTTP_PORT}" &
        DAEMON_PID=$!
    fi
fi

# Launch signal-cli-rest-api on dedicated REST port (8084)
export PORT="${SIGNAL_REST_API_PORT}"
if [ "$(id -u)" -eq 0 ]; then
    setpriv --reuid="${SIGNAL_CLI_UID}" --regid="${SIGNAL_CLI_GID}" --init-groups --inh-caps=$caps \
        signal-cli-rest-api -signal-cli-config="${SIGNAL_CLI_CONFIG_DIR}" &
else
    signal-cli-rest-api -signal-cli-config="${SIGNAL_CLI_CONFIG_DIR}" &
fi
REST_PID=$!

_cleanup() {
    echo "[signal-entrypoint] Shutting down services..."
    kill -TERM "${REST_PID}" 2>/dev/null || true
    [ -n "${DAEMON_PID}" ] && kill -TERM "${DAEMON_PID}" 2>/dev/null || true
    [ "$(id -u)" -eq 0 ] && service supervisor stop 2>/dev/null || true
    exit 0
}

trap _cleanup TERM INT QUIT

# Launch gateway reverse proxy on canonical external port (8080)
PORT="${PROXY_PORT}" python3 /usr/local/bin/gateway_proxy.py &
PROXY_PID=$!

wait "${PROXY_PID}"
