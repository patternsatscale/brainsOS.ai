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

ADMIN_PASS="${ADMIN_MAIL_PASSWORD:-brainsos_admin_mail_secret_change_me}"
OPERATOR_PASS="${OPERATOR_MAIL_PASSWORD:-brainsos_operator_mail_secret_change_me}"
TERRASTELLA_PASS="${TERRASTELLA_MAIL_PASSWORD:-brainsos_terrastella_mail_secret_change_me}"
BAWTFORD_PASS="${BAWTFORD_MAIL_PASSWORD:-brainsos_bawtford_mail_secret_change_me}"
MARVIN_PASS="${MARVIN_MAIL_PASSWORD:-brainsos_marvin_mail_secret_change_me}"
PING_PASS="${PING_MAIL_PASSWORD:-brainsos_ping_mail_secret_change_me}"

MAIL_DOMAIN="${BRAINSOS_MAIL_DOMAIN:-${BRAINSOS_DOMAIN:-brainsos.local}}"

# Provision configuration files in mounted volume
echo "[BRAINSOS-MAIL] Provisioning accounts in /etc/mail-brainsos/users..."
cat << EOF > /etc/mail-brainsos/users
admin@brainsos.local:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::
operator@brainsos.local:{PLAIN}${OPERATOR_PASS}:5000:5000::/var/mail/vmail/operator::
terrastella@brainsos.local:{PLAIN}${TERRASTELLA_PASS}:5000:5000::/var/mail/vmail/terrastella::
bawtford@brainsos.local:{PLAIN}${BAWTFORD_PASS}:5000:5000::/var/mail/vmail/bawtford::
marvin@brainsos.local:{PLAIN}${MARVIN_PASS}:5000:5000::/var/mail/vmail/marvin::
ping@brainsos.local:{PLAIN}${PING_PASS}:5000:5000::/var/mail/vmail/ping::
EOF

if [ "${MAIL_DOMAIN}" != "brainsos.local" ]; then
cat << EOF >> /etc/mail-brainsos/users
admin@${MAIL_DOMAIN}:{PLAIN}${ADMIN_PASS}:5000:5000::/var/mail/vmail/admin::
operator@${MAIL_DOMAIN}:{PLAIN}${OPERATOR_PASS}:5000:5000::/var/mail/vmail/operator::
terrastella@${MAIL_DOMAIN}:{PLAIN}${TERRASTELLA_PASS}:5000:5000::/var/mail/vmail/terrastella::
bawtford@${MAIL_DOMAIN}:{PLAIN}${BAWTFORD_PASS}:5000:5000::/var/mail/vmail/bawtford::
marvin@${MAIL_DOMAIN}:{PLAIN}${MARVIN_PASS}:5000:5000::/var/mail/vmail/marvin::
ping@${MAIL_DOMAIN}:{PLAIN}${PING_PASS}:5000:5000::/var/mail/vmail/ping::
EOF
fi

cat << EOF > /etc/mail-brainsos/vmailbox
admin@brainsos.local admin
operator@brainsos.local operator
terrastella@brainsos.local terrastella
bawtford@brainsos.local bawtford
marvin@brainsos.local marvin
ping@brainsos.local ping
EOF

if [ "${MAIL_DOMAIN}" != "brainsos.local" ]; then
cat << EOF >> /etc/mail-brainsos/vmailbox
admin@${MAIL_DOMAIN} admin
operator@${MAIL_DOMAIN} operator
terrastella@${MAIL_DOMAIN} terrastella
bawtford@${MAIL_DOMAIN} bawtford
marvin@${MAIL_DOMAIN} marvin
ping@${MAIL_DOMAIN} ping
EOF
fi

if [ ! -f /etc/mail-brainsos/virtual ]; then
    cat << EOF > /etc/mail-brainsos/virtual
# Alias mappings
postmaster@brainsos.local admin@brainsos.local
root@brainsos.local admin@brainsos.local
postmaster@${MAIL_DOMAIN} admin@brainsos.local
root@${MAIL_DOMAIN} admin@brainsos.local
EOF
fi

# Configure Postfix virtual mailbox domains
postconf -e "virtual_mailbox_domains = brainsos.local, ${MAIL_DOMAIN}"

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
    chmod 755 /usr/lib/dovecot/sieve-pipe/agent-webhook.sh
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
    if [ "$user" != "admin@brainsos.local" ] && [ "$user" != "admin@${MAIL_DOMAIN}" ]; then
        # Restrict agent owner: no write-deleted (t), no expunge (e), no admin (a)
        doveadm acl set -u "$user" INBOX owner lookup read write write-seen insert post 2>/dev/null || true
        # Grant admin full oversight & expunge capabilities
        doveadm acl set -u "$user" INBOX user=admin@brainsos.local lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
        if [ "${MAIL_DOMAIN}" != "brainsos.local" ]; then
            doveadm acl set -u "$user" INBOX user=admin@${MAIL_DOMAIN} lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
        fi
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
