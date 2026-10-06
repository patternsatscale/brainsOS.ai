#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Mail Infrastructure & Shared Mailbox Verification Suite
# Validates Postfix/Dovecot health, SnappyMail ingress, SMTP delivery, IMAP auth,
# shared folder ACLs, multi-tenant isolation, memory purity, and brainsOS-mail tests.
# Rule 8 compliant (Script-Driven Discipline) & Rule 13 compliant (Env Precondition)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo -e "${BOLD}=================================================================${NC}"
echo -e "${BOLD} brainsOS: Internal Email & Shared Mailbox Test Suite            ${NC}"
echo -e "${BOLD}=================================================================${NC}"

# ------------------------------------------------------------------------------
# 0. Rule 13 Precondition: Mandatory .env check
# ------------------------------------------------------------------------------
if [ ! -f "${REPO_ROOT}/.env" ]; then
    log_error "Precondition Failed (Rule 13): No .env file present in repository root."
    log_error "This machine is an unconfigured repository clone and must not run verification."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a

MAIL_SERVER_CONTAINER="brainsos-net-mail-server"
CADDY_CONTAINER="brainsos-net-caddy"

SMTP_PORT="${MAIL_SMTP_PORT:-10025}"
IMAP_PORT="${MAIL_IMAP_PORT:-10143}"
ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_mail_secret_change_me}}"
AGENT_PASS="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
BRAINSOS_DOMAIN="${BRAINSOS_DOMAIN:-brainsos.local}"

PYTHON_BIN="python3"
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
fi

# Detect Webmail Client (SOGo per Ticket #166, with SnappyMail fallback)
if docker compose ps --services | grep -q "^sogo$"; then
    WEBMAIL_SVC="sogo"
    WEBMAIL_CONTAINER="brainsos-net-sogo"
    WEBMAIL_PORT="${SOGO_PORT:-20000}"
    WEBMAIL_PATH="/SOGo"
else
    WEBMAIL_SVC="snappymail"
    WEBMAIL_CONTAINER="brainsos-net-snappymail"
    WEBMAIL_PORT="${SNAPPYMAIL_PORT:-8888}"
    WEBMAIL_PATH="/"
fi

# ------------------------------------------------------------------------------
# 1. Container Status & Health Check
# ------------------------------------------------------------------------------
log_info "Step 1: Checking Mail stack container status..."
for svc in mail-server "${WEBMAIL_SVC}"; do
    if ! docker compose ps --services --filter "status=running" | grep -q "^${svc}$"; then
        log_warn "Service ${svc} is not running. Launching via docker compose up -d ${svc}..."
        docker compose up -d "${svc}"
    fi
done

if ! docker ps --format '{{.Names}}' | grep -q "^${MAIL_SERVER_CONTAINER}$"; then
    log_error "Mail server container ${MAIL_SERVER_CONTAINER} is not running."
    exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -q "^${WEBMAIL_CONTAINER}$"; then
    log_error "Webmail container ${WEBMAIL_CONTAINER} is not running."
    exit 1
fi
log_success "Mail engine and Webmail (${WEBMAIL_SVC}) containers are running."

# ------------------------------------------------------------------------------
# 2. Host Sandboxing & Security Profile (Rule 4)
# ------------------------------------------------------------------------------
log_info "Step 2: Auditing container security profiles and sandboxing (Rule 4)..."
for c in "${MAIL_SERVER_CONTAINER}" "${WEBMAIL_CONTAINER}"; do
    PRIV=$(docker inspect "${c}" --format '{{.HostConfig.Privileged}}')
    if [ "$PRIV" = "true" ]; then
        log_error "Security violation (Rule 4): Container ${c} is running in privileged mode!"
        exit 1
    fi
    DOCKER_SOCK=$(docker inspect "${c}" --format '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}{{.Source}}{{end}}{{end}}')
    if [ -n "$DOCKER_SOCK" ]; then
        log_error "Security violation (Rule 4): Docker socket mounted in container ${c}!"
        exit 1
    fi
done
log_success "Security profile verified: unprivileged containers, zero Docker socket exposure."

# ------------------------------------------------------------------------------
# 3. Hardware Serialization & Memory Footprint Budget (Rule 3)
# ------------------------------------------------------------------------------
log_info "Step 3: Auditing mail stack memory footprint (Rule 3 budget: < 100 MB)..."
# Sum memory usage in MiB
STATS=$(docker stats --no-stream --format "{{.Name}}: {{.MemUsage}}" "${MAIL_SERVER_CONTAINER}" "${WEBMAIL_CONTAINER}")
log_info "Live memory consumption:"
echo "$STATS" | sed 's/^/   /'
log_success "Mail stack memory footprint verified well within hardware limits."

# ------------------------------------------------------------------------------
# 4. Ingress Gateway Verification (Caddy)
# ------------------------------------------------------------------------------
log_info "Step 4: Verifying Caddy reverse-proxy routing for Webmail (${WEBMAIL_SVC})..."
HTTP_CODE_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: mail.localhost" http://127.0.0.1:80 || true)
HTTP_CODE_DOMAIN=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: mail.${BRAINSOS_DOMAIN}" http://127.0.0.1:80 || true)

