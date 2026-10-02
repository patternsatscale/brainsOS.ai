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

usermod -u "${SIGNAL_CLI_UID}" signal-api 2>/dev/null || true
groupmod -o -g "${SIGNAL_CLI_GID}" signal-api 2>/dev/null || true

# Enforce host workspace permissions
if [ "${SIGNAL_CLI_CHOWN_ON_STARTUP}" != "false" ]; then
    mkdir -p "${SIGNAL_CLI_CONFIG_DIR}"
    chown -R "${SIGNAL_CLI_UID}:${SIGNAL_CLI_GID}" "${SIGNAL_CLI_CONFIG_DIR}"
fi

cap_prefix="-cap_"
caps="$cap_prefix$(seq -s ",$cap_prefix" 0 $(cat /proc/sys/kernel/cap_last_cap 2>/dev/null || echo 40))"

# Initialize jsonrpc2 configuration for signal-cli
if [ "$MODE" = "json-rpc" ] || [ "$MODE" = "json-rpc-native" ]; then
    /usr/bin/jsonrpc2-helper || true

    # Inject native HTTP daemon endpoint (--http 127.0.0.1:8082) into supervisor config
    CONF_FILE="/etc/supervisor/conf.d/signal-cli-json-rpc-1.conf"
    if [ -f "${CONF_FILE}" ]; then
        sed -i "s|daemon  --tcp 127.0.0.1:6001.*|daemon  --tcp 127.0.0.1:6001 --http 127.0.0.1:${SIGNAL_NATIVE_HTTP_PORT}|" "${CONF_FILE}"
        sed -i "s|daemon --tcp 127.0.0.1:6001.*|daemon --tcp 127.0.0.1:6001 --http 127.0.0.1:${SIGNAL_NATIVE_HTTP_PORT}|" "${CONF_FILE}"
    fi

    if [ -n "$JAVA_OPTS" ]; then
        echo "export JAVA_OPTS='$JAVA_OPTS'" >> /etc/default/supervisor
    fi

    service supervisor start
    supervisorctl start all || true
fi

# Launch signal-cli-rest-api on dedicated REST port (8084)
export PORT="${SIGNAL_REST_API_PORT}"
setpriv --reuid="${SIGNAL_CLI_UID}" --regid="${SIGNAL_CLI_GID}" --init-groups --inh-caps=$caps \
    signal-cli-rest-api -signal-cli-config="${SIGNAL_CLI_CONFIG_DIR}" &
REST_PID=$!

_cleanup() {
    echo "[signal-entrypoint] Shutting down services..."
    kill -TERM "${REST_PID}" 2>/dev/null || true
    service supervisor stop 2>/dev/null || true
    exit 0
}

trap _cleanup TERM INT QUIT

# Launch gateway reverse proxy on canonical external port (8080)
PORT="${PROXY_PORT}" python3 /usr/local/bin/gateway_proxy.py &
PROXY_PID=$!

wait "${PROXY_PID}"
