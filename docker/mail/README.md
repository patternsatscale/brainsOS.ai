# brainsOS: Lightweight Internal Email Subsystem (`docker/mail`)

This directory contains the container definitions, service configurations, and architectural specifications for brainsOS's **Internal Email & Shared Mailbox Subsystem** (Layer 7: Communications Plane).

---

## 1. Architectural Overview & Design Philosophy

In an autonomous multi-agent operating environment, human-agent and agent-to-agent collaboration face critical challenges when relying strictly on synchronous REST APIs, WebSocket streams, or terminal logs:

1. **Thread Blocking & Token Waste**: When an agent requires human review (e.g. approving a website deploy, database migration, or external API action), keeping a synchronous process active or polling an LLM completion loop wastes GPU inference tokens and exhausts CPU cycles.
2. **Context Window Saturation**: Polling an LLM repeatedly to ask "Has the operator responded yet?" consumes valuable context memory and saturates the unified memory bus.
3. **Observability Fragmentation**: Console outputs and Docker logs are ephemeral, messy, and difficult to audit historically.

### The Solution: Asynchronous Email Network with Shared Mailboxes

brainsOS deploys a private, ultra-lightweight email system engineered specifically for edge AI appliances:
* **Dedicated Agent Mailboxes**: Every agent (`operator@brainsos.local`, `terrastella@brainsos.local`, `bawtford@brainsos.local`, `marvin@brainsos.local`) has a native Maildir inbox.
* **Human-in-the-Loop (HITL) Asynchronous Briefs**: Agents dispatch RFC-compliant emails to `admin@brainsos.local` with markdown-formatted briefs, preview URLs, and actionable decision points.
* **The Unified Admin Cockpit (SOGo Groupware)**: The human operator logs into a modern groupware interface (**SOGo**) once. All agent mailboxes are dynamically mapped into the admin's sidebar under an `Agent Fleet` namespace (e.g., `Agent Fleet / Terrastella`, `Agent Fleet / Bawtford`). The operator inspects agent reports, reviews sent drafts, inspects CalDAV calendars, and schedules tasks via calendar invites.
* **Strict Multi-Tenant Isolation (Rule 9)**: Individual agents authenticate with Dovecot and have access *only* to their own personal Maildir. Cross-agent inspection or reading the administrator's mailbox is blocked at the IMAP protocol layer via RFC 4314 ACLs.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   AGENT PLANE                                          │
│                                                                                        │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │   Terrastella   │    │    Bawtford     │    │     Marvin      │    │  Operator   │  │
│  │ (Agent Sandbox) │    │ (Agent Sandbox) │    │ (Agent Sandbox) │    │ Receptionist│  │
│  │ [brainsos-queue]│    │ [brainsos-queue]│    │ [brainsos-queue]│    │ [brainsos-q]│  │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘    └──────┬──────┘  │
└───────────┼──────────────────────┼──────────────────────┼────────────────────┼─────────┘
            │                      │                      │                    │
            │ (Internal SMTP :25 / IMAP :143 via Docker network: brainsos-internal)    │
            ▼                      ▼                      ▼                    ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        MAIL SERVER CONTAINER (brainsos-net-mail-server)                │
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
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   GROUPWARE CONTAINER: SOGo (brainsos-net-sogo)                        │
│                                                                                        │
│  - IMAP Client: Accesses admin@brainsos.local + shared Agent Fleet namespaces          │
│  - CalDAV / CardDAV: Multi-agent calendar scheduling & task orchestration              │
│  - Dedicated Isolated DB: brainsos-sogo-db (PostgreSQL 16, Rule 6 strictly enforced)  │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                       INGRESS REVERSE PROXY (brainsos-net-caddy)                       │
│                                                                                        │
│  - Virtual Hosts: mail.localhost, mail.brainsos.local -> sogo:20000 (/ -> /SOGo)       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### A. Postfix 3.9 (MTA)
Rather than deploying heavyweight enterprise mail servers (which routinely consume 500 MB to 1 GB+ RAM due to embedded anti-spam scanners, anti-virus daemons, and bloated database engines), brainsOS combines **Alpine Postfix** and **Dovecot** in a single, unprivileged container:
* **Port Bindings**:
  * `25` (Standard SMTP): Open to the internal Docker network (`brainsos-internal`) for local container dispatch.
  * `587` (Submission): Authenticated submission via Dovecot SASL.
