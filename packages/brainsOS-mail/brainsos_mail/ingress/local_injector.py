"""Local SMTP injector for delivering RFC 822 messages to local mailboxes."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

logger = logging.getLogger(__name__)


class LocalMailInjector:
    """Injects parsed RFC 822 emails into the local Postfix mail server via SMTP."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 25,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def inject(self, msg: EmailMessage, recipients: Optional[List[str]] = None) -> bool:
        """Sends an EmailMessage via SMTP to local mail server.

        Args:
            msg: The RFC 822 EmailMessage instance.
            recipients: Optional explicit recipients list. If not provided,
                        extracted from msg['To'].

        Returns:
            True if SMTP delivery succeeded, False otherwise.
        """
        from_addr = str(msg.get("From", "ingress@brainsos.local"))
        to_header = str(msg.get("To", ""))

        target_recipients = recipients or [
            addr.strip() for addr in to_header.split(",") if addr.strip()
        ]

        if not target_recipients:
            logger.error("Cannot inject email: No recipient addresses found in message")
            return False

        logger.info(
            "Injecting email from %s to %s via local SMTP %s:%d",
            from_addr,
            target_recipients,
            self.host,
            self.port,
        )

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                smtp.send_message(msg, from_addr=from_addr, to_addrs=target_recipients)
            logger.info("Successfully delivered message <%s> to local SMTP", msg.get("Message-ID"))
            return True
        except (smtplib.SMTPException, OSError) as exc:
            logger.error(
                "Failed to inject email to %s:%d: %s",
                self.host,
                self.port,
                exc,
                exc_info=True,
            )
            return False
