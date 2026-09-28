#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Dovecot Pigeonhole Sieve Inbound Agent Webhook Dispatcher
# Piped by Dovecot LMTP on inbound email delivery to wake fleet agents reactively.
# Zero polling, zero token waste, pure push-based doorbell wake-up.
# ==============================================================================
set -e

# Read piped email from stdin
EMAIL_RAW="$(cat)"

# Source environment variables if available
if [ -f /etc/environment ]; then
    set -a
    . /etc/environment
    set +a
fi

# 1. Determine recipient from $1 (Sieve envelope argument) or fallback to To header
RECIPIENT_ARG="${1:-}"

# Parse headers and body using python3 if available, else awk/sed fallback
if command -v python3 >/dev/null 2>&1; then
    PARSED_JSON="$(python3 -c '
import sys, json, email
from email.header import decode_header

raw = sys.stdin.read()
msg = email.message_from_string(raw)

def decode_val(val):
    if not val:
        return ""
    parts = decode_header(val)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded).strip()

def get_body(message):
    body = ""
    try:
        if message.is_multipart():
            for part in message.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition", ""))
                if ctype == "text/plain" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                        break
            if not body:
                for part in message.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
        else:
            payload = message.get_payload(decode=True)
            if payload:
                body = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
            else:
                body = str(message.get_payload() or "")
    except Exception:
        body = ""
    return body.strip()

data = {
    "to": decode_val(msg.get("To", "")),
    "from": decode_val(msg.get("From", "")),
    "subject": decode_val(msg.get("Subject", "")),
    "message_id": decode_val(msg.get("Message-ID", "")),
    "in_reply_to": decode_val(msg.get("In-Reply-To", "")),
    "references": decode_val(msg.get("References", "")),
    "date": decode_val(msg.get("Date", "")),
    "body": get_body(msg),
}
print(json.dumps(data))
' <<< "$EMAIL_RAW" 2>/dev/null || true)"
fi

if [ -z "${PARSED_JSON:-}" ]; then
    # Pure bash/sed fallback
    EXTRACT_HDR() {
        echo "$EMAIL_RAW" | grep -i "^$1:" | head -n 1 | sed -e "s/^$1:[ \t]*//I" | tr -d '\r\n'
    }
    TO_HDR="$(EXTRACT_HDR "To")"
    FROM_HDR="$(EXTRACT_HDR "From")"
    SUBJ_HDR="$(EXTRACT_HDR "Subject")"
    MSG_ID_HDR="$(EXTRACT_HDR "Message-ID")"
    IN_REPLY_HDR="$(EXTRACT_HDR "In-Reply-To")"
    DATE_HDR="$(EXTRACT_HDR "Date")"

    # Escape JSON strings
    JSON_ESC() {
        printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g'
    }

    PARSED_JSON=$(cat <<EOF
{
  "to": "$(JSON_ESC "$TO_HDR")",
  "from": "$(JSON_ESC "$FROM_HDR")",
  "subject": "$(JSON_ESC "$SUBJ_HDR")",
  "message_id": "$(JSON_ESC "$MSG_ID_HDR")",
  "in_reply_to": "$(JSON_ESC "$IN_REPLY_HDR")",
  "references": "",
  "date": "$(JSON_ESC "$DATE_HDR")"
}
EOF
)
fi

# Determine effective recipient address
TARGET_TO="${RECIPIENT_ARG}"
if [ -z "${TARGET_TO}" ]; then
    TARGET_TO="$(echo "$PARSED_JSON" | grep -o '"to": *"[^"]*"' | head -n 1 | cut -d'"' -f4 || true)"
fi

# Extract mailbox username before @ (e.g. terrastella@brainsos.local -> terrastella)
AGENT_NAME="$(echo "${TARGET_TO}" | cut -d@ -f1 | tr '[:upper:]' '[:lower:]' | tr -d ' ')"

# Only trigger for known autonomous fleet agents or configured recipients
case "${AGENT_NAME}" in
    terrastella)
        AGENT_PORT="${BRAINSOS_AGENT_PORT_TERRASTELLA:-8642}"
        AGENT_KEY="${HERMES_API_TERRASTELLA_KEY:-}"
        ;;
    marvin)
        AGENT_PORT="${BRAINSOS_AGENT_PORT_MARVIN:-8643}"
        AGENT_KEY="${HERMES_API_MARVIN_KEY:-}"
        ;;
    bawtford|cindy-pawford)
        AGENT_NAME="bawtford"
        AGENT_PORT="${BRAINSOS_AGENT_PORT_BAWTFORD:-8644}"
        AGENT_KEY="${HERMES_API_BAWTFORD_KEY:-}"
        ;;
    *)
        # Not a recognized fleet agent mailbox (e.g. admin or operator) - skip webhook dispatch cleanly
        echo "[BRAINSOS-SIEVE-PIPE] Non-agent delivery to '${TARGET_TO}' (user: '${AGENT_NAME}'). Skipping webhook."
        exit 0
        ;;
esac

# Allow environment overrides for agent host / target URL
AGENT_HOST="${BRAINSOS_AGENT_HOST:-brainsos-agent-${AGENT_NAME}}"
WEBHOOK_URL="${AGENT_WEBHOOK_URL:-http://${AGENT_HOST}:${AGENT_PORT}/webhook}"

echo "[BRAINSOS-SIEVE-PIPE] Inbound email for '${AGENT_NAME}' -> Dispatching push webhook to ${WEBHOOK_URL}..."

AUTH_HEADER=()
if [ -n "${AGENT_KEY}" ]; then
    AUTH_HEADER=(-H "Authorization: Bearer ${AGENT_KEY}")
fi

# Deliver webhook with 5s connect timeout and 10s max execution time
HTTP_STATUS=$(curl -s -o /tmp/webhook_response.txt -w "%{http_code}" \
    -X POST \
    -H "Content-Type: application/json" \
    "${AUTH_HEADER[@]}" \
    -H "X-BrainsOS-Event: inbound-email" \
    -d "${PARSED_JSON}" \
    --connect-timeout 5 \
    --max-time 10 \
    "${WEBHOOK_URL}" || echo "failed")

echo "[BRAINSOS-SIEVE-PIPE] Webhook dispatched to ${WEBHOOK_URL} (HTTP Status: ${HTTP_STATUS})"

# Always exit 0 so Dovecot LMTP delivery to the user Maildir completes successfully
exit 0
