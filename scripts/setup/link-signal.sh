#!/usr/bin/env bash
# ==============================================================================
# Project Titan: Signal Operator Onboarding & Device Linking
# Script-first operational onboarding for Signal Private Operator Backchannel
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ANSI Color formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ------------------------------------------------------------------------------
# 0. Rule 13 Precondition: Mandatory .env check
# ------------------------------------------------------------------------------
if [ ! -f "${REPO_ROOT}/.env" ]; then
    log_error "Precondition Failed (Rule 13): No .env file present in repository root."
    log_error "This host is strictly an unconfigured repository clone. Execution halted."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a

SIGNAL_CONTAINER="titan-net-signal-cli"
HERMES_CONTAINER="titan-agent-terrastella"
COMMS_DIR="${TITAN_COMMS_DIR:-${REPO_ROOT}/data/comms}"
if [ -d "${COMMS_DIR}/signal" ] || [ ! -d "${TITAN_WORKSPACE_DIR:-${REPO_ROOT}/data/workspace}/signal" ]; then
    SIGNAL_STORAGE="${COMMS_DIR}/signal"
else
    SIGNAL_STORAGE="${TITAN_WORKSPACE_DIR:-${REPO_ROOT}/data/workspace}/signal"
fi

# ------------------------------------------------------------------------------
# 1. Prerequisite & Permission Validation
# ------------------------------------------------------------------------------
check_prerequisites() {
    log_info "Validating runtime prerequisites..."
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed or not in PATH."
        exit 1
    fi

    # Ensure storage directory exists with UID 1000:1000 permissions (Rule 1 & Rule 8)
    mkdir -p "${SIGNAL_STORAGE}"
    chmod 775 "${SIGNAL_STORAGE}" 2>/dev/null || true

    # Ensure signal-cli container is running
    if ! docker ps --filter "name=${SIGNAL_CONTAINER}" --filter "status=running" --format '{{.Names}}' | grep -q "${SIGNAL_CONTAINER}"; then
        log_warn "Signal daemon (${SIGNAL_CONTAINER}) is not running. Starting service..."
        (cd "${REPO_ROOT}" && docker compose up -d signal-cli)
        sleep 4
    fi

    # Verify daemon health
    DAEMON_ABOUT=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/about 2>/dev/null || echo "failed")
    if ! echo "${DAEMON_ABOUT}" | grep -q "json-rpc"; then
        log_error "Failed to reach Signal daemon API on 127.0.0.1:8080 (Got: ${DAEMON_ABOUT})"
        exit 1
    fi
    log_success "Signal daemon verified running and healthy."
}

# ------------------------------------------------------------------------------
# 2. Terminal QR Code Renderer
# ------------------------------------------------------------------------------
render_qr() {
    local uri="$1"

    echo ""
    echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}${BOLD}         SIGNAL OPERATOR ONBOARDING: SCAN QR CODE TO LINK            ${NC}"
    echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "1. Open the ${BOLD}Signal app${NC} on your primary mobile phone."
    echo -e "2. Navigate to: ${BOLD}Settings${NC} → ${BOLD}Linked Devices${NC} → ${BOLD}Link New Device${NC} (or '+' button)."
    echo -e "3. Point your camera at the QR code below:"
    echo ""

    local qr_rendered=false

    # Try rendering via Hermes container's built-in qrcode library
    if docker ps --filter "name=${HERMES_CONTAINER}" --filter "status=running" --format '{{.Names}}' | grep -q "${HERMES_CONTAINER}"; then
        if docker exec "${HERMES_CONTAINER}" /opt/hermes/.venv/bin/python3 -c "import qrcode; qr = qrcode.QRCode(); qr.add_data('${uri}'); qr.print_ascii(invert=True)" 2>/dev/null; then
            qr_rendered=true
        fi
    fi

    # Fallback to host python if qrcode is installed
    if [ "${qr_rendered}" = false ]; then
        if python3 -c "import qrcode; qr = qrcode.QRCode(); qr.add_data('${uri}'); qr.print_ascii(invert=True)" 2>/dev/null; then
            qr_rendered=true
        fi
    fi

    # If terminal ASCII rendering failed, output raw URI and instruction
    if [ "${qr_rendered}" = false ]; then
        log_warn "Terminal ASCII QR code rendering unavailable."
        echo ""
        echo -e "Raw Device Link URI: ${BOLD}${uri}${NC}"
        echo ""
        echo "You can generate a QR image by viewing in a browser or using qrencode:"
        echo "  qrencode -t ANSIUTF8 '${uri}'"
    fi

    echo ""
    echo -e "${YELLOW}Waiting for device linking confirmation (timeout: 90 seconds)...${NC}"
}

