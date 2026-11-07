FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# Install SOGo, memcached, PostgreSQL client, and process tools
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        sogo \
        memcached \
        postgresql-client \
        ca-certificates \
        curl \
        gosu \
        procps \
        nginx-light && \
    rm -rf /var/lib/apt/lists/*

# Scaffold runtime directories with proper permissions
RUN mkdir -p /etc/sogo /var/spool/sogo /var/log/sogo /var/run/sogo && \
    chown -R sogo:sogo /etc/sogo /var/spool/sogo /var/log/sogo /var/run/sogo

COPY sogo.conf /etc/sogo/sogo.conf
COPY nginx.conf /etc/nginx/sites-available/default
COPY theme-brainsos.css /usr/lib/GNUstep/SOGo/WebServerResources/css/theme-brainsos.css
COPY theme-brainsos.js /usr/lib/GNUstep/SOGo/WebServerResources/js/theme-brainsos.js
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/delete e\.target\.attributes\.target/e.target.removeAttribute("target")/g' /usr/lib/GNUstep/SOGo/WebServerResources/js/Mailer.services.js 2>/dev/null || true && \
    sed -i 's/delete \$event\.target\.attributes\.target/$event.target.removeAttribute("target")/g' /usr/lib/GNUstep/SOGo/WebServerResources/js/Mailer/MessageController.js 2>/dev/null || true && \
    chmod 644 /etc/sogo/sogo.conf /etc/nginx/sites-available/default /usr/lib/GNUstep/SOGo/WebServerResources/css/theme-brainsos.css /usr/lib/GNUstep/SOGo/WebServerResources/js/theme-brainsos.js && \
    chmod 755 /entrypoint.sh

EXPOSE 20000

ENTRYPOINT ["/entrypoint.sh"]