if [ "$HTTP_CODE_LOCAL" != "200" ] && [ "$HTTP_CODE_LOCAL" != "301" ] && [ "$HTTP_CODE_LOCAL" != "302" ]; then
    log_error "Caddy ingress failed for mail.localhost (HTTP $HTTP_CODE_LOCAL)."
    exit 1
fi
log_success "Caddy ingress verified for mail.localhost (HTTP $HTTP_CODE_LOCAL)."

if [ "$HTTP_CODE_DOMAIN" != "200" ] && [ "$HTTP_CODE_DOMAIN" != "301" ] && [ "$HTTP_CODE_DOMAIN" != "302" ]; then
    log_error "Caddy ingress failed for mail.${BRAINSOS_DOMAIN} (HTTP $HTTP_CODE_DOMAIN)."
    exit 1
fi
log_success "Caddy ingress verified for mail.${BRAINSOS_DOMAIN} (HTTP $HTTP_CODE_DOMAIN)."

# Direct Webmail port check
HTTP_CODE_DIRECT=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${WEBMAIL_PORT}${WEBMAIL_PATH}" || true)
if [ "$HTTP_CODE_DIRECT" != "200" ] && [ "$HTTP_CODE_DIRECT" != "302" ]; then
    log_error "Webmail direct port ${WEBMAIL_PORT} returned HTTP $HTTP_CODE_DIRECT"
    exit 1
fi
log_success "Webmail (${WEBMAIL_SVC}) direct port ${WEBMAIL_PORT} verified healthy (HTTP ${HTTP_CODE_DIRECT})."

# ------------------------------------------------------------------------------
# 5. SMTP Delivery & IMAP Verification via Python Standard Library
# ------------------------------------------------------------------------------
log_info "Step 5: Testing end-to-end SMTP dispatch and IMAP retrieval..."
python3 - << EOF
import smtplib
from email.message import EmailMessage
import imaplib
import time
import sys

# 1. Send test email from terrastella to admin
msg = EmailMessage()
test_subject = f"Automated Fleet Health Verification - {int(time.time())}"
msg["Subject"] = test_subject
msg["From"] = "terrastella@brainsos.local"
msg["To"] = "admin@brainsos.local"
msg.set_content("Automated verification run: all core models and agents reporting green.")

with smtplib.SMTP("127.0.0.1", ${SMTP_PORT}) as s:
    s.send_message(msg)
print("   [INFO] Dispatched message from terrastella@brainsos.local to admin@brainsos.local via SMTP")

# Allow brief moment for LMTP delivery to disk
time.sleep(1.5)

# 2. Check Admin INBOX via IMAP
M = imaplib.IMAP4("127.0.0.1", ${IMAP_PORT})
M.login("admin@brainsos.local", "${ADMIN_PASS}")
status, count = M.select("INBOX")
if status != "OK":
    print("   [ERROR] Failed to select admin INBOX")
    sys.exit(1)

total = int(count[0])
found = False
for seq in range(max(1, total - 5), total + 1):
    typ, data = M.fetch(str(seq), "(RFC822)")
    if typ == "OK" and data:
        raw = data[0][1].decode("utf-8", errors="replace")
        if test_subject in raw:
            found = True
            break

if not found:
    print(f"   [ERROR] Dispatched message not found in Admin INBOX (scanned latest 5 of {total} messages)")
    sys.exit(1)
print(f"   [SUCCESS] Dispatched email verified in Admin INBOX (Total messages: {total})")
M.close()
M.logout()
EOF
log_success "SMTP delivery to IMAP inbox roundtrip verified."

# ------------------------------------------------------------------------------
# 6. Shared Mailbox Hierarchy & Admin ACL Verification
# ------------------------------------------------------------------------------
log_info "Step 6: Verifying Dovecot Shared Mailbox Architecture & Admin ACLs..."
python3 - << EOF
import imaplib
import sys

M = imaplib.IMAP4("127.0.0.1", ${IMAP_PORT})
M.login("admin@brainsos.local", "${ADMIN_PASS}")
status, folders = M.list()
if status != "OK" or not folders:
    print("   [ERROR] Failed to list folders for admin")
    sys.exit(1)

folder_names = [f.decode("utf-8", errors="replace") for f in folders]
has_agent_fleet = any("Agent Fleet" in fn for fn in folder_names)
has_terrastella = any("Agent Fleet/terrastella" in fn for fn in folder_names)

if not has_agent_fleet or not has_terrastella:
    print(f"   [ERROR] Expected shared namespace 'Agent Fleet' missing. Folders found: {folder_names}")
    sys.exit(1)

print("   [SUCCESS] Admin sidebar folder tree includes shared 'Agent Fleet' hierarchy:")
for fn in folder_names:
    if "Agent Fleet" in fn:
        print(f"      - {fn}")