* **Modern Storage**: Configured with **LMDB** (`virtual_mailbox_maps = lmdb:/etc/mail-brainsos/vmailbox`), completely avoiding deprecated Berkeley DB hash dependencies on modern Alpine distributions.
* **Handoff**: Directly hands off incoming messages to Dovecot LMTP on `127.0.0.1:24`.

### B. Dovecot 2.3 (MDA & IMAP)
* **Authentication**: File-based passdb (`/etc/mail-brainsos/users`) with encrypted or plaintext schemes—requiring zero external database dependencies.
* **Storage Engine**: Native `Maildir` layout with mmap indexing (`dovecot.index`), ensuring instant header parsing and thread search without persistent SQL indexing.
* **Shared Namespaces**: Exposes `Agent Fleet/<agent>/` to the administrator mailbox.
* **ACL Enforcement**: Enforces RFC 4314 access control lists prohibiting agents from expunging messages.
* **Extension Hook**: Script `/usr/lib/dovecot/sieve-pipe/agent-webhook.sh` pipes incoming email metadata to target agent containers (`http://brainsos-agent-<name>:<port>/webhook`) to wake agents up asynchronously.

### C. SOGo Groupware
* **Role**: Modern, web-based groupware cockpit for operator oversight, CalDAV task planning, and email communications.
* **Image**: Built natively on ARM64 packaging SOGo 5.8.0, local memcached, and PostgreSQL driver.
* **Database Isolation (Rule 6)**: SOGo persistence is hosted exclusively in `brainsos-sogo-db` (`postgres:16-alpine`), completely isolated from `brainsos-infra-litellm-db`.
* **Pre-Seeded Profiles**: Automatically configured with domain settings for `brainsos.local` (IMAP: `mail-server:143`, SMTP: `mail-server:25`, STARTTLS disabled internally).
* **Private Cockpit**: Mapped via Caddy reverse proxy on `mail.localhost` and `mail.brainsos.local`.

---

## 3. Shared Mailbox Architecture & Multi-Tenant Access Control

### How the Shared Namespace Works