# ------------------------------------------------------------------------------
# 3. Status Query
# ------------------------------------------------------------------------------
cmd_status() {
    check_prerequisites
    echo ""
    echo -e "${BOLD}Project Titan: Signal Messaging Gateway Status${NC}"
    echo "--------------------------------------------------------"

    ABOUT_JSON=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/about)
    ACCOUNTS_JSON=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/accounts)

    echo -e "Daemon Health:      ${GREEN}OK${NC}"
    echo -e "API Capabilities:   $(echo "${ABOUT_JSON}" | grep -o '"mode":"[^"]*"' | tr -d '"')"
    echo -e "Session Path:       ${SIGNAL_STORAGE}"
    echo -e "Registered Accounts:"

    # Parse JSON accounts array
    ACCOUNT_COUNT=$(echo "${ACCOUNTS_JSON}" | grep -c '"+' 2>/dev/null || echo "0")
    ACCOUNT_COUNT="$(echo "${ACCOUNT_COUNT}" | tr -d '[:space:]')"
    if [ "${ACCOUNT_COUNT}" = "0" ] || [ "${ACCOUNTS_JSON}" = "[]" ] || [ -z "${ACCOUNTS_JSON}" ]; then
        echo -e "  ${YELLOW}No registered or linked Signal accounts found.${NC}"
        echo "  Run './scripts/setup/link-signal.sh --link' to link your Signal app."
    else
        echo "${ACCOUNTS_JSON}" | grep -o '"+[^"]*"' | tr -d '"' | while IFS= read -r acc; do
            echo -e "  - ${GREEN}${acc}${NC} (Active)"
        done
    fi

    echo ""
    echo -e "Current .env Configuration:"
    echo "  SIGNAL_ACCOUNT       = ${SIGNAL_ACCOUNT:-<unset>}"
    echo "  SIGNAL_ALLOWED_USERS = ${SIGNAL_ALLOWED_USERS:-<unset>}"
    echo "--------------------------------------------------------"
}

# ------------------------------------------------------------------------------
# 4. QR Device Linking Mode
# ------------------------------------------------------------------------------
cmd_link() {
    local device_name="${1:-${DEFAULT_DEVICE_NAME}}"
    check_prerequisites

    log_info "Initiating QR device linking session for '${device_name}'..."

    # Get baseline accounts
    BASELINE_ACCOUNTS=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/accounts 2>/dev/null || echo "[]")

    # Request linking URI from signal-cli-rest-api
    LINK_RESP=$(docker exec "${SIGNAL_CONTAINER}" curl -s "http://127.0.0.1:8080/v1/qrcodelink/raw?device_name=${device_name}")
    LINK_URI=$(echo "${LINK_RESP}" | grep -o '"device_link_uri":"[^"]*"' | cut -d '"' -f 4 || true)

    if [ -z "${LINK_URI}" ]; then
        log_error "Failed to retrieve device link URI from daemon: ${LINK_RESP}"
        exit 1
    fi

    render_qr "${LINK_URI}"

    # Poll /v1/accounts for completion
    local elapsed=0
    local poll_interval=3
    local timeout=90
    local linked_account=""

    while [ "${elapsed}" -lt "${timeout}" ]; do
        sleep "${poll_interval}"
        elapsed=$((elapsed + poll_interval))

        CURRENT_ACCOUNTS=$(docker exec "${SIGNAL_CONTAINER}" curl -s http://127.0.0.1:8080/v1/accounts 2>/dev/null || echo "[]")
        if [ "${CURRENT_ACCOUNTS}" != "${BASELINE_ACCOUNTS}" ] && [ "${CURRENT_ACCOUNTS}" != "[]" ]; then
            # Extract newly added account
            linked_account=$(echo "${CURRENT_ACCOUNTS}" | grep -o '"+[^"]*"' | tail -n 1 | tr -d '"')
            break
        fi
        echo -n "."
    done
    echo ""

    if [ -n "${linked_account}" ]; then
        log_success "Device linked successfully! Linked account: ${BOLD}${linked_account}${NC}"
        echo ""
        update_env_prompt "${linked_account}"
    else
        log_warn "Device linking timed out after ${timeout} seconds."
        log_info "If the link request expired in your app, re-run: ./scripts/setup/link-signal.sh --link"
        exit 1
    fi
}

