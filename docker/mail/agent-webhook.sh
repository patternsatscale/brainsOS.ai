#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Dovecot Pigeonhole Sieve Non-Blocking Inbound Mail Spooler & Streamer
# Piped by Dovecot LMTP on inbound delivery.
# Spools raw RFC 822 stream to disk and streams directly to control plane ingress.
# ==============================================================================
set -e

# Source environment variables if available
if [ -f /etc/environment ]; then
    set -a
    . /etc/environment
    set +a
fi

SPOOL_DIR="${BRAINSOS_SPOOL_DIR:-/var/spool/brainsos/inbound}"
mkdir -p "${SPOOL_DIR}" 2>/dev/null || true

# 1. Zero-Loss Spooler: Write raw RFC 822 stream from stdin to disk atomically
TMP_FILE="$(mktemp -p "${SPOOL_DIR}" -t "$(date +%s)_XXXXXX")"
cat > "${TMP_FILE}"
chmod 664 "${TMP_FILE}" 2>/dev/null || chmod 644 "${TMP_FILE}" 2>/dev/null || true
SPOOL_FILE="${TMP_FILE}.eml"
mv "${TMP_FILE}" "${SPOOL_FILE}"

# 2. HTTP Streaming: Forward stream to control plane ingress endpoint
INGRESS_URL="${BRAINSOS_INGRESS_URL:-http://control-plane:8000/api/v1/mail/inbound}"

HEADERS=(--header "Content-Type: message/rfc822")
if [ -n "${1:-}" ]; then
    HEADERS+=(--header "X-Envelope-To: ${1}")
fi
HEADERS+=(--header "X-Spool-Filename: $(basename "${SPOOL_FILE}")")


curl -sS -X POST "${INGRESS_URL}" \
    "${HEADERS[@]}" \
    --data-binary @"${SPOOL_FILE}" \
    --max-time 3 >/dev/null 2>&1 || true

# 3. Clean exit: Guarantee exit code 0 so Dovecot LMTP delivers to Maildir without deferral
exit 0
