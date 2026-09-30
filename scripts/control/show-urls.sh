#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Service URL & Credential Directory (show-urls.sh)
#
# Displays all active service URLs, ports, usernames, and passwords from .env,
# and automatically checks / synchronizes local domain mappings in /etc/hosts.
# ==============================================================================

set -euo pipefail

# Terminal colors & styling
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
MAGENTA="\033[0;35m"
DIM="\033[2m"
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

if [ ! -f "${ENV_FILE}" ]; then
  log_error "No .env file found at ${ENV_FILE}."
  echo -e "Run ${BOLD}make env${NC} or ${BOLD}make setup${NC} first to bootstrap your environment."
  exit 1
fi

APPLY_HOSTS=false
NO_HOSTS=false
MASK_SECRETS=false

show_help() {
  echo -e "${BOLD}brainsOS Service URL & Credential Directory${NC}"
  echo ""
  echo "Usage:"
  echo "  $0 [options]"
  echo ""
  echo "Options:"
  echo "  --apply-hosts     Automatically apply missing /etc/hosts mappings (requires sudo)"
  echo "  --no-hosts        Skip checking or updating /etc/hosts"
  echo "  --mask-secrets    Mask passwords and API tokens in output"
  echo "  -h, --help        Show this help documentation"
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply-hosts)
      APPLY_HOSTS=true
      shift
      ;;
    --no-hosts)
      NO_HOSTS=true
      shift
      ;;
    --mask-secrets)
      MASK_SECRETS=true
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

# Execute formatting and extraction via Python helper
python3 - << EOF
import os
import re
import sys

env_file = "${ENV_FILE}"
mask_secrets = ("${MASK_SECRETS}".lower() == "true")
no_hosts = ("${NO_HOSTS}".lower() == "true")
apply_hosts = ("${APPLY_HOSTS}".lower() == "true")

env = {}
with open(env_file, "r", encoding="utf-8") as f:
    for line in f:
        line_s = line.strip()
        if not line_s or line_s.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.rstrip("\r\n").strip('"\'')

domain = env.get("BRAINSOS_DOMAIN", "brainsos.local")
mail_domain = env.get("BRAINSOS_MAIL_DOMAIN", f"mail.{domain}")
email_account_domain = mail_domain if ("." in mail_domain and not mail_domain.startswith("mail.")) else domain

caddy_http = env.get("CADDY_HTTP_PORT", "80")
caddy_https = env.get("CADDY_HTTPS_PORT", "443")
code_port = env.get("CODE_SERVER_PORT", "8443")
code_user = env.get("OPERATOR_USER", "operator")
code_pass = env.get("CODE_SERVER_PASSWORD", "brainsos_operator_secret")

litellm_port = env.get("LITELLM_PORT", "4000")
litellm_key = env.get("LITELLM_MASTER_KEY", "sk-brainsos-master-key")
litellm_db_user = env.get("LITELLM_DB_USER", "litellm")
litellm_db_pass = env.get("LITELLM_DB_PASSWORD", "litellm_password")
litellm_db_port = env.get("LITELLM_DB_PORT", "5432")

sogo_port = env.get("SOGO_PORT", "20000")
mail_smtp_port = env.get("MAIL_SMTP_PORT", "10025")
mail_imap_port = env.get("MAIL_IMAP_PORT", "10143")

admin_mail_pass = env.get("ADMIN_MAIL_PASSWORD", "admin_mail_pass")
op_mail_pass = env.get("OPERATOR_MAIL_PASSWORD", "operator_mail_pass")
terra_mail_pass = env.get("TERRASTELLA_MAIL_PASSWORD", "terrastella_mail_pass")
marvin_mail_pass = env.get("MARVIN_MAIL_PASSWORD", "marvin_mail_pass")
bawt_mail_pass = env.get("BAWTFORD_MAIL_PASSWORD", "bawtford_mail_pass")
ping_mail_pass = env.get("PING_MAIL_PASSWORD", "ping_mail_pass")

hermes_runner_port = env.get("HERMES_RUNNER_PORT", "8642")
openai_runner_port = env.get("OPENAI_RUNNER_PORT", "8002")
agent_queue_port = env.get("AGENT_QUEUE_PORT", "8000")

langfuse_port = env.get("LANGFUSE_PORT", "3001")
langfuse_user = env.get("LANGFUSE_INIT_USER_EMAIL", f"admin@{domain}")
langfuse_pass = env.get("LANGFUSE_INIT_USER_PASSWORD", "brainsos_admin_secret")