# ------------------------------------------------------------------------------
# 5. SMS / Voice Registration Mode
# ------------------------------------------------------------------------------
cmd_register() {
    local phone="$1"
    local use_voice="${2:-false}"
    check_prerequisites

    if [ -z "${phone}" ]; then
        log_error "Phone number must be specified in E.164 format (e.g. +15551234567)."
        exit 1
    fi

    log_info "Initiating registration for ${phone} (voice: ${use_voice})..."
    local voice_flag="false"
    if [ "${use_voice}" = "true" ]; then
        voice_flag="true"
    fi

    REG_RESP=$(docker exec "${SIGNAL_CONTAINER}" curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"use_voice\": ${voice_flag}}" \
        "http://127.0.0.1:8080/v1/register/${phone}")

    log_info "Server response: ${REG_RESP}"
    log_info "Please check your device for the SMS or voice verification code."
    echo ""
    echo "To verify, run:"
    echo "  ./scripts/setup/link-signal.sh --verify ${phone} <VERIFICATION_CODE>"
}

cmd_verify() {
    local phone="$1"
    local code="$2"
    check_prerequisites

    if [ -z "${phone}" ] || [ -z "${code}" ]; then
        log_error "Usage: ./scripts/setup/link-signal.sh --verify <phone_number> <verification_code>"
        exit 1
    fi

    log_info "Submitting verification code for ${phone}..."
    VERIFY_RESP=$(docker exec "${SIGNAL_CONTAINER}" curl -s -X POST \
        -H "Content-Type: application/json" \
        "http://127.0.0.1:8080/v1/register/${phone}/verify/${code}")

    if echo "${VERIFY_RESP}" | grep -qi "error"; then
        log_error "Verification failed: ${VERIFY_RESP}"
        exit 1
    fi

    log_success "Account verified and registered successfully!"
    update_env_prompt "${phone}"
}

# ------------------------------------------------------------------------------
# Helper: Prompt to update .env
# ------------------------------------------------------------------------------
update_env_prompt() {
    local account="$1"
    log_info "Active Signal Account: ${account}"

    if grep -q "^SIGNAL_ACCOUNT=" "${REPO_ROOT}/.env"; then
        sed -i "s|^SIGNAL_ACCOUNT=.*|SIGNAL_ACCOUNT=${account}|" "${REPO_ROOT}/.env"
        log_success "Updated SIGNAL_ACCOUNT=${account} in .env"
    fi

    if grep -q "^SIGNAL_ALLOWED_USERS=" "${REPO_ROOT}/.env"; then
        CURRENT_ALLOWED=$(grep "^SIGNAL_ALLOWED_USERS=" "${REPO_ROOT}/.env" | cut -d '=' -f 2-)
        if [ -z "${CURRENT_ALLOWED}" ]; then
            sed -i "s|^SIGNAL_ALLOWED_USERS=.*|SIGNAL_ALLOWED_USERS=${account}|" "${REPO_ROOT}/.env"
            log_success "Configured strict operator whitelisting in .env: SIGNAL_ALLOWED_USERS=${account}"
        fi
    fi

    log_info "Synchronizing fleet configurations..."
    "${REPO_ROOT}/scripts/control/sync-agents.sh"
}

# ------------------------------------------------------------------------------
# CLI Dispatcher
# ------------------------------------------------------------------------------
show_help() {
    echo "Usage: ./scripts/setup/link-signal.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --link [device_name]          Generate QR code and link existing Signal mobile app (Default)"
    echo "  --register <phone> [--voice]  Initiate new phone registration via SMS or voice call"
    echo "  --verify <phone> <code>       Verify phone registration with received code"
    echo "  --status                      Query and display registered accounts and daemon status"
    echo "  --help                        Display this help dialog"
    echo ""
    echo "Examples:"
    echo "  ./scripts/setup/link-signal.sh --link Titan-Operator"
    echo "  ./scripts/setup/link-signal.sh --status"
    echo "  ./scripts/setup/link-signal.sh --register +15551234567"
    echo "  ./scripts/setup/link-signal.sh --verify +15551234567 123-456"
}

MODE="${1:---link}"
case "${MODE}" in
    --link)
        cmd_link "${2:-${DEFAULT_DEVICE_NAME}}"
        ;;
    --register)
        cmd_register "${2:-}" "${3:-false}"
        ;;
    --verify)
        cmd_verify "${2:-}" "${3:-}"
        ;;
    --status|--list)
        cmd_status
        ;;
    --help|-h)
        show_help
        ;;
    *)
        log_error "Unknown option: ${MODE}"
        show_help
        exit 1
        ;;
esac
