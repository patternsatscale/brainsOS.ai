"""Claim-check payload parser and RFC 822 email message builder."""

from __future__ import annotations

import email.utils
import json
import logging
import posixpath
import urllib.parse
from email.message import EmailMessage
from typing import Any, Dict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ClaimCheckMessage(BaseModel):
    """Schema for claim-check messages emitted by Cloud Sanitizer Lambda to SQS."""

    version: str = "1.0"
    message_id: str = Field(alias="messageId")
    s3_bucket: str = Field(alias="s3Bucket")
    s3_key: str = Field(alias="s3Key")
    from_address: str = Field(alias="from")
    to_address: str = Field(alias="to")
    subject: str = ""
    timestamp: str = ""

    model_config = {
        "populate_by_name": True,
    }


_MAX_S3_KEY_UNQUOTE_PASSES = 16


def validate_approved_s3_key(key: str) -> str:
    """Validate that an S3 key strictly targets a non-traversal object under 'approved/'."""
    if not isinstance(key, str) or not key:
        raise ValueError("S3 key must be a non-empty string")

    # Bounded fixed-point URL-decoding catches multi-encoded payloads before policy checks.
    candidates = [key]
    current = key
    for _ in range(_MAX_S3_KEY_UNQUOTE_PASSES):
        decoded = urllib.parse.unquote(current)
        if decoded == current:
            break
        candidates.append(decoded)
        current = decoded
    else:
        if urllib.parse.unquote(current) != current:
            raise ValueError(f"Exceeded max URL-decoding passes in S3 key: {key!r}")

    for candidate in candidates:
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
            raise ValueError(f"Control characters in S3 key: {key!r}")
        if "\\" in candidate or candidate.startswith("/"):
            raise ValueError(f"Unsafe characters or leading slash in S3 key: {key!r}")
        if not candidate.startswith("approved/") or len(candidate) <= len("approved/"):
            raise ValueError(f"S3 key must be under 'approved/': {key!r}")
        segments = candidate.split("/")
        if any(seg in ("", ".", "..") for seg in segments):
            raise ValueError(f"Path traversal or empty segment in S3 key: {key!r}")
        if posixpath.normpath(candidate) != candidate:
            raise ValueError(f"Non-normalized S3 key rejected: {key!r}")

    # Sanitizer emits approved/${messageId}.json with [A-Za-z0-9._-]+; reject '%' altogether.
    if "%" in key:
        raise ValueError(f"Percent-encoded characters not permitted in S3 key: {key!r}")

    return key


def fetch_approved_payload(
    s3_client: Any,
    bucket: str,
    key: str,
    expected_bucket: str | None = None,
) -> Dict[str, Any]:
    """Downloads and deserializes the approved email JSON payload from S3."""
    if (
        not isinstance(bucket, str)
        or not bucket
        or bucket != bucket.strip()
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in bucket)
    ):
        raise ValueError("S3 bucket must be a valid non-empty string")
    if expected_bucket is not None:
        expected = expected_bucket.strip()
        if not expected or expected != expected_bucket or bucket != expected:
            raise ValueError(
                f"S3 bucket mismatch: got {bucket!r}, expected {expected!r}"
            )
    validated_key = validate_approved_s3_key(key)
    logger.info("Fetching approved email payload from s3://%s/%s", bucket, validated_key)
    response = s3_client.get_object(Bucket=bucket, Key=validated_key)
    raw_content = response["Body"].read().decode("utf-8")
    return json.loads(raw_content)


def build_rfc822_message(payload: Dict[str, Any], claim_check: ClaimCheckMessage) -> EmailMessage:
    """Constructs an RFC 822 EmailMessage from approved payload and claim-check."""
    msg = EmailMessage()

    from_addr = payload.get("from") or claim_check.from_address
    to_addr = payload.get("to") or claim_check.to_address
    subject = payload.get("subject") or claim_check.subject
    message_id = payload.get("messageId") or claim_check.message_id
    body = payload.get("body", "")

    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = f"<{message_id}@brainsos.ingress>"
    msg["X-BrainsOS-Security-Verdict"] = payload.get("securityVerdict", "VERIFIED_OPERATOR")
    msg["X-BrainsOS-Origin"] = "external-ses"

    # Set enveloped plain-text body
    msg.set_content(body)

    return msg


def fetch_and_build_email(
    s3_client: Any,
    claim_check: ClaimCheckMessage,
    expected_bucket: str | None = None,
) -> EmailMessage:
    """High-level helper to fetch approved payload and build an RFC 822 EmailMessage."""
    payload = fetch_approved_payload(
        s3_client,
        claim_check.s3_bucket,
        claim_check.s3_key,
        expected_bucket=expected_bucket,
    )
    return build_rfc822_message(payload, claim_check)
