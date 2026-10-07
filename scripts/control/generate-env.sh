#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Interactive Environment & Credential Generator (generate-env.sh)
#
# Generates or updates .env with cryptographically secure random passwords,
# prompts for custom service URLs and domains (e.g. email / SOGo domain),
# and automatically rebuilds/reloads platform services.
# ==============================================================================

set -euo pipefail

# Terminal colors & styling
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
  _check_dir="${SCRIPT_DIR}"
  while [ "${_check_dir}" != "/" ] && [ -n "${_check_dir}" ]; do
    if [ -f "${_check_dir}/config/agents.yaml" ] || [ -f "${_check_dir}/config/default_settings/agents.yaml" ] || [ -d "${_check_dir}/.git" ]; then
      REPO_ROOT="${_check_dir}"
      break
    fi
    _check_dir="$(dirname "${_check_dir}")"
  done
  [ -z "${REPO_ROOT}" ] && REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
fi

cd "${REPO_ROOT}"

ENV_FILE="${REPO_ROOT}/.env"
EXAMPLE_FILE="${REPO_ROOT}/.env.example"

if [ ! -f "${EXAMPLE_FILE}" ]; then
  log_error "Template file .env.example not found at ${EXAMPLE_FILE}."
  exit 1
fi

# Options & defaults
NON_INTERACTIVE=false
REBUILD=true
FORCE_PASSWORDS=false
CUSTOM_DOMAIN=""
CUSTOM_MAIL_DOMAIN=""
CUSTOM_DATA_DIR=""

show_help() {
  echo -e "${BOLD}brainsOS Environment & Credential Generator${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  -y, --yes, --non-interactive, --defaults"
  echo "                        Run in non-interactive mode with default answers"
  echo "  --domain <domain>     Set base platform domain (e.g. brainsos.local)"
  echo "  --mail-domain <domain>"
  echo "                        Set custom email / SOGo URL (e.g. dev.local.brainsos.ai)"
  echo "  --data-dir <path>     Set runtime data directory (default: ./data)"
  echo "  --force-passwords     Regenerate all passwords even if custom ones exist"
  echo "  --no-rebuild          Skip rebuilding/restarting Docker services"
  echo "  -h, --help            Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes|--non-interactive|--defaults)
      NON_INTERACTIVE=true
      shift
      ;;
    --domain)
      CUSTOM_DOMAIN="$2"
      shift 2
      ;;
    --mail-domain)
      CUSTOM_MAIL_DOMAIN="$2"
      shift 2
      ;;
    --data-dir)
      CUSTOM_DATA_DIR="$2"
      shift 2
      ;;
    --force-passwords)
      FORCE_PASSWORDS=true
      shift
      ;;
    --rebuild)
      REBUILD=true
      shift
      ;;
    --no-rebuild)
      REBUILD=false
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

# If not running in a terminal, default to non-interactive mode
if [ ! -t 0 ]; then
  NON_INTERACTIVE=true
fi

echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║               brainsOS Environment & Credential Generator                    ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Read existing values if .env exists
EXISTING_DOMAIN="brainsos.local"
EXISTING_MAIL_DOMAIN=""
EXISTING_DATA_DIR="./data"

