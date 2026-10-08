"""SQS claim-check long-polling consumer."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from brainsos_mail.ingress.claim_check import ClaimCheckMessage, fetch_and_build_email
from brainsos_mail.ingress.config import IngressConfig
from brainsos_mail.ingress.local_injector import LocalMailInjector

logger = logging.getLogger(__name__)


class SqsIngressConsumer:
    """Long-polls SQS ingress queue, downloads approved payloads from S3,

    and injects them into local SMTP.
    """

    def __init__(
        self,
        config: IngressConfig,
        s3_client: Optional[Any] = None,
        sqs_client: Optional[Any] = None,
        injector: Optional[LocalMailInjector] = None,
    ) -> None:
        self.config = config
        self._running = False
        self._stop_event = threading.Event()

        # Initialize AWS clients
        session_kwargs: Dict[str, Any] = {"region_name": self.config.aws_region}
        if self.config.aws_access_key_id and self.config.aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = self.config.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = self.config.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        self.s3_client = s3_client or session.client("s3")
        self.sqs_client = sqs_client or session.client("sqs")

        # Initialize local mail injector
        self.injector = injector or LocalMailInjector(
            host=self.config.local_smtp_host,
            port=self.config.local_smtp_port,
        )

    def process_message(self, message: Dict[str, Any]) -> bool:
        """Processes a single SQS message:

        1. Parses claim-check JSON from message Body.
        2. Fetches approved payload from S3 and builds RFC 822 EmailMessage.
        3. Delivers via local SMTP injector.
        4. On success: deletes SQS message and deletes approved S3 object.
        """
        receipt_handle = message.get("ReceiptHandle")
        body_raw = message.get("Body", "")

        try:
            body_dict = json.loads(body_raw)
            claim_check = ClaimCheckMessage.model_validate(body_dict)
        except Exception as exc:
            logger.error(
                "Invalid claim-check payload format in SQS message: %s. Body: %s",
                exc,
                body_raw,
            )
            return False

        logger.info(
            "Processing claim-check for messageId=%s from=%s to=%s (s3://%s/%s)",
            claim_check.message_id,
            claim_check.from_address,
            claim_check.to_address,
            claim_check.s3_bucket,
            claim_check.s3_key,
        )

        try:
            # 1. Fetch from S3 and construct RFC 822 MIME
            email_msg = fetch_and_build_email(self.s3_client, claim_check)

            # 2. Inject to local SMTP
            injected = self.injector.inject(email_msg)
            if not injected:
                logger.warning(
                    "Local SMTP injection failed for messageId=%s; leaving message in SQS for retry",
                    claim_check.message_id,
                )
                return False

            # 3. Delete from SQS upon verified local delivery
            if receipt_handle and self.config.sqs_queue_url:
                self.sqs_client.delete_message(
                    QueueUrl=self.config.sqs_queue_url,
                    ReceiptHandle=receipt_handle,
                )
                logger.info(
                    "Acknowledged and deleted messageId=%s from SQS queue",
                    claim_check.message_id,
                )

            # 4. Delete approved object from S3
            if self.config.delete_s3_on_success:
                try:
                    self.s3_client.delete_object(
                        Bucket=claim_check.s3_bucket,
                        Key=claim_check.s3_key,
                    )
                    logger.info(
                        "Cleaned up approved S3 payload: s3://%s/%s",
                        claim_check.s3_bucket,
                        claim_check.s3_key,
                    )
                except Exception as s3_err:
                    logger.warning("Failed to delete approved S3 payload (non-fatal): %s", s3_err)

            return True

        except (ClientError, BotoCoreError) as aws_err:
            logger.error("AWS error processing messageId=%s: %s", claim_check.message_id, aws_err)
            return False
        except Exception as exc:
            logger.error(
                "Unexpected error processing messageId=%s: %s",
                claim_check.message_id,
                exc,
                exc_info=True,
            )
            return False

    def poll_once(self) -> int:
        """Polls SQS once and processes all received messages.

        Returns number of successfully processed messages.
        """
        if not self.config.sqs_queue_url:
            logger.warning("Cannot poll SQS: sqs_queue_url is not configured")
            return 0

        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.config.sqs_queue_url,
                MaxNumberOfMessages=self.config.max_messages,
                WaitTimeSeconds=self.config.poll_wait_seconds,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("Error receiving messages from SQS (%s): %s", self.config.sqs_queue_url, exc)
            self._stop_event.wait(timeout=5.0)
            return 0

        messages = response.get("Messages", [])
        if not messages:
            return 0

        logger.info("Received %d message(s) from SQS", len(messages))
        success_count = 0
        for msg in messages:
            if self.process_message(msg):
                success_count += 1

        return success_count

    def stop(self) -> None:
        """Signals the consumer loop to terminate gracefully."""
        self._running = False
        self._stop_event.set()

    def run(self) -> None:
        """Runs the consumer daemon loop until stopped via signal or stop()."""
        self._running = True
        logger.info(
            "Starting brainsOS-mail SQS Ingress Consumer daemon (queue: %s, smtp: %s:%d)...",
            self.config.sqs_queue_url,
            self.config.local_smtp_host,
            self.config.local_smtp_port,
        )

        def _handle_signal(signum: int, frame: Any) -> None:
            logger.info("Received termination signal %d. Shutting down gracefully...", signum)
            self.stop()

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            # Not in main thread or unsupported platform
            pass

        if not self.config.sqs_queue_url:
            logger.warning(
                "sqs_queue_url is not configured. Inbound email ingress consumer will not run. Exiting.",
            )
            self._running = False
            return

        while self._running and not self._stop_event.is_set():
            try:
                count = self.poll_once()
                if count == 0 and self.config.poll_wait_seconds == 0:
                    self._stop_event.wait(timeout=1.0)
            except Exception as exc:
                logger.error("Unhandled error in consumer polling loop: %s", exc, exc_info=True)
                self._stop_event.wait(timeout=5.0)

        self._running = False
        logger.info("brainsOS-mail SQS Ingress Consumer daemon stopped.")
