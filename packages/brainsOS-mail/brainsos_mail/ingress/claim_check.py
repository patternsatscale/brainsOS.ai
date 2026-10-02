"""Claim-check payload parser and RFC 822 email message builder."""

from __future__ import annotations

import email.utils
import json
import logging
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


def fetch_approved_payload(s3_client: Any, bucket: str, key: str) -> Dict[str, Any]:
    """Downloads and deserializes the approved email JSON payload from S3."""
    logger.info("Fetching approved email payload from s3://%s/%s", bucket, key)
    response = s3_client.get_object(Bucket=bucket, Key=key)
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


def fetch_and_build_email(s3_client: Any, claim_check: ClaimCheckMessage) -> EmailMessage:
    """High-level helper to fetch approved payload and build an RFC 822 EmailMessage."""
    payload = fetch_approved_payload(s3_client, claim_check.s3_bucket, claim_check.s3_key)
    return build_rfc822_message(payload, claim_check)
