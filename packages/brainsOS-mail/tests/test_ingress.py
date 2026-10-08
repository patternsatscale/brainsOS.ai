"""Unit tests for brainsOS-mail ingress submodule."""

import email
import json
import smtplib
from unittest.mock import MagicMock, patch

import pytest
from brainsos_mail.ingress.claim_check import (
    ClaimCheckMessage,
    build_rfc822_message,
)
from brainsos_mail.ingress.cli import main as cli_main
from brainsos_mail.ingress.config import IngressConfig
from brainsos_mail.ingress.local_injector import LocalMailInjector
from brainsos_mail.ingress.sqs_consumer import SqsIngressConsumer


@pytest.fixture
def sample_claim_check_dict():
    return {
        "version": "1.0",
        "messageId": "msg-ingress-12345",
        "s3Bucket": "brainsos-mail-ingress-test",
        "s3Key": "approved/msg-ingress-12345.json",
        "from": "patternsatscale@gmail.com",
        "to": "bawtford@local.brainsos.ai",
        "subject": "System Directive Alpha",
        "timestamp": "2026-10-01T15:30:00Z",
    }


@pytest.fixture
def sample_approved_payload():
    return {
        "version": "1.0",
        "messageId": "msg-ingress-12345",
        "from": "patternsatscale@gmail.com",
        "to": "bawtford@local.brainsos.ai",
        "subject": "System Directive Alpha",
        "timestamp": "2026-10-01T15:30:00Z",
        "body": "<<<EXTERNAL_UNTRUSTED_CONTENT>>>\nPlease review the cluster logs.\n<<</EXTERNAL_UNTRUSTED_CONTENT>>>",
        "securityVerdict": "VERIFIED_OPERATOR",
        "dkimVerdict": "pass",
        "spfVerdict": "pass",
    }


def test_ingress_config_defaults(monkeypatch):
    monkeypatch.setenv("INGRESS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/inbound")
    monkeypatch.setenv("INGRESS_BUCKET_NAME", "brainsos-mail-ingress-stage")
    monkeypatch.setenv("MAIL_SMTP_HOST", "mail-server")
    monkeypatch.setenv("MAIL_SMTP_PORT", "10025")

    config = IngressConfig()
    assert config.sqs_queue_url == "https://sqs.us-east-1.amazonaws.com/123/inbound"
    assert config.s3_bucket == "brainsos-mail-ingress-stage"
    assert config.local_smtp_host == "mail-server"
    assert config.local_smtp_port == 10025
    assert config.poll_wait_seconds == 20
    assert config.max_messages == 5


def test_claim_check_model_validation(sample_claim_check_dict):
    claim_check = ClaimCheckMessage.model_validate(sample_claim_check_dict)
    assert claim_check.message_id == "msg-ingress-12345"
    assert claim_check.s3_bucket == "brainsos-mail-ingress-test"
    assert claim_check.s3_key == "approved/msg-ingress-12345.json"
    assert claim_check.from_address == "patternsatscale@gmail.com"
    assert claim_check.to_address == "bawtford@local.brainsos.ai"
    assert claim_check.subject == "System Directive Alpha"


def test_build_rfc822_message(sample_claim_check_dict, sample_approved_payload):
    claim_check = ClaimCheckMessage.model_validate(sample_claim_check_dict)
    msg = build_rfc822_message(sample_approved_payload, claim_check)

    assert msg["From"] == "patternsatscale@gmail.com"
    assert msg["To"] == "bawtford@local.brainsos.ai"
    assert msg["Subject"] == "System Directive Alpha"
    assert msg["Message-ID"] == "<msg-ingress-12345@brainsos.ingress>"
    assert msg["X-BrainsOS-Security-Verdict"] == "VERIFIED_OPERATOR"
    assert msg["X-BrainsOS-Origin"] == "external-ses"

    body = msg.get_content()
    assert "<<<EXTERNAL_UNTRUSTED_CONTENT>>>" in body
    assert "Please review the cluster logs." in body
    assert "<<</EXTERNAL_UNTRUSTED_CONTENT>>>" in body


def test_local_mail_injector_success():
    injector = LocalMailInjector(host="127.0.0.1", port=10025)
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@local.brainsos.ai"
    msg["Subject"] = "Test"
    msg.set_content("Hello")

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        success = injector.inject(msg)
        assert success is True
        mock_smtp.send_message.assert_called_once_with(
            msg, from_addr="sender@example.com", to_addrs=["recipient@local.brainsos.ai"]
        )


