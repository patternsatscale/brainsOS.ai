#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Caddy Internal Root CA Trust Utility
# Exports Caddy's local root CA certificate and installs it into host trust store
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source utility functions if available
if [ -f "${REPO_ROOT}/scripts/utils.sh" ]; then
  # shellcheck source=../../scripts/utils.sh
  source "${REPO_ROOT}/scripts/utils.sh"
else
  log_info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
  log_success() { echo -e "\033[1;32m[SUCCESS]\033[0m $*"; }
  log_warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
  log_error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }
fi

# Source .env if present
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  . "${REPO_ROOT}/.env"
  set +a
fi

TARGET_CERT_DIR="${BRAINSOS_CONTROL_PLANE_DIR:-${BRAINSOS_DATA_DIR:-${REPO_ROOT}/data}/control_plane}"
TARGET_CERT_FILE="${TARGET_CERT_DIR}/caddy_root.crt"
mkdir -p "${TARGET_CERT_DIR}"
if [ -d "${TARGET_CERT_FILE}" ]; then
  rm -rf "${TARGET_CERT_FILE}"
fi

log_info "Exporting Caddy internal root CA certificate from Docker volume..."

# Extract root.crt from Caddy container or caddy_data volume (with retry)
for attempt in 1 2 3 4 5; do
  if docker compose ps -q caddy >/dev/null 2>&1 && [ -n "$(docker compose ps -q caddy 2>/dev/null)" ]; then
    docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "${TARGET_CERT_FILE}" 2>/dev/null || true
  fi

  if [ ! -s "${TARGET_CERT_FILE}" ]; then
    # Fallback: run temporary lightweight container mounting brainsos_caddy_data volume
    docker run --rm -v brainsos_caddy_data:/data alpine cat /data/caddy/pki/authorities/local/root.crt > "${TARGET_CERT_FILE}" 2>/dev/null || true
  fi

  if [ -s "${TARGET_CERT_FILE}" ]; then
    break
  fi
  sleep 1
done

if [ ! -s "${TARGET_CERT_FILE}" ]; then
  log_error "Could not retrieve Caddy root CA certificate. Ensure Caddy container is initialized and running."
  exit 1
fi

chmod 644 "${TARGET_CERT_FILE}" 2>/dev/null || true
log_success "Exported Caddy root CA certificate to: ${TARGET_CERT_FILE}"

# Optional automatic installation into host system trust store
INSTALL_STORE=1
if [[ "${1:-}" == "--export-only" ]]; then
  INSTALL_STORE=0
fi

if [ ${INSTALL_STORE} -eq 1 ]; then
  OS_TYPE="$(uname -s)"
  if [ "${OS_TYPE}" = "Linux" ]; then
    if [ "$(id -u)" -ne 0 ]; then
      log_info "Installing to Linux system trust store requires sudo:"
      if command -v sudo >/dev/null 2>&1; then
        sudo cp "${TARGET_CERT_FILE}" /usr/local/share/ca-certificates/brainsos_caddy_root.crt
        sudo update-ca-certificates
        log_success "Installed Caddy root CA to /usr/local/share/ca-certificates and updated system trust store."
      else
        log_warn "sudo not available. Please run as root: cp ${TARGET_CERT_FILE} /usr/local/share/ca-certificates/ && update-ca-certificates"
      fi
    else
      cp "${TARGET_CERT_FILE}" /usr/local/share/ca-certificates/brainsos_caddy_root.crt
      update-ca-certificates
      log_success "Installed Caddy root CA and updated system trust store."
    fi
  elif [ "${OS_TYPE}" = "Darwin" ]; then
    if security verify-cert -c "${TARGET_CERT_FILE}" >/dev/null 2>&1; then
      log_success "Caddy root CA certificate is already trusted in macOS Keychain."
    else
      log_info "Caddy root CA certificate is not yet trusted in macOS Keychain."
      if [ "$(id -u)" -eq 0 ]; then
        security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "${TARGET_CERT_FILE}"
        log_success "Installed and trusted Caddy root CA in macOS System Keychain."
      elif sudo -n true 2>/dev/null; then
        sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "${TARGET_CERT_FILE}"
        log_success "Installed and trusted Caddy root CA in macOS System Keychain (via passwordless sudo)."
      elif [[ "${1:-}" == "--install" ]] && [ -t 0 ]; then
        log_info "Attempting to install into macOS System Keychain (sudo password required)..."
        if sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "${TARGET_CERT_FILE}"; then
          log_success "Successfully installed and trusted Caddy root CA in macOS System Keychain."
        else
          log_warn "Installation cancelled or failed."
          log_info "To trust Caddy's certificate system-wide for Chrome/Safari/VSCode Webviews, run:"
          echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain \"${TARGET_CERT_FILE}\""
        fi
      else
        log_info "To trust Caddy's certificate system-wide for Chrome/Safari/VSCode Webviews, run:"
        echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain \"${TARGET_CERT_FILE}\""
        echo "  (or run: make trust-ca)"
      fi
    fi
  fi
fi

log_info "Browser / Client Notice:"
echo "  - Google Chrome & Chromium browsers treat '*.localhost' as a secure context automatically (http://editor.localhost)."
echo "  - For HTTPS on '*.brainsos.local', import '${TARGET_CERT_FILE}' as an Authority / Trusted Root Certificate in your browser settings."
