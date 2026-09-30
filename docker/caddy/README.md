# brainsOS: Ingress Reverse Proxy & ACME DNS-01 Architecture (`docker/caddy`)

This directory contains the custom build configuration and operational documentation for brainsOS's **Caddy Ingress Gateway** (Layer 7: Communications & UX Ingress Plane).

---

## 1. Architectural Overview & The "Why"

brainsOS runs on local hardware appliances (such as the ASUS Ascent GX10 or Apple Silicon workstations) behind local network NAT firewalls. Standard web infrastructure relies on **HTTP-01 ACME challenges** to acquire Let's Encrypt SSL certificates, which requires opening inbound ports 80 and 443 to the public internet.

**For brainsOS, opening inbound router ports is unacceptable**:
1. **Zero Attack Surface**: Inbound port forwarding exposes the appliance host, local agent sandboxes, and home/office networks to malicious port scans and exploit payloads.
2. **Wildcard Support**: Standard HTTP-01 challenges cannot issue wildcard certificates (`*.brainsos.local.<domain>`).
3. **Frictionless Mobile & Desktop Trust**: Self-signed certificates require manual Root CA installation on every device (macOS, iOS, Android, Linux). Public Let's Encrypt certificates are natively trusted by every WebKit, Chromium, and Gecko browser without installing anything.

To solve this, brainsOS uses **ACME DNS-01 Challenges via AWS Route 53**.

```text
                     ┌────────────────────────────────────────────────────────┐
                     │ AWS Route 53 (Managed by SST in infra/)                │
                     │ Hosted Zone: example.com                               │
                     └───────────────▲──────────────────────▲─────────────────┘
                                     │                      │
             1. Outbound API call:   │                      │ 3. Let's Encrypt
             Caddy writes temporary  │                      │    queries public DNS
             _acme-challenge TXT     │                      │    to verify ownership
                                     │                      │
┌────────────────────────────────────┴─────┐       ┌────────┴───────────────────┐
│ LOCAL BRAINSOS APPLIANCE                 │       │ PUBLIC LET'S ENCRYPT CA    │
│                                          │       │                            │
│  [ Caddy Reverse Proxy Container ]       │◄──────┤ 4. Issues signed public    │
│    • Built with 'dns.providers.route53'  │       │    Wildcard SSL Cert       │
│    • Mounts ~/.aws for AWS credentials   │       │    (Green Padlock)         │
│    • Serves all reverse proxies:         │       └────────────────────────────┘
│      *.brainsos.local.example.com        │
└──────────────────────────────────────────┘
```

---

## 2. One Wildcard Certificate for All Reverse Proxies

### "Do we need a separate Let's Encrypt challenge for every URL?"
**No.** Let's Encrypt issues a **single wildcard certificate** covering:
- `*.brainsos.local.example.com`
- `brainsos.local.example.com`

Because a wildcard certificate matches any first-level subdomain, **a single challenge secures all appliance reverse proxies**:
- `https://editor.brainsos.local.example.com` (Operator IDE / VS Code)
- `https://proxy.brainsos.local.example.com` (LiteLLM Control Plane Gateway)
- `https://dgx.brainsos.local.example.com` (Hardware Telemetry)
- `https://langfuse.brainsos.local.example.com` (Observability)
- `https://efw.brainsos.local.example.com` (Tool Egress Firewall Console)
- `https://terrastella.brainsos.local.example.com` (Terrastella Agent Unit)
- `https://marvin.brainsos.local.example.com` (Marvin Agent Unit)
- `https://bawtford.brainsos.local.example.com` (Bawtford Agent Unit)
- *Any newly spawned agent units added to `config/agents.yaml`!*

The verification happens **once**. Once issued, Caddy stores the wildcard certificate in the persistent Docker volume (`brainsos_caddy_data`) and serves it instantly to all incoming requests with zero latency.

---

## 3. How It Works: Step-by-Step Lifecycle

1. **Custom Multi-Stage Build (`Dockerfile`)**:
   Standard Caddy binaries do not include cloud DNS providers. We compile Caddy with `xcaddy` using `github.com/caddy-dns/route53`:
   ```dockerfile
   FROM caddy:2-builder-alpine AS builder
   RUN xcaddy build --with github.com/caddy-dns/route53
   FROM caddy:2-alpine
   COPY --from=builder /usr/bin/caddy /usr/bin/caddy
   ```

2. **Credential Resolution**:
   In `docker-compose.yml`, the host's AWS CLI directory is mounted into the container read-only:
   ```yaml
   volumes:
     - ${HOME}/.aws:/root/.aws:ro
   ```
   Caddy's Route 53 plugin natively reads credentials from `/root/.aws/credentials` (or environment variables if explicitly configured).

3. **Dynamic TLS Policy Compilation (`sync-agents.sh`)**:
   When `ACME_DNS_PROVIDER=route53` is enabled in `.env`, `./scripts/control/sync-agents.sh` generates `config/caddy/tls_policy.caddy`:
   ```caddy
   (brainsos_tls) {
       tls {
           dns route53
       }
   }
   ```
   Every public route block imports `brainsos_tls`, while localhost routes (`*.localhost`) remain bound to `tls internal`.

4. **The Outbound ACME DNS-01 Flow**:
   - When Caddy receives its first request, it calls Let's Encrypt via ACME.
   - Let's Encrypt returns a challenge token.
   - Caddy calls AWS Route 53 API (`route53:ChangeResourceRecordSets`) to create a TXT record:
     `_acme-challenge.brainsos.local.example.com`
   - Let's Encrypt queries authoritative DNS, validates the token, and issues the signed wildcard certificate.
   - Caddy deletes the temporary TXT record from Route 53.
   - Caddy caches the certificate in `/data` (Docker volume `brainsos_caddy_data`).

5. **Automatic 60-Day Renewal**:
   Caddy checks certificate expiration continuously and automatically repeats the DNS-01 challenge in the background every 60 days. No manual maintenance or renewal scripts are ever needed.

---

## 4. Localhost Fallback Preservation

Localhost routes (`http://editor.localhost`, `http://*.localhost`, `127.0.0.1`) remain strictly isolated from public ACME:
- ACME Certificate Authorities strictly refuse to issue certificates for `.localhost` or local IPs.
- Caddy separates public and localhost blocks; localhost blocks use `tls internal` (Caddy's local trust store), ensuring local offline development never errors or blocks on external network calls.
