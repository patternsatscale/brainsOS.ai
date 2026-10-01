"""CLI daemon for brainsOS-mail external email ingress."""

from __future__ import annotations

import argparse
import logging
import sys

from brainsos_mail.ingress.config import IngressConfig
from brainsos_mail.ingress.sqs_consumer import SqsIngressConsumer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="brainsos-mail-ingress",
        description="brainsOS: SQS Claim-Check Inbound Email Consumer & Local Injector",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll SQS queue once for available messages and exit immediately",
    )
    parser.add_argument(
        "--poll-wait",
        type=int,
        default=None,
        help="SQS long-poll wait time in seconds (default: 20)",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Maximum SQS messages to retrieve per batch (default: 5)",
    )
    parser.add_argument(
        "--smtp-host",
        type=str,
        default=None,
        help="Local Postfix/SMTP host (default: from env or 127.0.0.1)",
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=None,
        help="Local Postfix/SMTP port (default: from env or 25)",
    )
    parser.add_argument(
        "--queue-url",
        type=str,
        default=None,
        help="AWS SQS Inbound Queue URL override",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help="AWS S3 Ingress Bucket override",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="AWS Region override",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    # Base configuration from environment
    config = IngressConfig()

    # Apply CLI overrides if provided
    if args.poll_wait is not None:
        config.poll_wait_seconds = args.poll_wait
    if args.max_messages is not None:
        config.max_messages = args.max_messages
    if args.smtp_host is not None:
        config.local_smtp_host = args.smtp_host
    if args.smtp_port is not None:
        config.local_smtp_port = args.smtp_port
    if args.queue_url is not None:
        config.sqs_queue_url = args.queue_url
    if args.bucket is not None:
        config.s3_bucket = args.bucket
    if args.region is not None:
        config.aws_region = args.region

    consumer = SqsIngressConsumer(config=config)

    if args.once:
        processed = consumer.poll_once()
        logging.getLogger(__name__).info("Finished single poll batch; processed %d messages.", processed)
        return 0

    consumer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