egress_port = env.get("TOOL_EGRESS_WEB_PORT", "8081")
egress_pass = env.get("TOOL_EGRESS_WEB_PASSWORD", "brainsos_tool_egress_secret")

def mask(val):
    if not val:
        return "(none)"
    if not mask_secrets:
        return val
    if len(val) <= 6:
        return "******"
    return val[:3] + "..." + val[-3:]

W_NAME = 28
W_URL = 34
W_LOCAL = 26
W_AUTH = 36

BOLD = "\033[1m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
MAGENTA = "\033[0;35m"
DIM = "\033[2m"
NC = "\033[0m"

sep_line = f"{CYAN}{'═' * 115}{NC}"
sub_line = f"{DIM}{'─' * 115}{NC}"

print(sep_line)
print(f"{CYAN}{BOLD}  brainsOS Platform Service Directory & Ingress Gateway{NC}")
print(f"{DIM}  Target Domain: {BOLD}{domain}{DIM} | Email Host: {BOLD}{mail_domain}{DIM} | Config: {env_file}{NC}")
print(sep_line)
print(f"{BOLD}{'SERVICE':<28} {'PUBLIC / LAN URL':<34} {'LOCALHOST FALLBACK':<24} {'CREDENTIALS / AUTH'}{NC}")
print(sub_line)

def print_row(name, pub_url, local_url, auth_info=""):
    print(f"{BOLD}{name:<28}{NC} {CYAN}{pub_url:<34}{NC} {DIM}{local_url:<24}{NC} {YELLOW}{auth_info}{NC}")

# Section 1: Ingress & UX (L7 Web Interfaces)
print_row("Landing Page Portal", f"https://{domain}", f"http://localhost:{caddy_http}", "(public)")
print_row("Operator IDE (VS Code)", f"https://editor.{domain}", f"http://localhost:{code_port}", f"user: {code_user} | pass: {mask(code_pass)}")
print_row("Webmail & SOGo Groupware", f"https://{mail_domain}", f"http://localhost:{sogo_port}", f"user: operator@{email_account_domain} | pass: {mask(op_mail_pass)}")
print_row("LiteLLM Proxy Admin UI", f"https://proxy.{domain}/ui", f"http://localhost:{litellm_port}/ui", f"key: {mask(litellm_key)}")
print_row("Langfuse Observability", f"https://langfuse.{domain}", f"http://localhost:{langfuse_port}", f"user: {langfuse_user} | pass: {mask(langfuse_pass)}")
print_row("Tool Egress Proxy (mitm)", f"https://efw.{domain}", f"http://localhost:{egress_port}", f"pass: {mask(egress_pass)}")
print_row("NVIDIA DGX Telemetry", f"https://dgx.{domain}", "http://localhost:11001", "(system metrics)")

print(sub_line)
# Section 2: Cognitive Compute & Agent Runners (L2 Internal IPC & Worker)
print_row("Shared Hermes Runner (IPC)", "-", f"http://127.0.0.1:{hermes_runner_port}/v1", "(stateless runner)")
print_row("OpenAI SDK Runner (IPC)", "-", f"http://127.0.0.1:{openai_runner_port}/v1", "(stateless runner)")
print_row("Agent Queue & Webhook", "-", f"http://127.0.0.1:{agent_queue_port}/api/v1", "(async mail daemon)")

print(sub_line)
# Section 3: Multi-Agent Fleet & Communications (Tenant Personas & Mailboxes)
print_row("Terrastella (Primary Ops)", f"terrastella@{email_account_domain}", "-", f"pass: {mask(terra_mail_pass)}")
print_row("Marvin (Sports Analytics)", f"marvin@{email_account_domain}", "-", f"pass: {mask(marvin_mail_pass)}")
print_row("Bawtford (Creative Director)", f"bawtford@{email_account_domain}", "-", f"pass: {mask(bawt_mail_pass)}")
print_row("Ping (Auto-Responder)", f"ping@{email_account_domain}", "-", f"pass: {mask(ping_mail_pass)}")
print_row("Operator Mailbox", f"operator@{email_account_domain}", "-", f"pass: {mask(op_mail_pass)}")
print_row("Admin Mailbox", f"admin@{email_account_domain}", "-", f"pass: {mask(admin_mail_pass)}")

print(sub_line)
# Section 4: Mail & Persistence Protocols (L4 Storage)
print_row("Postfix SMTP Relay", f"smtp://{domain}:{mail_smtp_port}", f"127.0.0.1:{mail_smtp_port}", "STARTTLS optional")
print_row("Dovecot IMAP Server", f"imap://{domain}:{mail_imap_port}", f"127.0.0.1:{mail_imap_port}", "Plain / LOGIN auth")
print_row("LiteLLM PostgreSQL DB", "-", f"127.0.0.1:{litellm_db_port}", f"user: {litellm_db_user} | pass: {mask(litellm_db_pass)}")

