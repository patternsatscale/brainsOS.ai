#!/bin/bash
set -e

echo "[BRAINSOS-MAIL] Initializing brainsOS Mail Server (Postfix + Dovecot)..."

# Ensure directories exist
mkdir -p /var/mail/vmail /etc/mail-brainsos /var/run/dovecot /var/spool/postfix /var/spool/brainsos/inbound
touch /var/mail/vmail/shared-mailboxes.db
chown -R vmail:vmail /var/spool/brainsos 2>/dev/null || true
chmod -R 775 /var/spool/brainsos 2>/dev/null || true

# Ensure vmail user & group exist
addgroup -g 5000 vmail 2>/dev/null || true
adduser -D -u 5000 -G vmail -h /var/mail/vmail vmail 2>/dev/null || true
addgroup dovecot vmail 2>/dev/null || true
addgroup postfix vmail 2>/dev/null || true

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_admin_mail_secret_change_me}}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-${BRAINSOS_ADMIN_PASSWORD:-brainsos_operator_mail_secret_change_me}}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-brainsos_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-brainsos_marvin_mail_secret_change_me}"
PING_PASS="${PING_MAIL_PASSWORD:-brainsos_ping_mail_secret_change_me}"
CLAUDE_PASS="${CLAUDE_MAIL_PASSWORD:-brainsos_claude_mail_secret_change_me}"
GPT_PASS="${GPT_MAIL_PASSWORD:-brainsos_gpt_mail_secret_change_me}"

# Collect and deduplicate domains
RAW_DOMAINS=("brainsos.local" "local.brainsos.ai")
if [ -n "${BRAINSOS_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_DOMAIN}"); fi
if [ -n "${BRAINSOS_MAIL_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_MAIL_DOMAIN}"); fi
if [ -n "${BRAINSOS_EMAIL_DOMAIN:-}" ]; then RAW_DOMAINS+=("${BRAINSOS_EMAIL_DOMAIN}"); fi

UNIQUE_DOMAINS=()
for d in "${RAW_DOMAINS[@]}"; do
    skip=0
    for u in "${UNIQUE_DOMAINS[@]}"; do
        if [ "$d" = "$u" ]; then
            skip=1
            break
        fi
    done
    if [ "$skip" -eq 0 ]; then
        UNIQUE_DOMAINS+=("$d")
    fi
done

# Provision configuration files in mounted volume
echo "[BRAINSOS-MAIL] Provisioning accounts in /etc/mail-brainsos/users..."
> /etc/mail-brainsos/users
> /etc/mail-brainsos/vmailbox
> /etc/mail-brainsos/virtual

for d in "${UNIQUE_DOMAINS[@]}"; do
cat << EOF >> /etc/mail-brainsos/users
admin@${d}:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::
operator@${d}:{PLAIN}${OPERATOR_PASS}:5000:5000::/var/mail/vmail/operator::
terrastella@${d}:{PLAIN}${TERRASTELLA_PASS}:5000:5000::/var/mail/vmail/terrastella::
bawtford@${d}:{PLAIN}${BAWTFORD_PASS}:5000:5000::/var/mail/vmail/bawtford::
marvin@${d}:{PLAIN}${MARVIN_PASS}:5000:5000::/var/mail/vmail/marvin::
ping@${d}:{PLAIN}${PING_PASS}:5000:5000::/var/mail/vmail/ping::
claude@${d}:{PLAIN}${CLAUDE_PASS}:5000:5000::/var/mail/vmail/claude::
gpt@${d}:{PLAIN}${GPT_PASS}:5000:5000::/var/mail/vmail/gpt::
EOF

cat << EOF >> /etc/mail-brainsos/vmailbox
admin@${d} admin
operator@${d} operator
terrastella@${d} terrastella
bawtford@${d} bawtford
marvin@${d} marvin
ping@${d} ping
claude@${d} claude
gpt@${d} gpt
EOF

cat << EOF >> /etc/mail-brainsos/virtual
postmaster@${d} admin@brainsos.local
root@${d} admin@brainsos.local
cindy@${d} bawtford@${d}
EOF
done

# Configure Postfix virtual mailbox domains
DOMAINS_STR=$(IFS=', '; echo "${UNIQUE_DOMAINS[*]}")
postconf -e "virtual_mailbox_domains = ${DOMAINS_STR}"