Dovecot is configured with two distinct namespaces in [`dovecot/dovecot.conf`](file:///docker/mail/dovecot/dovecot.conf):

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
doveadm acl set -u <agent_user> INBOX user=admin@brainsos.local lookup read write write-seen write-deleted insert post expunge admin
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

1. **Operator Experience (`admin@brainsos.local`)**:
   - Logs into SOGo once.
   - The left sidebar renders:
     * `INBOX` (Personal admin mailbox)
     * `Agent Fleet`
       * `operator`
       * `terrastella`
       * `bawtford`
       * `marvin`
   - Clicking any agent folder instantly lists their messages. The admin can read agent reports, view sent items, delete unwanted messages, and reply with instructions.

2. **Agent Experience (`terrastella@brainsos.local`, etc.)**:
   - Authenticates over IMAP using container credentials.
   - Has **zero ACL rights** to `admin@brainsos.local` or any peer agent mailboxes.
   - Attempting to inspect `Agent Fleet` or another agent's Maildir triggers an immediate RFC error: `NO [b"Mailbox doesn't exist"]`.
   - Cannot set `\Deleted` flag or call `EXPUNGE` on their own inbox.
   - Agents operate strictly within their append/read/flag partition.

---

## 4. Hardware Serialization & Resource Budget (Rule 3)

brainsOS is designed to operate on edge appliances with unified memory architectures (ASUS Ascent GX10 GB10 appliance and Apple Silicon workstations). In unified memory systems, background daemons that trigger excessive memory bus traffic or hog RAM degrade LLM inference throughput:

| Component | Container Name | Runtime Engine | Idle RAM | Architecture |
|---|---|---|---|---|
| **Mail Server** | `brainsos-net-mail-server` | Alpine 3.20 (Postfix + Dovecot C daemons) | **~11.5 MiB** | Native ARM64 |
| **Combined Stack** | Postfix + Dovecot + SOGo | Complete Email & Groupware Subsystem | **~85 MiB** | **PASSED (< 100 MB target)** |

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

## 6. Standalone Python Agent Client (`packages/brainsOS-mail`)

Agent containers interact with the mail server via the zero-dependency Python package located at [`packages/brainsOS-mail/`](file:///packages/brainsOS-mail/):

```python
from brainsos_mail import BrainsOSMailClient

# 1. Initialize client using container environment variables
# (BRAINSOS_MAIL_SMTP_HOST, BRAINSOS_MAIL_IMAP_HOST, AGENT_MAIL_USER, AGENT_MAIL_PASSWORD)
client = BrainsOSMailClient.from_env()

# 2. Dispatch an RFC-compliant briefing email to the operator
msg_id = client.send_mail(
    to="admin@brainsos.local",
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

## 7. Operations, Diagnostics & Troubleshooting Handbook

### Common Operational Commands

```bash
# 1. Provision mail directories, seed accounts, and build container
./scripts/setup/setup-mail.sh

# 2. Start the mail stack via Docker Compose
docker compose up -d mail-server sogo

# 3. Restart Caddy to bind mail hostnames
docker compose restart caddy

# 4. View real-time mail server logs
docker compose logs -f mail-server

# 5. Execute the automated verification suite
./scripts/verify/verify-mail.sh

# 6. Execute Python mail client unit tests
PYTHONPATH=packages/brainsOS-mail python3 -m unittest discover packages/brainsOS-mail/tests
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

### Testing Direct Protocol Delivery (SMTP & IMAP)

```bash
# Test raw SMTP delivery from within the Docker network
docker compose exec mail-server nc 127.0.0.1 25 << 'EOF'
HELO localhost
MAIL FROM:<terrastella@brainsos.local>
RCPT TO:<admin@brainsos.local>
DATA
Subject: Direct SMTP Test

This is a test email sent via raw SMTP.
.
QUIT
EOF

# Test IMAP connectivity and authentication
docker compose exec mail-server nc 127.0.0.1 143 << 'EOF'
a1 LOGIN admin@brainsos.local admin_secret_pass
a2 LIST "" "*"
a3 LOGOUT
EOF
```

---

## 8. Reactive Inbound Webhooks & Hermes Tool-First Integration

### Architectural Paradigm: Tool-First Comms

To prevent LLM split-brain, context runaway, and accidental auto-reply feedback loops, autonomous agents operate under a **Tool-First Model**:
1. **Platform Gateway Disabled**: The default chat auto-reply gateway (`platforms.email.enabled: false`) is strictly disabled.
2. **Doorbell Inbound Wake-Up (Push)**:
   - When an email arrives for any `@brainsos.local` fleet address, Dovecot Pigeonhole Sieve triggers `/etc/dovecot/sieve/default.sieve` via `sieve_before`.
   - The script uses `vnd.dovecot.pipe` to execute `/usr/lib/dovecot/sieve-pipe/agent-webhook.sh`.
   - `agent-webhook.sh` extracts RFC 822 headers (`To`, `From`, `Subject`, `Message-ID`, `In-Reply-To`, `Date`) into JSON, maps the recipient to the agent's port (`terrastella: 8642`, `marvin: 8643`, `bawtford: 8644`), and dispatches an asynchronous `POST /webhook` to `http://brainsos-agent-<name>:<port>/webhook`.
   - The agent webhook endpoint responds immediately with `HTTP 200 OK`, logs the event to `/memories/logs/email_inbound.md` (Rule 1 compliant OKF Markdown), and wakes the agent runtime via a background self-post.
3. **Explicit Tool Actions (Pull & Send)**:
   - The agent actively inspects and processes emails using the `brainsos-mail` toolset:
     - `search_emails(query=..., subject=..., from_addr=..., unread_only=...)`: Queries the IMAP server for matching messages.
     - `read_email(seq_num=..., message_id=...)`: Reads full email body and parses threading metadata (`in_reply_to`, `references`).
     - `send_email(to=..., subject=..., body=..., in_reply_to=..., references=...)`: Sends emails via Postfix SMTP.
4. **Strict Sender Verification**:
   - Every agent is strictly locked to its assigned identity (`{agent_id}@brainsos.local`). Any attempt to spoof another sender address is immediately rejected with an error before contacting SMTP.

### Automated Verification

Execute the dedicated agent email verification suite:
```bash
./scripts/verify/verify-agent-email.sh
```
