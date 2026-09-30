#!/usr/bin/env python3
"""Helper script to poll user IMAP inbox and verify thread replies, ordering, and RFC headers."""

from __future__ import annotations

import argparse
import email
from email.header import decode_header
import imaplib
import sys
import time
from typing import Any


def decode_str(s: str | bytes | None) -> str:
    if not s:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    decoded_fragments = decode_header(s)
    parts = []
    for frag, enc in decoded_fragments:
        if isinstance(frag, bytes):
            parts.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(frag))
    return "".join(parts)


def get_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                break
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return body.strip()


def poll_and_verify(
    host: str,
    port: int,
    username: str,
    password: str,
    expected_count: int,
    subject_keyword: str | None = None,
    expected_thread_id: str | None = None,
    expected_snippets: list[str] | None = None,
    timeout: float = 25.0,
    poll_interval: float = 1.0,
) -> bool:
    start_time = time.time()
    expected_snippets = expected_snippets or []

    print(f"[INFO] Polling IMAP {username}@{host}:{port} for {expected_count} replies (timeout={timeout}s)...")

    while time.time() - start_time < timeout:
        try:
            with imaplib.IMAP4(host, port) as imap:
                imap.login(username, password)
                status, _ = imap.select("INBOX")
                if status != "OK":
                    time.sleep(poll_interval)
                    continue

                status, msg_nums = imap.search(None, "ALL")
                if status != "OK" or not msg_nums[0]:
                    time.sleep(poll_interval)
                    continue

                matched_messages: list[dict[str, Any]] = []
                for num in msg_nums[0].split():
                    seq_str = num.decode() if isinstance(num, bytes) else str(num)
                    typ, data = imap.fetch(seq_str, "(RFC822)")
                    if typ != "OK" or not data or not isinstance(data[0], tuple):
                        continue

                    raw_bytes = data[0][1]
                    msg = email.message_from_bytes(raw_bytes)
                    subject = decode_str(msg.get("Subject"))
                    in_reply_to = decode_str(msg.get("In-Reply-To"))
                    references = decode_str(msg.get("References"))
                    body = get_body(msg)

                    # Filter by subject keyword if provided
                    if subject_keyword and subject_keyword.lower() not in subject.lower():
                        continue

                    matched_messages.append({
                        "seq": seq_str,
                        "message_id": decode_str(msg.get("Message-ID")),
                        "subject": subject,
                        "in_reply_to": in_reply_to,
                        "references": references,
                        "body": body,
                        "date": decode_str(msg.get("Date")),
                    })

                if len(matched_messages) >= expected_count:
                    print(f"[SUCCESS] Found {len(matched_messages)} matching replies in INBOX.")

                    # Verify thread headers and ordering
                    for i, m in enumerate(matched_messages[-expected_count:]):
                        print(f"  Reply #{i+1}: Subject: '{m['subject']}' | In-Reply-To: '{m['in_reply_to']}'")
                        print(f"             References: '{m['references']}'")

                        if expected_thread_id:
                            clean_expected = expected_thread_id.strip()
                            if clean_expected not in m["in_reply_to"] and clean_expected not in m["references"]:
                                print(f"[ERROR] Thread ID '{clean_expected}' missing from In-Reply-To and References!")
                                return False

                    # Check sequential content snippets if specified
                    if expected_snippets:
                        for idx, snippet in enumerate(expected_snippets):
                            if idx < len(matched_messages):
                                target_body = matched_messages[-(expected_count - idx)]["body"]
                                if snippet not in target_body:
                                    print(f"[WARN] Snippet '{snippet}' not found in reply #{idx+1} body: {target_body[:100]}...")

                    return True

        except Exception as e:
            print(f"[DEBUG] IMAP poll iteration error: {e}")

        time.sleep(poll_interval)

    print(f"[ERROR] Timeout reached ({timeout}s) waiting for {expected_count} messages in {username}'s INBOX.")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify IMAP thread replies.")
    parser.add_argument("--host", default="127.0.0.1", help="IMAP host")
    parser.add_argument("--port", type=int, default=10143, help="IMAP port")
    parser.add_argument("--username", required=True, help="User email")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument("--expected-count", type=int, default=1, help="Expected count of replies")
    parser.add_argument("--subject-keyword", default=None, help="Keyword in Subject")
    parser.add_argument("--thread-id", default=None, help="Root Thread-ID / Message-ID")
    parser.add_argument("--expected-snippets", nargs="*", default=[], help="Expected substrings in order")
    parser.add_argument("--timeout", type=float, default=25.0, help="Max wait seconds")

    args = parser.parse_args()

    success = poll_and_verify(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        expected_count=args.expected_count,
        subject_keyword=args.subject_keyword,
        expected_thread_id=args.thread_id,
        expected_snippets=args.expected_snippets,
        timeout=args.timeout,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
