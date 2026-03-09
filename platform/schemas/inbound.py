"""Inbound gateway message schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserInfo(BaseModel):
    """User information from inbound message source."""

    id: str
    username: str | None = None
    display_name: str | None = None


class InboundSource(BaseModel):
    """Source information for inbound message."""

    protocol: str
    chat_id: str
    message_id: str = ""
    reply_to_message_id: str | None = None
    from_: UserInfo | None = Field(None, alias="from")

    model_config = ConfigDict(populate_by_name=True)


class InboundAttachment(BaseModel):
    """Attachment in inbound message."""

    filename: str
    mime_type: str
    size_bytes: int = 0
    download_url: str = ""


class GatewayInboundMessage(BaseModel):
    """Inbound message from gateway webhook."""

    route: dict
    credential_id: str
    source: InboundSource
    text: str
    attachments: list[InboundAttachment] = []
    timestamp: str
    extra_data: dict | None = None
