# Project Titan: Lightweight Internal Email Subsystem (`docker/mail`)

This directory contains the container definitions, service configurations, and architectural specifications for Project Titan's **Internal Email & Shared Mailbox Subsystem** (Layer 7: Communications Plane).

---

## 1. Architectural Overview & Design Philosophy

In an autonomous multi-agent operating environment, human-agent and agent-to-agent collaboration face critical challenges when relying strictly on synchronous REST APIs, WebSocket streams, or terminal logs:

1. **Thread Blocking & Token Waste**: When an agent requires human review (e.g. approving a website deploy, database migration, or external API action), keeping a synchronous process active or polling an LLM completion loop wastes GPU inference tokens and exhausts CPU cycles.
2. **Context Window Saturation**: Polling an LLM repeatedly to ask "Has the operator responded yet?" consumes valuable context memory and saturates the unified memory bus.
3. **Observability Fragmentation**: Console outputs and Docker logs are ephemeral, messy, and difficult to audit historically.

### The Solution: Asynchronous Email Network with Shared Mailboxes

Project Titan deploys a private, ultra-lightweight email system engineered specifically for edge AI appliances:
* **Dedicated Agent Mailboxes**: Every agent (`operator@titan.local`, `terrastella@titan.local`, `bawtford@titan.local`, `marvin@titan.local`) has a native Maildir inbox.
* **Human-in-the-Loop (HITL) Asynchronous Briefs**: Agents dispatch RFC-compliant emails to `admin@titan.local` with markdown-formatted briefs, preview URLs, and actionable decision points.
* **The Unified Admin Cockpit (SOGo Groupware)**: The human operator logs into a modern groupware interface (**SOGo**) once. All agent mailboxes are dynamically mapped into the admin's sidebar under an `Agent Fleet` namespace (e.g., `Agent Fleet / Terrastella`, `Agent Fleet / Bawtford`). The operator inspects agent reports, reviews sent drafts, inspects CalDAV calendars, and schedules tasks via calendar invites.
* **Strict Multi-Tenant Isolation (Rule 9)**: Individual agents authenticate with Dovecot and have access *only* to their own personal Maildir. Cross-agent inspection or reading the administrator's mailbox is blocked at the IMAP protocol layer via RFC 4314 ACLs.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AGENT PLANE                                          │
│                                                                                        │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │   Terrastella   │    │    Bawtford     │    │     Marvin      │    │  Operator   │  │
│  │ (Agent Sandbox) │    │ (Agent Sandbox) │    │ (Agent Sandbox) │    │ Receptionist│  │
│  │ [titan-queue]   │    │ [titan-queue]   │    │ [titan-queue]   │    │ [titan-queue│  │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘    └──────┬──────┘  │
└───────────┼──────────────────────┼──────────────────────┼────────────────────┼─────────┘
            │                      │                      │                    │
            │ (Internal SMTP :25 / IMAP :143 via Docker network: titan-internal)       │
            ▼                      ▼                      ▼                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        MAIL SERVER CONTAINER (titan-mail-server)                       │
│                                                                                        │
│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ Postfix 3.9 (MTA)                       │  │ Dovecot 2.3 (MDA & IMAP)            │  │
│  │ - SMTP Port 25 (Internal Container Net) │  │ - IMAP Port 143 (Private Docker Net)│  │
│  │ - Submission Port 587 (Authenticated)   │  │ - Memory-Mapped (mmap) Indexing     │  │
│  │ - LMDB Virtual Lookup Maps              │  │ - Shared Namespace: Agent Fleet/%%n/│  │
│  │ - Relays to LMTP on 127.0.0.1:24        │  │ - RFC 4314 IMAP ACL Enforcement     │  │
│  └────────────────────┬────────────────────┘  └──────────────────┬──────────────────┘  │
│                       │ LMTP Delivery (Port 24)                  │                     │
│                       └──────────────────────────────────────────┘                     │
│                                         │                                              │
│                                         ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Pigeonhole Sieve Engine (Event Hooks for Issue #164)                             │  │
│  │ - Compiles default.sieve to bytecode (.svbin)                                    │  │
│  │ - /usr/lib/dovecot/sieve-pipe mounted for wake-up webhook dispatch               │  │
│  │ - Pipes new message brief to agent /webhook endpoint                             │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                         │                                              │
│                                         ▼                                              │
│                        Flat-file Maildir Storage: /data/comms/email/vmail              │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          │ Internal IMAP (:143) / SMTP (:25)
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   GROUPWARE CONTAINER: SOGo (titan-net-sogo)                           │
│                   Replaces SnappyMail (Ticket #166)                                    │
│                                                                                        │
│  - Native ARM64 (debian:bookworm-slim + sogo 5.8.0 + memcached)                        │
│  - CalDAV / CardDAV / Webmail Unified Engine                                           │
│  - sogo-ealarms-notify (1-minute calendar event reminder dispatcher)                  │
│  - Dedicated Isolated DB: titan-sogo-db (PostgreSQL 16, Rule 6 strictly enforced)     │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          │ Reverse Proxy HTTP (Port 20000)
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       INGRESS REVERSE PROXY (titan-infra-caddy)                        │
│                                                                                        │
│  - Virtual Hosts: mail.localhost, mail.titan.local -> sogo:20000 (/ -> /SOGo)         │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          ▼
                               Human Operator Web Browser
                         (Unified Webmail & Multi-Agent CalDAV)
```

---

## 2. Core Service Components

Rather than deploying heavyweight enterprise mail servers (which routinely consume 500 MB to 1 GB+ RAM due to embedded anti-spam scanners, anti-virus daemons, and bloated database engines), Project Titan combines **Alpine Postfix** and **Dovecot** in a single, unprivileged container:

### A. Postfix (Message Transfer Agent - MTA)
* **Role**: Accepts local SMTP submissions from agent containers and SOGo; routes messages to the local virtual mailbox delivery agent.
* **Ports**:
  * `25` (Standard SMTP): Open to the internal Docker network (`titan-internal`) for local container dispatch.
  * `587` (Submission): Authenticated submission supporting SASL authentication via Dovecot.
* **Local Hand-off**: Uses **LMTP (Local Mail Transfer Protocol)** over TCP (`127.0.0.1:24`) to deliver incoming mail directly to Dovecot.
* **Modern Storage**: Configured with **LMDB** (`virtual_mailbox_maps = lmdb:/etc/mail-titan/vmailbox`), completely avoiding deprecated Berkeley DB hash dependencies on modern Alpine distributions.

### B. Dovecot (Mail Delivery Agent & IMAP Server - MDA)
* **Role**: Handles mailbox storage (Maildir format), local indexing, IMAP retrieval for webmail, shared folder namespaces, and access control.
* **Extreme Low Footprint**: Written in optimized C with memory-mapped (`mmap`) indices (`dovecot.index`). When idle, Dovecot consumes **under 15 MiB RAM**.
* **Authentication**: File-based passdb (`/etc/mail-titan/users`) with encrypted or plaintext schemes—requiring zero external database dependencies.
* **Storage Engine**: Maildir layout (`/var/mail/vmail/%n/Maildir`) providing 100% human-readable flat-file message persistence.

### C. Pigeonhole Sieve Engine (Event Hooks for Issue #164)
* **Role**: Dovecot LMTP is configured with the **Pigeonhole Sieve extension** (`sieve_plugins = sieve_extprograms`, `sieve_global_extensions = +vnd.dovecot.pipe`).
* **Extension Hook**: Script `/usr/lib/dovecot/sieve-pipe/agent-webhook.sh` pipes incoming email metadata to target agent containers (`http://titan-agent-<name>:<port>/webhook`) to wake agents up asynchronously.

### D. SOGo Groupware & CalDAV Subsystem (Ticket #166)
* **Role**: Replaces legacy SnappyMail with a comprehensive, modern groupware suite supporting Webmail, Multi-Agent CalDAV Calendars, CardDAV address books, and automated reminder triggers.
* **Image**: `titan-sogo:latest` built natively on ARM64 from `debian:bookworm-slim` packaging SOGo 5.8.0, local memcached, and PostgreSQL driver.
* **Email Alarms Engine**: Background daemon executes `sogo-ealarms-notify` every 60 seconds. When an event reminder fires, SOGo dispatches an email via Postfix (`mail-server:25`), which passes through Dovecot LMTP and triggers the agent's webhook.
* **Database Isolation (Rule 6)**: SOGo persistence is hosted exclusively in `titan-sogo-db` (`postgres:16-alpine`), completely isolated from `titan-infra-litellm-db`.
* **Zero Overhead**: Total idle footprint of SOGo (~18 MiB) and SOGo DB (~36 MiB) is ~54 MiB, well below the appliance budget.    (Private Access: "Open to me and only me")
```

---

## 2. Core Service Components

Rather than deploying heavyweight enterprise mail servers (which routinely consume 500 MB to 1 GB+ RAM due to embedded anti-spam scanners, anti-virus daemons, and bloated database engines), Project Titan combines **Alpine Postfix** and **Dovecot** in a single, unprivileged container:

### A. Postfix (Message Transfer Agent - MTA)
* **Role**: Accepts local SMTP submissions from agent containers and SnappyMail; routes messages to the local virtual mailbox delivery agent.
* **Ports**:
  * `25` (Standard SMTP): Open to the internal Docker network (`titan-internal`) for local container dispatch.
  * `587` (Submission): Authenticated submission supporting SASL authentication via Dovecot.
* **Local Hand-off**: Uses **LMTP (Local Mail Transfer Protocol)** over TCP (`127.0.0.1:24`) to deliver incoming mail directly to Dovecot.
* **Modern Storage**: Configured with **LMDB** (`virtual_mailbox_maps = lmdb:/etc/mail-titan/vmailbox`), completely avoiding deprecated Berkeley DB hash dependencies on modern Alpine distributions.

### B. Dovecot (Mail Delivery Agent & IMAP Server - MDA)
* **Role**: Handles mailbox storage (Maildir format), local indexing, IMAP retrieval for webmail, shared folder namespaces, and access control.
* **Extreme Low Footprint**: Written in optimized C with memory-mapped (`mmap`) indices (`dovecot.index`). When idle, Dovecot consumes **under 15 MiB RAM**.
* **Authentication**: File-based passdb (`/etc/mail-titan/users`) with encrypted or plaintext schemes—requiring zero external database dependencies.
* **Storage Engine**: Maildir layout (`/var/mail/vmail/%n/Maildir`) providing 100% human-readable flat-file message persistence.

### C. Pigeonhole Sieve Engine (Event Hooks for Issue #164)
* **Role**: Dovecot LMTP is pre-configured with the **Pigeonhole Sieve extension** (`sieve_plugins = sieve_extprograms`, `sieve_global_extensions = +vnd.dovecot.pipe`).
* **Extension Hook**: Script directory `/usr/lib/dovecot/sieve-pipe` is mounted and ready for Ticket [#164](https://github.com/patternsatscale/project-titan/issues/164). When an email arrives for an agent, Sieve can pipe the email to an internal webhook dispatcher, waking up the target agent reactively without polling.

### D. SnappyMail Webmail Client
* **Role**: Provides a clean, ultra-fast webmail interface for the human operator.
* **Image**: `djmaze/snappymail:latest` (Alpine-based PHP 8.2 FPM).
* **Pre-Seeded Profiles**: Automatically configured with domain settings for `titan.local` (IMAP: `mail-server:143`, SMTP: `mail-server:25`, STARTTLS disabled internally).
* **Private Cockpit**: Mapped via Caddy reverse proxy on `mail.localhost` and `mail.titan.local`.

---

## 3. Shared Mailbox Architecture & Multi-Tenant Access Control

### How the Shared Namespace Works

Dovecot is configured with two distinct namespaces in [`dovecot/dovecot.conf`](file:///home/patternsatscale/ProjectTitan/docker/mail/dovecot/dovecot.conf):

```dovecot
# 1. Personal Namespace: authenticated user's private mailbox
namespace inbox {
  inbox = yes
  separator = /
  prefix =
  location = maildir:/var/mail/vmail/%n/Maildir
  mailbox Drafts { special_use = \Drafts }
  mailbox Sent { special_use = \Sent }
  mailbox Trash { special_use = \Trash }
  mailbox Junk { special_use = \Junk }
}

# 2. Shared Namespace: dynamically exposes delegated agent mailboxes
namespace shared {
  type = shared
  separator = /
  prefix = Agent Fleet/%%n/
  location = maildir:/var/mail/vmail/%%n/Maildir:INDEX=/var/mail/vmail/%n/shared/%%n
  subscriptions = yes
  list = children
}
```

### RFC 4314 IMAP ACL Subsystem & Immutability Guarantee

During container boot (`entrypoint.sh`), Dovecot assigns granular Access Control Lists (ACLs) using the standard `vfile` backend:
```bash
# 1. Restrict agent owner: CANNOT delete, expunge, or elevate privileges
doveadm acl set -u <agent_user> INBOX owner lookup read write write-seen insert post

# 2. Grant administrator full oversight & expunge capabilities
doveadm acl set -u <agent_user> INBOX user=admin@titan.local lookup read write write-seen write-deleted insert post expunge admin
```

#### Breakdown of Granted IMAP ACL Rights:
| Right | Name | Agent Owner | Human Admin | Description |
|---|---|:---:|:---:|---|
| `l` | **Lookup** | ✅ | ✅ | Mailbox is visible in folder listing and subscriptions. |
| `r` | **Read** | ✅ | ✅ | Read and download email message headers and bodies. |
| `s` | **Write-Seen** | ✅ | ✅ | Toggle `\Seen` (read/unread) flags. |
| `w` | **Write** | ✅ | ✅ | Toggle other flags (`\Answered`, `\Flagged`, etc.). |
| `i` | **Insert** | ✅ | ✅ | Copy or append new messages into the mailbox. |
| `p` | **Post** | ✅ | ✅ | Send mail directly to the mailbox via LMTP delivery. |
| `t` | **Write-Deleted** | ❌ **DENIED** | ✅ | Mark messages with `\Deleted` flag. |
| `e` | **Expunge** | ❌ **DENIED** | ✅ | Permanently purge deleted messages. |
| `x` | **Delete** | ❌ **DENIED** | ✅ | Delete or rename the mailbox folder. |
| `a` | **Admin** | ❌ **DENIED** | ✅ | Modify or grant ACL permissions. |

#### Why the Anti-Deletion Guarantee Matters:
1. **Audit Trail Protection**: Autonomous agents can never tamper with or cover their tracks by purging instructions, logs, or error reports.
2. **Privilege Escalation Protection**: Because agents lack the `admin` (`a`) right, attempts to run `SETACL` via IMAP to grant themselves deletion rights return an immediate `NO [NOPERM] You lack administrator privileges on this mailbox`.
3. **Admin Prerogative**: The human administrator is the sole actor permitted to expunge, delete, or archive emails.

### Operator vs. Agent Experience (Rule 9: Multi-Tenant Partitioning)

1. **Operator Experience (`admin@titan.local`)**:
   - Logs into SnappyMail once.
   - The left sidebar renders:
     * `INBOX` (Personal admin mailbox)
     * `Agent Fleet`
       * `operator`
       * `terrastella`
       * `bawtford`
       * `marvin`
   - Clicking any agent folder instantly lists their messages. The admin can read agent reports, view sent items, delete unwanted messages, and reply with instructions.

2. **Agent Experience (`terrastella@titan.local`, etc.)**:
   - Authenticates over IMAP using container credentials.
   - Has **zero ACL rights** to `admin@titan.local` or any peer agent mailboxes.
   - Attempting to inspect `Agent Fleet` or another agent's Maildir triggers an immediate RFC error: `NO [b"Mailbox doesn't exist"]`.
   - Cannot set `\Deleted` flag or call `EXPUNGE` on their own inbox.
   - Agents operate strictly within their append/read/flag partition.

---

## 4. Hardware Serialization & Resource Budget (Rule 3)

Project Titan is designed to operate on edge appliances with unified memory architectures (ASUS Ascent GX10 GB10 appliance and Apple Silicon workstations). In unified memory systems, background daemons that trigger excessive memory bus traffic or hog RAM degrade LLM inference throughput:

| Component | Container Name | Runtime Engine | Idle RAM | Architecture |
|---|---|---|---|---|
| **Mail Server** | `titan-net-mail-server` | Alpine 3.20 (Postfix + Dovecot C daemons) | **~11.5 MiB** | Native ARM64 |
| **Webmail Client** | `titan-net-snappymail` | Alpine (PHP 8.2 FPM) | **~52.0 MiB** | Native ARM64 |
| **Combined Stack** | Postfix + Dovecot + SnappyMail | Complete Email & Webmail Subsystem | **~63.5 MiB** | **PASSED (< 100 MB target)** |

---

## 5. Storage Topology & Memory Plane Purity (Rule 1)

All persistent state for the mail subsystem resides strictly under the communications data plane (`/data/comms/email`):

```text
data/comms/email/
├── config/                         # Authentication & routing configuration
│   ├── users                       # Dovecot passdb/userdb (username:password:uid:gid::home)
│   ├── vmailbox                    # Postfix recipient lookup table (lmdb compiled)
│   ├── vmailbox.lmdb               # Compiled LMDB database
│   ├── virtual                     # Postfix aliases and forwarding rules
│   └── virtual.lmdb                # Compiled LMDB aliases
├── snappymail/                     # SnappyMail application state
│   └── data/_data_/_default_
│       ├── domains/                # Pre-configured domain profiles (titan.local.json)
│       └── storage/                # SQLite session & address book cache
└── vmail/                          # Flat-file Maildir message stores (UID 5000)
    ├── admin/Maildir/              # Operator mailbox
    │   ├── cur/                    # Read messages
    │   ├── new/                    # Incoming unread messages
    │   ├── tmp/                    # Delivery scratch directory
    │   └── dovecot.index*          # Dovecot mmap index files
    ├── operator/Maildir/           # Operator receptionist agent mailbox
    ├── terrastella/Maildir/        # Primary operations agent mailbox
    │   ├── dovecot-acl             # IMAP ACL configuration file
    │   └── ...
    ├── bawtford/Maildir/           # Creative director agent mailbox
    ├── marvin/Maildir/             # Sports analytics agent mailbox
    └── shared-mailboxes.db         # Dovecot shared dictionary index
```

### Architectural Guarantees:
* **Memory Plane Purity (Rule 1)**: Absolutely zero mail files, SQLite databases, or runtime caches are stored in `/memories` (`./data/agent_memories`). The memory plane remains 100% human-auditable Open Knowledge Format (OKF) Markdown notes.
* **Git Cleanliness**: `data/comms/*` is ignored in `.gitignore`, preventing private messages and credentials from ever being committed to Git.

---

## 6. Future-Proofing & Roadmap Architecture (Tickets #163 & #164)

### A. Secure Remote Operator Access via Tailscale / WireGuard
* **The Goal**: Allow the human operator to access SnappyMail securely on a laptop or mobile phone outside the local LAN ("open to me and only me"), without exposing ports 25, 143, or 8888 to the public internet.
* **Architecture**:
  * A dedicated VPN gateway container (`titan-net-vpn` running Tailscale or WireGuard) attaches to the host.
  * Caddy reverse-proxies incoming connections arriving on the VPN interface (e.g. `100.x.y.z` or `10.8.0.x`) to SnappyMail.
  * SnappyMail remains strictly bound to internal Docker networks and the private VPN subnet. Zero open ports on public WAN interfaces.

### B. Inbound Reactive Agent Webhooks via Dovecot Pigeonhole Sieve
* **The Goal**: When an email arrives for an agent (e.g. `operator@titan.local` receives a directive from the admin), Dovecot should automatically fire an HTTP webhook into the agent container, waking it up instantly without polling.
* **Architecture**:
  1. Postfix receives SMTP message and delivers to Dovecot via LMTP (`127.0.0.1:24`).
  2. Dovecot LMTP triggers Pigeonhole Sieve with the `vnd.dovecot.pipe` extension enabled.
  3. Sieve executes an unprivileged shell script in `/usr/lib/dovecot/sieve-pipe/agent-webhook.sh`:
     ```bash
     #!/bin/sh
     RECIPIENT="$1"
     curl -s -X POST "http://titan-agent-${RECIPIENT}:8000/hooks/email" \
          -H "Content-Type: message/rfc822" \
          --data-binary @-
     ```
  4. The target agent container wakes up immediately, processes the message via `packages/titan_mail`, and records its actions to `/memories/`.

---

## 7. Standalone Python Agent Client (`packages/titan_mail`)

Agent containers interact with the mail server via the zero-dependency Python package located at [`packages/titan_mail/`](file:///home/patternsatscale/ProjectTitan/packages/titan_mail/):

```python
from titan_mail import TitanMailClient

# 1. Initialize client using container environment variables
# (TITAN_MAIL_HOST, TITAN_MAIL_USER, TITAN_MAIL_PASSWORD)
client = TitanMailClient.from_env()

# 2. Dispatch an RFC-compliant briefing email to the operator
msg_id = client.send_mail(
    to="admin@titan.local",
    subject="Deployment Brief: Web App Canvas v2.4",
    body="All visual regression checks passed. Ready for human review at http://localhost:3000.",
)

# 3. Retrieve unread messages from personal inbox
unread = client.get_unread_messages()
for msg in unread:
    print(f"From: {msg['from']} | Subject: {msg['subject']}")

    # Reply preserving RFC threading headers (In-Reply-To, References)
    client.send_mail(
        to=msg["from"],
        subject=f"Re: {msg['subject']}",
        body="Directive received and scheduled for immediate execution.",
        in_reply_to=msg["message_id"],
    )

# 4. Search inbox for specific keywords, subjects, or date ranges
matches = client.search_messages(query="deployment", subject="approval", unread_only=False)
for match in matches:
    print(f"Matched message {match['message_id']} from {match['from']}")
```


---

## 8. Operations, Diagnostics & Troubleshooting Handbook

### Common Operational Commands

```bash
# 1. Provision mail directories, seed accounts, and build container
./scripts/setup/setup-mail.sh

# 2. Start the mail stack via Docker Compose
docker compose up -d mail-server snappymail

# 3. Restart Caddy to bind mail hostnames
docker compose restart caddy

# 4. View real-time mail server logs
docker compose logs -f mail-server

# 5. Execute the automated 10-step verification suite
./scripts/verify/verify-mail.sh

# 6. Execute Python mail client unit tests
PYTHONPATH=packages/titan_mail python3 -m unittest discover packages/titan_mail/tests
```

### Inspecting Mailboxes & ACLs with `doveadm`

```bash
# List all mailboxes for an agent
docker compose exec mail-server doveadm mailbox list -u terrastella

# Inspect ACL permissions on an agent inbox
docker compose exec mail-server doveadm acl get -u terrastella INBOX

# Check mailbox status and message counts
docker compose exec mail-server doveadm mailbox status -u admin all INBOX
```

### Inspecting Flat-File Maildirs Directly

```bash
# List new incoming messages for the administrator
ls -la data/comms/email/vmail/admin/Maildir/new/

# Read the raw RFC822 headers of the latest email
head -n 25 data/comms/email/vmail/admin/Maildir/new/* | head -n 25
```

### Testing Direct Protocol Delivery (SMTP & IMAP)

```bash
# Test raw SMTP delivery from within the Docker network
docker compose exec mail-server nc 127.0.0.1 25 << 'EOF'
HELO localhost
MAIL FROM:<terrastella@titan.local>
RCPT TO:<admin@titan.local>
DATA
Subject: Direct SMTP Test

This is a test email sent via raw SMTP.
.
QUIT
EOF

# Test IMAP connectivity and authentication
docker compose exec mail-server nc 127.0.0.1 143 << 'EOF'
a1 LOGIN admin@titan.local titan_admin_mail_secret_change_me
a2 LIST "" "*"
a3 LOGOUT
EOF
```

---

## 9. Reactive Inbound Webhooks & Hermes Tool-First Integration (Ticket #164)

### Architectural Paradigm: Tool-First Comms

To prevent LLM split-brain, context runaway, and accidental auto-reply feedback loops, autonomous agents operate under a **Tool-First Model**:
1. **Platform Gateway Disabled**: The default chat auto-reply gateway (`platforms.email.enabled: false`) is strictly disabled.
2. **Doorbell Inbound Wake-Up (Push)**:
   - When an email arrives for any `@titan.local` fleet address, Dovecot Pigeonhole Sieve triggers `/etc/dovecot/sieve/default.sieve` via `sieve_before`.
   - The script uses `vnd.dovecot.pipe` to execute `/usr/lib/dovecot/sieve-pipe/agent-webhook.sh`.
   - `agent-webhook.sh` extracts RFC 822 headers (`To`, `From`, `Subject`, `Message-ID`, `In-Reply-To`, `Date`) into JSON, maps the recipient to the agent's port (`terrastella: 8642`, `marvin: 8643`, `bawtford: 8644`), and dispatches an asynchronous `POST /webhook` to `http://titan-agent-<name>:<port>/webhook`.
   - The agent webhook endpoint responds immediately with `HTTP 200 OK`, logs the event to `/memories/logs/email_inbound.md` (Rule 1 compliant OKF Markdown), and wakes the agent runtime via a background self-post.
3. **Explicit Tool Actions (Pull & Send)**:
   - The agent actively inspects and processes emails using the `titan-mail` toolset:
     - `search_emails(query=..., subject=..., from_addr=..., unread_only=...)`: Queries the IMAP server for matching messages.
     - `read_email(seq_num=..., message_id=...)`: Reads full email body and parses threading metadata (`in_reply_to`, `references`).
     - `send_email(to=..., subject=..., body=..., in_reply_to=..., references=...)`: Sends emails via Postfix SMTP.
4. **Strict Sender Verification**:
   - Every agent is strictly locked to its assigned identity (`{agent_id}@titan.local`). Any attempt to spoof another sender address is immediately rejected with an error before contacting SMTP.

### Automated Verification

Execute the dedicated agent email verification suite:
```bash
./scripts/verify/verify-agent-email.sh
```

