"""Configuration schema for external email ingress."""

from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pydantic import BaseModel, Field


class IngressConfig(BaseModel):
    """Configuration for SQS claim-check consumer and local SMTP injector."""

    aws_region: str = Field(
        default_factory=lambda: os.getenv("AWS_REGION")
        or os.getenv("BRAINSOS_INFRA_AWS_REGION")
        or "us-east-1",
        description="AWS Region for SQS and S3 clients",
    )
    sqs_queue_url: str = Field(
        default_factory=lambda: os.getenv("INGRESS_QUEUE_URL", ""),
        description="AWS SQS Inbound Queue URL",
    )
    s3_bucket: str = Field(
        default_factory=lambda: os.getenv("INGRESS_BUCKET_NAME")
        or os.getenv("INGRESS_S3_BUCKET")
        or "",
        description="Default S3 bucket for approved emails",
    )
    local_smtp_host: str = Field(
        default_factory=lambda: os.getenv("LOCAL_SMTP_HOST")
        or os.getenv("MAIL_SMTP_HOST")
        or "127.0.0.1",
        description="Local Postfix/SMTP server hostname or IP",
    )
    local_smtp_port: int = Field(
        default_factory=lambda: int(
            os.getenv("LOCAL_SMTP_PORT")
            or os.getenv("MAIL_SMTP_PORT")
            or 25
        ),
        description="Local Postfix/SMTP server port (e.g. 25 or 10025)",
    )
    poll_wait_seconds: int = Field(
        default_factory=lambda: int(os.getenv("INGRESS_POLL_WAIT_SECONDS") or 20),
        description="SQS long-polling wait time in seconds (max 20)",
    )
    max_messages: int = Field(
        default_factory=lambda: int(os.getenv("INGRESS_MAX_MESSAGES") or 5),
        description="Maximum SQS messages to receive per batch (1-10)",
    )
    aws_access_key_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("INGRESS_AWS_ACCESS_KEY_ID")
        or os.getenv("AWS_ACCESS_KEY_ID"),
        description="Optional explicit AWS Access Key ID",
    )
    aws_secret_access_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("INGRESS_AWS_SECRET_ACCESS_KEY")
        or os.getenv("AWS_SECRET_ACCESS_KEY"),
        description="Optional explicit AWS Secret Access Key",
    )
    delete_s3_on_success: bool = Field(
        default=True,
        description="Whether to delete the approved S3 object after successful local SMTP delivery",
    )
