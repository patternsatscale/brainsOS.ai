"""Data models for brainsOS email parsing and transport."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    """MIME attachment contained within an inbound or outbound email."""

    filename: str
    content_type: str
    payload: bytes
    size: int


class ParsedInboundEmail(BaseModel):
    """Cleaned and normalized inbound email payload."""

    message_id: str
    thread_id: str
    sender: str
    recipient: str
    subject: str
    clean_body: str
    raw_mime: bytes
    attachments: list[Attachment] = Field(default_factory=list)