# Compile Postfix lookup databases
postmap lmdb:/etc/mail-brainsos/vmailbox
postmap lmdb:/etc/mail-brainsos/virtual
newaliases

# Clean up any stale lock files from previous unclean shutdowns
find /var/mail/vmail -name "*.lock" -delete 2>/dev/null || true

# Enforce secure permissions
chown -R vmail:vmail /var/mail/vmail
chmod -R 770 /var/mail/vmail

# Scaffold mailbox folders for all users
for user in $(cut -d: -f1 /etc/mail-brainsos/users); do
    name=$(echo "$user" | cut -d@ -f1)
    mkdir -p "/var/mail/vmail/$name/Maildir/new" \
             "/var/mail/vmail/$name/Maildir/cur" \
             "/var/mail/vmail/$name/Maildir/tmp"
    chown -R vmail:vmail "/var/mail/vmail/$name"
    chmod -R 770 "/var/mail/vmail/$name"
done

# Compile default Sieve script and ensure webhook dispatcher permissions
if [ -f /etc/dovecot/sieve/default.sieve ]; then
    sievec /etc/dovecot/sieve/default.sieve /etc/dovecot/sieve/default.svbin 2>/dev/null || true
    chmod 644 /etc/dovecot/sieve/default.* 2>/dev/null || true
    chown -R vmail:vmail /etc/dovecot/sieve 2>/dev/null || true
fi
if [ -f /usr/lib/dovecot/sieve-pipe/agent-webhook.sh ]; then
    chmod 755 /usr/lib/dovecot/sieve-pipe/agent-webhook.sh 2>/dev/null || true
fi

# Initialize Dovecot log file
touch /var/log/dovecot.log
chown dovecot:dovecot /var/log/dovecot.log 2>/dev/null || true
tail -n 0 -F /var/log/dovecot.log &

# Export environment variables for Dovecot Sieve child scripts
env | grep -E '^(HERMES_API_|BRAINSOS_AGENT_|BRAINSOS_INGRESS_URL|BRAINSOS_SPOOL_DIR)' > /etc/environment || true
chmod 644 /etc/environment

# Start Dovecot
echo "[BRAINSOS-MAIL] Starting Dovecot daemon..."
/usr/sbin/dovecot
sleep 1

# Register ACLs via doveadm:
# 1. Agent owners get read, write, seen, insert, and post rights — but CANNOT delete, expunge, or modify ACLs
# 2. Administrator gets full management access (including write-deleted and expunge)
for user in $(cut -d: -f1 /etc/mail-brainsos/users); do
    base_user=$(echo "$user" | cut -d@ -f1)
    if [ "$base_user" != "admin" ]; then
        # Restrict agent owner: no write-deleted (t), no expunge (e), no admin (a)
        doveadm acl set -u "$user" INBOX owner lookup read write write-seen insert post 2>/dev/null || true
        # Grant admin full oversight & expunge capabilities across all domains
        for d in "${UNIQUE_DOMAINS[@]}"; do
            doveadm acl set -u "$user" INBOX user=admin@${d} lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
        done
    fi
done

# Start Postfix
echo "[BRAINSOS-MAIL] Starting Postfix daemon..."
/usr/sbin/postfix start

echo "[BRAINSOS-MAIL] Mail server running and ready for traffic (SMTP :25/:587, IMAP :143)."

# Signal handler for graceful shutdown
shutdown() {
    echo "[BRAINSOS-MAIL] Shutting down Postfix and Dovecot..."
    /usr/sbin/postfix stop 2>/dev/null || true
    if [ -f /var/run/dovecot/master.pid ]; then
        kill -TERM $(cat /var/run/dovecot/master.pid 2>/dev/null) 2>/dev/null || true
    fi
    exit 0
}

trap shutdown SIGTERM SIGINT

# Keep container alive while monitoring daemons
while true; do
    if [ ! -f /var/run/dovecot/master.pid ] || ! kill -0 $(cat /var/run/dovecot/master.pid 2>/dev/null) 2>/dev/null; then
        echo "[BRAINSOS-MAIL] Dovecot process died!"
        exit 1
    fi
    if ! /usr/sbin/postfix status >/dev/null 2>&1; then
        echo "[BRAINSOS-MAIL] Postfix process died!"
        exit 1
    fi
    sleep 5
done