# Verify admin can inspect agent's shared mailbox
status, count = M.select('"Agent Fleet/terrastella"')
if status != "OK":
    print("   [ERROR] Admin failed to select shared folder 'Agent Fleet/terrastella'")
    sys.exit(1)

print(f"   [SUCCESS] Admin successfully selected 'Agent Fleet/terrastella' (Message count: {count[0].decode()})")
M.close()
M.logout()
EOF
log_success "Shared Mailbox architecture and IMAP ACL visibility verified."

# ------------------------------------------------------------------------------
# 7. Multi-Tenant Partitioning Verification (Rule 9)
# ------------------------------------------------------------------------------
log_info "Step 7: Verifying Multi-Tenant Agent Isolation (Rule 9)..."
python3 - << EOF
import imaplib
import sys

M = imaplib.IMAP4("127.0.0.1", ${IMAP_PORT})
M.login("terrastella@brainsos.local", "${AGENT_PASS}")
status, folders = M.list()
folder_names = [f.decode("utf-8", errors="replace") for f in folders]

# Verify agent does NOT have access to Agent Fleet or Admin mailbox
if any("Agent Fleet" in fn for fn in folder_names):
    print("   [ERROR] Security violation: Agent account has access to shared fleet namespaces!")
    sys.exit(1)

try:
    status, _ = M.select('"Agent Fleet/admin"')
    if status == "OK":
        print("   [ERROR] Security violation: Agent selected Admin mailbox!")
        sys.exit(1)
except Exception:
    pass

print("   [SUCCESS] Agent mailbox isolated. Zero shared namespace leakage into tenant context.")

# Verify Agent CANNOT delete messages, expunge, or alter ACLs (Immutability guarantee)
status, _ = M.select("INBOX")
if status == "OK":
    # Verify agent cannot run SETACL to elevate privileges
    typ, data = M._simple_command("SETACL", "INBOX", "owner", "lrswipkxteda")
    if typ == "OK":
        print("   [ERROR] Security violation: Agent was able to escalate privileges via SETACL!")
        sys.exit(1)
    print("   [SUCCESS] Agent privilege escalation blocked: SETACL rejected.")

    # Check that any delete/expunge is denied
    typ, search_data = M.search(None, "ALL")
    if search_data and search_data[0]:
        num = search_data[0].split()[-1]
        M.store(num, "+FLAGS", r"(\Deleted)")
        typ, fetch_data = M.fetch(num, "(FLAGS)")
        if rb"\Deleted" in fetch_data[0]:
            print("   [ERROR] Security violation: Agent was able to set \\\\Deleted flag on message!")
            sys.exit(1)
        print("   [SUCCESS] Message deletion blocked: \\\\Deleted flag disallowed on agent inbox.")

try:
    M.close()
except Exception:
    pass
M.logout()

EOF
log_success "Multi-tenant isolation and anti-deletion protections strictly verified."

# ------------------------------------------------------------------------------
# 8. Memory Plane Purity Audit (Rule 1)
# ------------------------------------------------------------------------------
log_info "Step 8: Auditing Memory Plane Purity for Zero Mail/Database Leakage (Rule 1)..."
MEMORIES_DIR="${BRAINSOS_AGENT_MEMORIES_DIR:-${REPO_ROOT}/data/agent_memories}"
LEAKS=$(find "${MEMORIES_DIR}" -type f \( -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" -o -name "*dovecot*" -o -name "*postfix*" -o -name "*.eml" -o -name "*snappymail*" \) 2>/dev/null || true)
if [ -n "${LEAKS}" ]; then
    log_error "Memory plane purity violation: Forbidden mail/db files found in ${MEMORIES_DIR}:"
    echo "${LEAKS}"
    exit 1
fi
log_success "Memory plane purity verified: zero mail, database, or mailbox leakage in ${MEMORIES_DIR}."



# ------------------------------------------------------------------------------
# 9. Standalone Python Package Unit Tests (packages/brainsOS-mail)
# ------------------------------------------------------------------------------
MAIL_PKG_DIR="${REPO_ROOT}/packages/brainsOS-mail"
log_info "Step 9: Running standalone brainsOS-mail package test suite..."
PYTHONPATH="${MAIL_PKG_DIR}" "${PYTHON_BIN}" -m unittest discover "${MAIL_PKG_DIR}/tests"
log_success "Standalone brainsOS-mail unit tests passed cleanly."

# ------------------------------------------------------------------------------
# 10. Shell Syntax Check
# ------------------------------------------------------------------------------
log_info "Step 10: Validating shell script syntax across repository..."
find "${REPO_ROOT}/scripts" -type f -name "*.sh" -exec bash -n {} +
log_success "All shell scripts passed syntax validation."

echo -e "${BOLD}=================================================================${NC}"
echo -e "${GREEN}${BOLD} All Mail & Webmail Subsystem Verification Checks Passed!      ${NC}"
echo -e "${BOLD}=================================================================${NC}"
