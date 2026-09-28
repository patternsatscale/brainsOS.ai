FROM alpine:3.20

RUN apk add --no-cache \
    postfix \
    dovecot \
    dovecot-lmtpd \
    dovecot-pigeonhole-plugin \
    bash \
    curl \
    python3 \
    ca-certificates

# Ensure vmail user & group exist with UID/GID 5000
RUN addgroup -g 5000 vmail 2>/dev/null || true && \
    adduser -D -u 5000 -G vmail -h /var/mail/vmail vmail 2>/dev/null || true && \
    addgroup dovecot vmail 2>/dev/null || true && \
    addgroup postfix vmail 2>/dev/null || true

# Directory scaffolding
RUN mkdir -p /var/mail/vmail \
             /etc/dovecot \
             /etc/postfix \
             /etc/mail-brainsos \
             /usr/lib/dovecot/sieve-pipe \
             /etc/dovecot/sieve \
             /var/run/dovecot && \
    chown -R vmail:vmail /var/mail/vmail && \
    chmod -R 770 /var/mail/vmail

COPY dovecot/dovecot.conf /etc/dovecot/dovecot.conf
COPY postfix/main.cf /etc/postfix/main.cf
COPY postfix/master.cf /etc/postfix/master.cf
COPY sieve/default.sieve /etc/dovecot/sieve/default.sieve
COPY agent-webhook.sh /usr/lib/dovecot/sieve-pipe/agent-webhook.sh
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /usr/lib/dovecot/sieve-pipe/agent-webhook.sh && \
    sievec /etc/dovecot/sieve/default.sieve /etc/dovecot/sieve/default.svbin 2>/dev/null || true

EXPOSE 25 143 587

ENTRYPOINT ["/entrypoint.sh"]
