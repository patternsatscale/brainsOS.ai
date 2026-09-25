#!/bin/bash
set -e

echo "[TITAN-MAIL] Initializing Titan Mail Server (Postfix + Dovecot)..."

# Ensure directories exist
mkdir -p /var/mail/vmail /etc/mail-titan /var/run/dovecot /var/spool/postfix
touch /var/mail/vmail/shared-mailboxes.db

# Ensure vmail user & group exist
addgroup -g 5000 vmail 2>/dev/null || true
adduser -D -u 5000 -G vmail -h /var/mail/vmail vmail 2>/dev/null || true
addgroup dovecot vmail 2>/dev/null || true
addgroup postfix vmail 2>/dev/null || true

# Initialize configuration files if not present in mounted volume
if [ ! -f /etc/mail-titan/users ]; then
    echo "[TITAN-MAIL] Seeding default accounts in /etc/mail-titan/users..."
    cat << 'EOF' > /etc/mail-titan/users
admin@titan.local:{PLAIN}admin_secret_pass:5000:5000::/var/mail/vmail/admin::
operator@titan.local:{PLAIN}operator_secret_pass:5000:5000::/var/mail/vmail/operator::
terrastella@titan.local:{PLAIN}terrastella_secret_pass:5000:5000::/var/mail/vmail/terrastella::
bawtford@titan.local:{PLAIN}bawtford_secret_pass:5000:5000::/var/mail/vmail/bawtford::
marvin@titan.local:{PLAIN}marvin_secret_pass:5000:5000::/var/mail/vmail/marvin::
EOF
fi

if [ ! -f /etc/mail-titan/vmailbox ]; then
    cat << 'EOF' > /etc/mail-titan/vmailbox
admin@titan.local admin
operator@titan.local operator
terrastella@titan.local terrastella
bawtford@titan.local bawtford
marvin@titan.local marvin
EOF
fi

if [ ! -f /etc/mail-titan/virtual ]; then
    cat << 'EOF' > /etc/mail-titan/virtual
# Alias mappings
postmaster@titan.local admin@titan.local
root@titan.local admin@titan.local
EOF
fi

# Compile Postfix lookup databases
postmap lmdb:/etc/mail-titan/vmailbox
postmap lmdb:/etc/mail-titan/virtual
newaliases

# Enforce secure permissions
chown -R vmail:vmail /var/mail/vmail
chmod -R 770 /var/mail/vmail

# Scaffold mailbox folders for all users
for user in $(cut -d: -f1 /etc/mail-titan/users); do
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
env | grep -E '^(HERMES_API_|TITAN_AGENT_)' > /etc/environment || true
chmod 644 /etc/environment

# Start Dovecot
echo "[TITAN-MAIL] Starting Dovecot daemon..."
/usr/sbin/dovecot
sleep 1

# Register ACLs via doveadm:
# 1. Agent owners get read, write, seen, insert, and post rights — but CANNOT delete, expunge, or modify ACLs
# 2. Administrator gets full management access (including write-deleted and expunge)
for user in $(cut -d: -f1 /etc/mail-titan/users); do
    if [ "$user" != "admin@titan.local" ]; then
        # Restrict agent owner: no write-deleted (t), no expunge (e), no admin (a)
        doveadm acl set -u "$user" INBOX owner lookup read write write-seen insert post 2>/dev/null || true
        # Grant admin full oversight & expunge capabilities
        doveadm acl set -u "$user" INBOX user=admin@titan.local lookup read write write-seen write-deleted insert post expunge admin 2>/dev/null || true
    fi
done

# Start Postfix
echo "[TITAN-MAIL] Starting Postfix daemon..."
/usr/sbin/postfix start

echo "[TITAN-MAIL] Mail server running and ready for traffic (SMTP :25/:587, IMAP :143)."

# Signal handler for graceful shutdown
shutdown() {
    echo "[TITAN-MAIL] Shutting down Postfix and Dovecot..."
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
        echo "[TITAN-MAIL] Dovecot process died!"
        exit 1
    fi
    if ! /usr/sbin/postfix status >/dev/null 2>&1; then
        echo "[TITAN-MAIL] Postfix process died!"
        exit 1
    fi
    sleep 5
done