print(sep_line)
print("")

# ------------------------------------------------------------------------------
# Check /etc/hosts
# ------------------------------------------------------------------------------
required_hosts = [
    domain,
    f"editor.{domain}",
    f"code.{domain}",
    f"mail.{domain}",
    f"proxy.{domain}",
    f"dgx.{domain}",
    f"langfuse.{domain}",
    f"efw.{domain}",
    f"firewall.{domain}"
]
if mail_domain and mail_domain not in required_hosts:
    required_hosts.append(mail_domain)

# Read /etc/hosts
existing_resolved = set()
hosts_file_content = ""
try:
    with open("/etc/hosts", "r", encoding="utf-8", errors="ignore") as f:
        hosts_file_content = f.read()
        for line in hosts_file_content.splitlines():
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split()
            if len(parts) >= 2:
                ip = parts[0]
                if ip in ("127.0.0.1", "127.0.0.01", "::1"):
                    for host in parts[1:]:
                        existing_resolved.add(host.lower())
except Exception as e:
    print(f"{YELLOW}[WARN] Could not inspect /etc/hosts: {e}{NC}")

missing_hosts = [h for h in required_hosts if h.lower() not in existing_resolved]

if not missing_hosts:
    print(f"{GREEN}[SUCCESS] All {len(required_hosts)} service domains are mapped to 127.0.0.1 in /etc/hosts.{NC}")
    sys.exit(0)

print(f"{YELLOW}[NOTICE] {len(missing_hosts)} service hostnames are missing from /etc/hosts:{NC}")
for h in missing_hosts:
    print(f"  - {h}")
print("")

# Prepare hosts entry block
hosts_block_header = "# brainsOS-managed-hosts-begin"
hosts_block_footer = "# brainsOS-managed-hosts-end"
hosts_line = f"127.0.0.1 " + " ".join(sorted(set(required_hosts)))

new_block = f"{hosts_block_header}\n{hosts_line}\n{hosts_block_footer}\n"

# Output instructions / apply
if no_hosts:
    print(f"{BLUE}[INFO] Skipping /etc/hosts update (--no-hosts specified).{NC}")
    print(f"To configure manually, run:")
    print(f"  echo \"{hosts_line}\" | sudo tee -a /etc/hosts\n")
    sys.exit(0)

# Write temp hosts file for safe substitution
temp_hosts = "/tmp/hosts.brainsos.new"
try:
    if hosts_block_header in hosts_file_content and hosts_block_footer in hosts_file_content:
        # Replace existing managed block
        pattern = re.compile(rf"{re.escape(hosts_block_header)}.*?{re.escape(hosts_block_footer)}\n?", re.DOTALL)
        updated_content = pattern.sub(new_block, hosts_file_content)
    else:
        # Append managed block
        updated_content = hosts_file_content.rstrip() + "\n\n" + new_block

    with open(temp_hosts, "w", encoding="utf-8") as f:
        f.write(updated_content)
except Exception as e:
    print(f"{RED}[ERROR] Failed to write temporary hosts file: {e}{NC}")
    sys.exit(1)

# Prompt or apply
should_apply = apply_hosts
if not should_apply and sys.stdin.isatty():
    resp = input(f"Would you like to automatically update /etc/hosts now? (Requires sudo) [Y/n]: ").strip()
    if resp.lower() not in ("n", "no"):
        should_apply = True

if should_apply:
    print(f"{BLUE}[INFO] Updating /etc/hosts (sudo authentication may be requested)...{NC}")
    cmd = f'sudo cp /etc/hosts "/etc/hosts.bak-\$(date +%Y%m%d%H%M%S)" && sudo cp "{temp_hosts}" /etc/hosts && rm -f "{temp_hosts}"'
    ret = os.system(f'bash -c \'{cmd}\'')
    if ret == 0:
        print(f"{GREEN}[SUCCESS] Successfully updated /etc/hosts with brainsOS service domains!{NC}")
    else:
        print(f"{RED}[WARN] Could not update /etc/hosts automatically.{NC}")
        print(f"Run the following command manually:")
        print(f"  echo \"{hosts_line}\" | sudo tee -a /etc/hosts\n")
else:
    print(f"{BLUE}[INFO] To manually add these domains to /etc/hosts, run:{NC}")
    print(f"  echo \"{hosts_line}\" | sudo tee -a /etc/hosts\n")

EOF