def test_local_mail_injector_failure():
    injector = LocalMailInjector(host="127.0.0.1", port=10025)
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@local.brainsos.ai"

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp.send_message.side_effect = smtplib.SMTPConnectError(421, "Cannot connect")
        mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

        success = injector.inject(msg)
        assert success is False


def test_sqs_consumer_process_message_success(sample_claim_check_dict, sample_approved_payload):
    config = IngressConfig(
        sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123/queue",
        s3_bucket="brainsos-mail-ingress-test",
    )

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps(sample_approved_payload).encode("utf-8"))
    }

    mock_sqs = MagicMock()
    mock_injector = MagicMock()
    mock_injector.inject.return_value = True

    consumer = SqsIngressConsumer(
        config=config,
        s3_client=mock_s3,
        sqs_client=mock_sqs,
        injector=mock_injector,
    )

    sqs_message = {
        "ReceiptHandle": "receipt-handle-abc-123",
        "Body": json.dumps(sample_claim_check_dict),
    }

    result = consumer.process_message(sqs_message)
    assert result is True

    # Verified SMTP injection called
    assert mock_injector.inject.call_count == 1

    # Verified SQS message deleted
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl="https://sqs.us-east-1.amazonaws.com/123/queue",
        ReceiptHandle="receipt-handle-abc-123",
    )

    # Verified S3 approved object deleted
    mock_s3.delete_object.assert_called_once_with(
        Bucket="brainsos-mail-ingress-test",
        Key="approved/msg-ingress-12345.json",
    )


def test_sqs_consumer_process_message_delivery_failure(sample_claim_check_dict, sample_approved_payload):
    config = IngressConfig(
        sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123/queue",
        s3_bucket="brainsos-mail-ingress-test",
    )

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps(sample_approved_payload).encode("utf-8"))
    }

    mock_sqs = MagicMock()
    mock_injector = MagicMock()
    mock_injector.inject.return_value = False  # Injection fails

    consumer = SqsIngressConsumer(
        config=config,
        s3_client=mock_s3,
        sqs_client=mock_sqs,
        injector=mock_injector,
    )

    sqs_message = {
        "ReceiptHandle": "receipt-handle-abc-123",
        "Body": json.dumps(sample_claim_check_dict),
    }

    result = consumer.process_message(sqs_message)
    assert result is False

    # Ensure message is NOT deleted from SQS and NOT deleted from S3
    mock_sqs.delete_message.assert_not_called()
    mock_s3.delete_object.assert_not_called()


def test_sqs_consumer_poll_once(sample_claim_check_dict, sample_approved_payload):
    config = IngressConfig(sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123/queue")

    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps(sample_approved_payload).encode("utf-8"))
    }

    mock_sqs = MagicMock()
    mock_sqs.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "handle-1",
                "Body": json.dumps(sample_claim_check_dict),
            }
        ]
    }

    mock_injector = MagicMock()
    mock_injector.inject.return_value = True

    consumer = SqsIngressConsumer(
        config=config,
        s3_client=mock_s3,
        sqs_client=mock_sqs,
        injector=mock_injector,
    )

    processed_count = consumer.poll_once()
    assert processed_count == 1
    mock_sqs.delete_message.assert_called_once_with(
        QueueUrl="https://sqs.us-east-1.amazonaws.com/123/queue",
        ReceiptHandle="handle-1",
    )


def test_cli_once():
    with patch("brainsos_mail.ingress.cli.SqsIngressConsumer") as mock_consumer_cls:
        mock_instance = MagicMock()
        mock_instance.poll_once.return_value = 2
        mock_consumer_cls.return_value = mock_instance

        exit_code = cli_main(["--once", "--queue-url", "https://sqs.mock/queue", "--smtp-port", "10025"])
        assert exit_code == 0
        mock_instance.poll_once.assert_called_once()


def test_sqs_consumer_unconfigured_queue_url():
    config = IngressConfig(sqs_queue_url="")
    consumer = SqsIngressConsumer(config=config)
    assert consumer.poll_once() == 0


def test_sqs_consumer_run_stops_cleanly_when_unconfigured():
    config = IngressConfig(sqs_queue_url="")
    consumer = SqsIngressConsumer(config=config)
    consumer.stop()
    consumer.run()
    assert consumer._running is False