if [ -f "${ENV_FILE}" ]; then
  EXISTING_DOMAIN=$(grep -E "^BRAINSOS_DOMAIN=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo "brainsos.local")
  EXISTING_MAIL_DOMAIN=$(grep -E "^BRAINSOS_MAIL_DOMAIN=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo "")
  EXISTING_DATA_DIR=$(grep -E "^BRAINSOS_DATA_DIR=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo "./data")
fi

TARGET_DOMAIN="${CUSTOM_DOMAIN:-${EXISTING_DOMAIN:-brainsos.local}}"
TARGET_MAIL_DOMAIN="${CUSTOM_MAIL_DOMAIN:-${EXISTING_MAIL_DOMAIN}}"
TARGET_DATA_DIR="${CUSTOM_DATA_DIR:-${EXISTING_DATA_DIR:-./data}}"

# ------------------------------------------------------------------------------
# Interactive Q&A
# ------------------------------------------------------------------------------
if [ "${NON_INTERACTIVE}" = false ]; then
  echo -e "${BOLD}Interactive Configuration Wizard:${NC}"
  echo ""

  # 1. Existing passwords prompt
  if [ -f "${ENV_FILE}" ] && [ "${FORCE_PASSWORDS}" = false ]; then
    echo -e "${YELLOW}An existing .env file was detected.${NC}"
    read -r -p "Regenerate ALL passwords with newly generated secure random keys? [y/N]: " regen_resp
    if [[ "${regen_resp}" =~ ^[Yy]$ ]]; then
      FORCE_PASSWORDS=true
    else
      log_info "Preserving existing non-placeholder passwords; generating secure keys for any unset/placeholder secrets."
    fi
    echo ""
  fi

  # 2. Base platform domain
  read -r -p "Enter base platform domain [${TARGET_DOMAIN}]: " input_domain
  if [ -n "${input_domain}" ]; then
    TARGET_DOMAIN="${input_domain}"
  fi

  # 3. Email / SOGo domain or URL
  default_mail_display="${TARGET_MAIL_DOMAIN:-mail.${TARGET_DOMAIN}}"
  echo -e "${BLUE}[INFO]${NC} You can customize the email / SOGo service URL (e.g. ${BOLD}dev.local.brainsos.ai${NC} or ${BOLD}mail.${TARGET_DOMAIN}${NC})."
  read -r -p "Enter email service URL / domain [${default_mail_display}]: " input_mail_domain
  if [ -n "${input_mail_domain}" ]; then
    TARGET_MAIL_DOMAIN="${input_mail_domain}"
  elif [ -z "${TARGET_MAIL_DOMAIN}" ]; then
    TARGET_MAIL_DOMAIN="mail.${TARGET_DOMAIN}"
  fi

  # 4. Runtime data directory
  read -r -p "Enter runtime data directory [${TARGET_DATA_DIR}]: " input_data_dir
  if [ -n "${input_data_dir}" ]; then
    TARGET_DATA_DIR="${input_data_dir}"
  fi

  # 5. Rebuild containers
  read -r -p "Rebuild & reload platform containers with new configuration? [Y/n]: " input_rebuild
  if [[ "${input_rebuild}" =~ ^[Nn]$ ]]; then
    REBUILD=false
  fi
  echo ""
else
  if [ -z "${TARGET_MAIL_DOMAIN}" ]; then
    TARGET_MAIL_DOMAIN="mail.${TARGET_DOMAIN}"
  fi
fi

log_info "Configuration summary:"
echo -e "  - Base Domain:        ${BOLD}${TARGET_DOMAIN}${NC}"
echo -e "  - Email Service URL:  ${BOLD}${TARGET_MAIL_DOMAIN}${NC}"
echo -e "  - Data Directory:     ${BOLD}${TARGET_DATA_DIR}${NC}"
echo -e "  - Force New Secrets:  ${BOLD}${FORCE_PASSWORDS}${NC}"
echo -e "  - Rebuild Services:   ${BOLD}${REBUILD}${NC}"
echo ""

# ------------------------------------------------------------------------------
# Generate .env with Python Engine
# ------------------------------------------------------------------------------
log_info "Generating secure environment file (.env)..."

python3 - << EOF
import base64
import os
import secrets
import sys

env_file = "${ENV_FILE}"
example_file = "${EXAMPLE_FILE}"
temp_file = "${ENV_FILE}.tmp"

target_domain = "${TARGET_DOMAIN}"
target_mail_domain = "${TARGET_MAIL_DOMAIN}"
target_data_dir = "${TARGET_DATA_DIR}"
force_passwords = ("${FORCE_PASSWORDS}".lower() == "true")

# Parse existing .env if present
current_vars = {}
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line_s = line.strip()
            if not line_s or line_s.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            current_vars[k.strip()] = v.rstrip("\r\n")

# Helper to check if a value is a placeholder
def is_placeholder(val):
    if not val:
        return True
    val_lower = val.lower().strip()
    placeholder_fragments = [
        "change_me", "change-me", "changeme",
        "mock-key", "mock_key", "secret_pass",
        "brainsos_admin_secret", "brainsos_operator_secret",
        "brainsos_tool_egress_secret", "authentik_db_secret",
        "authentik_db_password", "authentik_secret",
        "authentik_bootstrap", "brainsos_authentik", "sogo_secret_pass",
        "sogo_db_password", "admin_mail_pass", "operator_mail_pass",
        "admin_pass", "litellm_password", "litellm_db_password",
        "sk-brainsos-mock-key", "sk-brainsos-master-key",
        "brainsos_langfuse_secret", "brainsos_langfuse_salt",
        "brainsos_langfuse_nextauth", "miniosecret", "myredissecret"
    ]
    if any(p in val_lower for p in placeholder_fragments):
        return True
    if "change" in val_lower:
        return True
    return False

def gen_hex(n=16):
    return secrets.token_hex(n)

def gen_alphanumeric(n=24):
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))

# Secret generation definitions
secret_generators = {
    "BRAINSOS_ADMIN_PASSWORD": lambda: gen_alphanumeric(24),
    "LITELLM_MASTER_KEY": lambda: f"sk-brainsos-{gen_hex(16)}",
    "LITELLM_DB_PASSWORD": lambda: gen_hex(20),
    "SOGO_DB_PASSWORD": lambda: gen_hex(20),
    "AUTHENTIK_SECRET_KEY": lambda: gen_hex(32),
    "AUTHENTIK_POSTGRESQL__PASSWORD": lambda: gen_hex(20),
    "AUTHENTIK_BOOTSTRAP_TOKEN": lambda: f"ak-tok-{gen_hex(16)}",
    "HERMES_API_TERRASTELLA_KEY": lambda: f"sk-api-terra-{gen_hex(16)}",
    "HERMES_API_MARVIN_KEY": lambda: f"sk-api-marvin-{gen_hex(16)}",
    "HERMES_API_BAWTFORD_KEY": lambda: f"sk-api-bawt-{gen_hex(16)}",
    "TERRASTELLA_LITELLM_KEY": lambda: f"sk-virt-terra-{gen_hex(16)}",
    "MARVIN_LITELLM_KEY": lambda: f"sk-virt-marvin-{gen_hex(16)}",
    "BAWTFORD_LITELLM_KEY": lambda: f"sk-virt-bawt-{gen_hex(16)}",
    "OPERATOR_LITELLM_KEY": lambda: f"sk-virt-operator-{gen_hex(16)}",
    "TERRASTELLA_MAIL_PASSWORD": lambda: gen_hex(16),
    "BAWTFORD_MAIL_PASSWORD": lambda: gen_hex(16),
    "MARVIN_MAIL_PASSWORD": lambda: gen_hex(16),
    "PING_MAIL_PASSWORD": lambda: gen_hex(16),
    "CLAUDE_MAIL_PASSWORD": lambda: gen_hex(16),
    "GPT_MAIL_PASSWORD": lambda: gen_hex(16),
    "NEXTAUTH_SECRET": lambda: base64.b64encode(secrets.token_bytes(32)).decode(),
    "SALT": lambda: base64.b64encode(secrets.token_bytes(32)).decode(),
    "ENCRYPTION_KEY": lambda: gen_hex(32),
    "LANGFUSE_DB_PASSWORD": lambda: gen_hex(16),
    "REDIS_AUTH": lambda: gen_hex(16),
    "MINIO_ROOT_PASSWORD": lambda: gen_hex(16),
    "LANGFUSE_PUBLIC_KEY": lambda: f"pk-lf-{gen_hex(16)}",
    "LANGFUSE_SECRET_KEY": lambda: f"sk-lf-{gen_hex(16)}",
}

generated_secrets = {}
for key, gen_fn in secret_generators.items():
    current_val = current_vars.get(key, "")
    if force_passwords or is_placeholder(current_val):
        generated_secrets[key] = gen_fn()
    else:
        generated_secrets[key] = current_val

# Sync dependent values
db_user = current_vars.get("LITELLM_DB_USER", "litellm")
db_port = current_vars.get("LITELLM_DB_PORT", "5432")
db_name = current_vars.get("LITELLM_DB_NAME", "litellm")
db_pass = generated_secrets["LITELLM_DB_PASSWORD"]
generated_secrets["DATABASE_URL"] = f"postgresql://{db_user}:{db_pass}@127.0.0.1:{db_port}/{db_name}"

# Sync Langfuse OTel Basic Auth header
lf_pub = generated_secrets.get("LANGFUSE_PUBLIC_KEY", "")
lf_sec = generated_secrets.get("LANGFUSE_SECRET_KEY", "")
if lf_pub and lf_sec:
    generated_secrets["LANGFUSE_OTEL_AUTH"] = f"Basic {base64.b64encode(f'{lf_pub}:{lf_sec}'.encode()).decode()}"

# Format output matching .env.example
output_lines = []
handled_keys = set()

with open(example_file, "r", encoding="utf-8") as f:
    for line in f:
        line_rstrip = line.rstrip("\r\n")
        line_s = line_rstrip.strip()
        if not line_s or line_s.startswith("#"):
            # Check for BRAINSOS_MAIL_DOMAIN comment in example
            if line_s.startswith("# BRAINSOS_MAIL_DOMAIN=") and target_mail_domain:
                output_lines.append(f"BRAINSOS_MAIL_DOMAIN={target_mail_domain}")
                handled_keys.add("BRAINSOS_MAIL_DOMAIN")
            else:
                output_lines.append(line_rstrip)
            continue

        if "=" in line_s:
            k, default_v = line_rstrip.split("=", 1)
            k = k.strip()
            handled_keys.add(k)

            # Check special overrides
            if k == "BRAINSOS_DOMAIN":
                output_lines.append(f"BRAINSOS_DOMAIN={target_domain}")
            elif k == "BRAINSOS_ADMIN_EMAIL":
                output_lines.append(f"BRAINSOS_ADMIN_EMAIL=admin@{target_domain}")
            elif k == "BRAINSOS_MAIL_DOMAIN":
                output_lines.append(f"BRAINSOS_MAIL_DOMAIN={target_mail_domain}")
            elif k == "BRAINSOS_DATA_DIR":
                output_lines.append(f"BRAINSOS_DATA_DIR={target_data_dir}")
            elif k in generated_secrets:
                output_lines.append(f"{k}={generated_secrets[k]}")
            elif k in current_vars:
                output_lines.append(f"{k}={current_vars[k]}")
            else:
                output_lines.append(f"{k}={default_v}")
        else:
            output_lines.append(line_rstrip)

# Ensure BRAINSOS_MAIL_DOMAIN is present
if "BRAINSOS_MAIL_DOMAIN" not in handled_keys:
    output_lines.append(f"BRAINSOS_MAIL_DOMAIN={target_mail_domain}")
    handled_keys.add("BRAINSOS_MAIL_DOMAIN")

# Filter out legacy redundant variables that inherit from BRAINSOS_ADMIN_PASSWORD
redundant_legacy_keys = {
    "HERMES_DASHBOARD_USER",
    "HERMES_DASHBOARD_PASSWORD",
    "CODE_SERVER_PASSWORD",
    "LANGFUSE_INIT_USER_PASSWORD",
    "LANGFUSE_INIT_USER_EMAIL",
    "ADMIN_MAIL_PASSWORD",
    "OPERATOR_MAIL_PASSWORD",
    "AUTHENTIK_BOOTSTRAP_PASSWORD",
    "AUTHENTIK_BOOTSTRAP_EMAIL",
    "TOOL_EGRESS_WEB_PASSWORD",
    "OPERATOR_PASSWORD_HASH",
}

# Append any custom unmapped keys from existing .env
unmapped = [
    k for k in current_vars
    if k not in handled_keys
    and not k.startswith("#")
    and k not in redundant_legacy_keys
]
if unmapped:
    output_lines.append("")
    output_lines.append("# ==============================================================================")
    output_lines.append("# Custom & Unmapped Overrides")
    output_lines.append("# ==============================================================================")
    for k in sorted(unmapped):
        output_lines.append(f"{k}={current_vars[k]}")

with open(temp_file, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

EOF

# Create safety backup of existing .env
if [ -f "${ENV_FILE}" ]; then
  BACKUP_FILE="${ENV_FILE}.bak-$(date +%Y%m%d%H%M%S)"
  cp -p "${ENV_FILE}" "${BACKUP_FILE}"
  cp -p "${ENV_FILE}" "${ENV_FILE}.bak"
  log_info "Safety backup created at ${BACKUP_FILE}"
fi

mv "${ENV_FILE}.tmp" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"
log_success "Generated secure .env file with permissions 600."

# Synchronize Langfuse distributed stack environment
if [ -f "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" ]; then
  log_info "Synchronizing Langfuse distributed environment configuration..."
  "${REPO_ROOT}/scripts/setup/setup-langfuse.sh" setup || true
fi

# ------------------------------------------------------------------------------
# Rebuild & Reload Services
# ------------------------------------------------------------------------------
if [ "${REBUILD}" = true ]; then
  echo ""
  log_info "Rebuilding and reloading platform Docker services and control plane..."
  "${SCRIPT_DIR}/reload-env.sh"
else
  log_info "Skipping container rebuild as requested."
fi

echo ""
log_success "Environment generation complete!"
echo -e "To view all service URLs and active credentials, run: ${BOLD}make urls${NC}"
