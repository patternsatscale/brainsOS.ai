# ==============================================================================
# brainsOS: Caddy Reverse Proxy with Route 53 ACME DNS-01 Plugin
# Multi-stage build enabling native wildcard TLS without open inbound ports.
# Preserves native ARM64 parity for ASUS Ascent GX10 and Apple Silicon.
# ==============================================================================

FROM caddy:2.11.4-builder-alpine@sha256:0aa610043dab5da82ad0a0268e46bb852785e6f5160f12f1c6fe3f42903d7e1b AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/route53@v1.6.3

FROM caddy@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
