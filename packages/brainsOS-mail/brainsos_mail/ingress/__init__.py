"""brainsOS-mail Ingress Submodule: SQS Claim-Check Consumer & Local Mail Injector."""

from brainsos_mail.ingress.claim_check import ClaimCheckMessage, fetch_and_build_email
from brainsos_mail.ingress.config import IngressConfig
from brainsos_mail.ingress.local_injector import LocalMailInjector
from brainsos_mail.ingress.sqs_consumer import SqsIngressConsumer

__all__ = [
    "IngressConfig",
    "ClaimCheckMessage",
    "fetch_and_build_email",
    "LocalMailInjector",
    "SqsIngressConsumer",
]
