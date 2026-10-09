#!/usr/bin/env bash
# ==============================================================================
# brainsOS: Email -> Agent Run -> Reply End-to-End Verification (Ticket #295)
#
# Sends one real email from the admin mailbox to an agent and verifies:
#   1. Exactly ONE threaded reply arrives (In-Reply-To = sent Message-ID), with
#      no duplicate within a grace window.
#   2. The reply is a result or a failure email, as expected (--expect).
#   3. The reply never contains raw infrastructure errors (429 / litellm / tracebacks).
#   4. Langfuse has the thread's session with the worker "email-run" trace, Hermes
#      "Hermes turn" traces and LiteLLM generation traces (warn-only if absent).
#
# Usage:
#   ./scripts/verify/verify-email-runs.sh [--agent bawtford] [--to addr]
#        [--body "text"] [--timeout 900] [--expect completed|failure|any]
#
# Requires the control plane running (./scripts/control/start-control-plane.sh start).
# Rule 8 (script-driven) & Rule 13 (.env precondition) compliant.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

if [ ! -f "${REPO_ROOT}/.env" ]; then
  log_error "Precondition Failed (Rule 13): no .env in repository root. Aborting."
  exit 1
fi
set -a
# shellcheck disable=SC1091
. "${REPO_ROOT}/.env"
set +a

AGENT="bawtford"
TO_ADDR=""
BODY="Reply with one short sentence confirming you received this test email."
TIMEOUT=900
EXPECT="completed"
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    --to) TO_ADDR="$2"; shift 2 ;;
    --body) BODY="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --expect) EXPECT="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) log_error "Unknown argument: $1"; exit 2 ;;
  esac
done

ADMIN_EMAIL="${BRAINSOS_ADMIN_EMAIL:?BRAINSOS_ADMIN_EMAIL not set}"
[ -z "${TO_ADDR}" ] && TO_ADDR="${AGENT}@${ADMIN_EMAIL#*@}"

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
[ -x "${PYTHON_BIN}" ] || PYTHON_BIN="python3"
export PYTHONPATH="${REPO_ROOT}/packages/brainsOS-mail:${REPO_ROOT}/packages/brainsOS-agent:${REPO_ROOT}/packages/brainsOS-queue:${PYTHONPATH:-}"

log_info "Sending test email ${ADMIN_EMAIL} -> ${TO_ADDR} (expect=${EXPECT}, timeout=${TIMEOUT}s)"

set +e
"${PYTHON_BIN}" - "${AGENT}" "${TO_ADDR}" "${BODY}" "${TIMEOUT}" "${EXPECT}" <<'PY'
import imaplib
import os
import re
import sys
import time
from email import message_from_bytes, policy

import httpx
from brainsos_agent.mail_runs import canonical_session_id
from brainsos_mail.client import BrainsOSMailClient

agent, to_addr, body, timeout, expect = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
admin, password = os.environ["BRAINSOS_ADMIN_EMAIL"], os.environ["BRAINSOS_ADMIN_PASSWORD"]

client = BrainsOSMailClient.from_env()
client.username, client.password = admin, password
subject = f"[verify-295] {agent} run check {time.strftime('%H:%M:%S')}"
msg_id = client.send_mail(to=to_addr, subject=subject, body=body, from_addr=admin, sync_imap=False)
print(f"[INFO] Sent Message-ID {msg_id}")
started = time.time()


def find_replies():
    with imaplib.IMAP4(client.imap_host, client.imap_port) as imap:
        imap.login(admin, password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, "HEADER", "In-Reply-To", msg_id.strip("<>"))
        ids = data[0].split() if status == "OK" and data and data[0] else []
        replies = []
        for i in ids:
            _, fetched = imap.fetch(i, "(RFC822)")
            replies.append(message_from_bytes(fetched[0][1], policy=policy.default))
        return replies


replies = []
while time.time() - started < timeout:
    replies = find_replies()
    if replies:
        break
    time.sleep(10)
elapsed = time.time() - started
if not replies:
    print(f"[ERROR] No reply within {timeout}s")
    sys.exit(1)
print(f"[INFO] First reply after {elapsed:.0f}s; waiting 30s grace window for duplicates...")
time.sleep(30)
replies = find_replies()

failed = False
if len(replies) != 1:
    print(f"[ERROR] Expected exactly 1 reply, got {len(replies)}")
    failed = True
reply = replies[0]
plain_body = reply.get_body(preferencelist=("plain",))
text = plain_body.get_content().strip() if plain_body else ""
html_part = reply.get_body(preferencelist=("html",))
has_html = html_part is not None
is_failure = "What you can do:" in text
has_chain = ("wrote:" in text and ">" in text)
print(f"[INFO] Reply from {reply['From']} subject={reply['Subject']!r} has_html={has_html} has_chain={has_chain} failure_email={is_failure}")
print("---- reply plain body (first 600 chars) ----\n" + text[:600] + "\n--------------------------------------")
if html_part:
    html_text = html_part.get_content().strip()
    print("---- reply html body (first 400 chars) ----\n" + html_text[:400] + "\n--------------------------------------")
if re.search(r"(litellm|RateLimitError|max_parallel_requests|Traceback|HTTP 429)", text, re.I):
    print("[ERROR] Reply leaks raw infrastructure error text")
    failed = True
if not has_html:
    print("[WARN] Reply does not contain a text/html alternative part")
if expect == "completed" and is_failure:
    print("[ERROR] Expected a result, got a failure email")
    failed = True
if expect == "failure" and not is_failure:
    print("[ERROR] Expected a failure email, got a result")
    failed = True

# Langfuse session check (warn-only: ingestion is asynchronous)
session_id = canonical_session_id(agent, msg_id)
pk, sk = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
if pk and sk:
    base = os.getenv("BRAINSOS_LANGFUSE_URL") or f"http://127.0.0.1:{os.getenv('LANGFUSE_PORT', '3001')}"
    names: list[str] = []
    for _ in range(6):
        try:
            r = httpx.get(f"{base}/api/public/traces", params={"sessionId": session_id, "limit": 100},
                          auth=(pk, sk), timeout=10)
            names = [t.get("name") or "" for t in r.json().get("data", [])]
        except Exception as e:  # pragma: no cover
            print(f"[WARN] Langfuse query failed: {e}")
        if any(n.startswith("email-run") for n in names):
            break
        time.sleep(10)
    print(f"[INFO] Langfuse session {session_id}: {len(names)} traces")
    for label, pred in (("email-run", lambda n: n.startswith("email-run")),
                        ("Hermes turn", lambda n: n == "Hermes turn"),
                        ("LiteLLM generation", lambda n: n.startswith("litellm"))):
        count = sum(1 for n in names if pred(n))
        print(f"[{'INFO' if count else 'WARN'}]   {label}: {count}")
else:
    print("[WARN] Langfuse keys not set; skipping session check")

sys.exit(1 if failed else 0)
PY
rc=$?
set -e
if [ "${rc}" -eq 0 ]; then
  log_success "Email -> run -> reply verified for ${AGENT}."
else
  log_error "Email -> run -> reply verification FAILED for ${AGENT}."
fi
exit "${rc}"
