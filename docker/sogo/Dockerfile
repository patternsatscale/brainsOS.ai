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
COPY entrypoint.sh /entrypoint.sh
RUN chmod 644 /etc/sogo/sogo.conf /etc/nginx/sites-available/default && chmod 755 /entrypoint.sh

EXPOSE 20000

ENTRYPOINT ["/entrypoint.sh"]
