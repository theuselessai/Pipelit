"""Tests for inbound gateway schemas and auth dependency."""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from config import settings
from schemas.inbound import (
    GatewayInboundMessage,
    InboundAttachment,
    InboundSource,
    UserInfo,
)
from auth import verify_gateway_token


class TestUserInfo:
    """Test UserInfo schema."""

    def test_user_info_valid(self):
        """Valid UserInfo validates correctly."""
        user = UserInfo(id="123", username="alice", display_name="Alice Smith")
        assert user.id == "123"
        assert user.username == "alice"
        assert user.display_name == "Alice Smith"

    def test_user_info_minimal(self):
        """UserInfo with only required id field."""
        user = UserInfo(id="456")
        assert user.id == "456"
        assert user.username is None
        assert user.display_name is None


class TestInboundSource:
    """Test InboundSource schema."""

    def test_inbound_source_valid(self):
        """Valid InboundSource validates correctly."""
        source = InboundSource(
            protocol="telegram",
            chat_id="789",
            message_id="msg_001",
            reply_to_message_id="msg_000",
            **{"from": UserInfo(id="user_1", username="bob")}
        )
        assert source.protocol == "telegram"
        assert source.chat_id == "789"
        assert source.message_id == "msg_001"
        assert source.reply_to_message_id == "msg_000"
        assert source.from_.id == "user_1"

    def test_inbound_source_from_alias(self):
        """'from' field alias works (JSON key maps to from_)."""
        data = {
            "protocol": "telegram",
            "chat_id": "789",
            "from": {"id": "user_1", "username": "bob"}
        }
        source = InboundSource(**data)
        assert source.from_.id == "user_1"
        assert source.from_.username == "bob"

    def test_inbound_source_minimal(self):
        """InboundSource with only required fields."""
        source = InboundSource(protocol="telegram", chat_id="789")
        assert source.protocol == "telegram"
        assert source.chat_id == "789"
        assert source.message_id == ""
        assert source.reply_to_message_id is None
        assert source.from_ is None


class TestInboundAttachment:
    """Test InboundAttachment schema."""

    def test_inbound_attachment_valid(self):
        """Valid InboundAttachment validates correctly."""
        attachment = InboundAttachment(
            filename="document.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            download_url="https://example.com/file.pdf"
        )
        assert attachment.filename == "document.pdf"
        assert attachment.mime_type == "application/pdf"
        assert attachment.size_bytes == 1024
        assert attachment.download_url == "https://example.com/file.pdf"

    def test_inbound_attachment_minimal(self):
        """InboundAttachment with only required fields."""
        attachment = InboundAttachment(
            filename="image.jpg",
            mime_type="image/jpeg"
        )
        assert attachment.filename == "image.jpg"
        assert attachment.mime_type == "image/jpeg"
        assert attachment.size_bytes == 0
        assert attachment.download_url == ""


class TestGatewayInboundMessage:
    """Test GatewayInboundMessage schema."""

    def test_gateway_inbound_message_valid(self):
        """Valid GatewayInboundMessage validates correctly."""
        message = GatewayInboundMessage(
            route={"workflow_slug": "my-workflow", "trigger_node_id": "trigger_123"},
            credential_id="cred_456",
            source=InboundSource(
                protocol="telegram",
                chat_id="789",
                **{"from": UserInfo(id="user_1")}
            ),
            text="Hello world",
            timestamp="2026-03-10T12:00:00Z",
            attachments=[
                InboundAttachment(filename="file.txt", mime_type="text/plain")
            ],
            extra_data={"key": "value"}
        )
        assert message.route["workflow_slug"] == "my-workflow"
        assert message.credential_id == "cred_456"
        assert message.text == "Hello world"
        assert len(message.attachments) == 1
        assert message.extra_data == {"key": "value"}

    def test_gateway_inbound_message_minimal(self):
        """GatewayInboundMessage with only required fields."""
        message = GatewayInboundMessage(
            route={"workflow_slug": "test"},
            credential_id="cred_1",
            source=InboundSource(protocol="telegram", chat_id="123"),
            text="Test",
            timestamp="2026-03-10T12:00:00Z"
        )
        assert message.route == {"workflow_slug": "test"}
        assert message.credential_id == "cred_1"
        assert message.text == "Test"
        assert message.attachments == []
        assert message.extra_data is None

    def test_gateway_inbound_message_missing_route(self):
        """Missing route field raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GatewayInboundMessage(
                credential_id="cred_1",
                source=InboundSource(protocol="telegram", chat_id="123"),
                text="Test",
                timestamp="2026-03-10T12:00:00Z"
            )

    def test_gateway_inbound_message_missing_credential_id(self):
        """Missing credential_id field raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GatewayInboundMessage(
                route={"workflow_slug": "test"},
                source=InboundSource(protocol="telegram", chat_id="123"),
                text="Test",
                timestamp="2026-03-10T12:00:00Z"
            )

    def test_gateway_inbound_message_missing_source(self):
        """Missing source field raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GatewayInboundMessage(
                route={"workflow_slug": "test"},
                credential_id="cred_1",
                text="Test",
                timestamp="2026-03-10T12:00:00Z"
            )

    def test_gateway_inbound_message_missing_text(self):
        """Missing text field raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GatewayInboundMessage(
                route={"workflow_slug": "test"},
                credential_id="cred_1",
                source=InboundSource(protocol="telegram", chat_id="123"),
                timestamp="2026-03-10T12:00:00Z"
            )

    def test_gateway_inbound_message_missing_timestamp(self):
        """Missing timestamp field raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GatewayInboundMessage(
                route={"workflow_slug": "test"},
                credential_id="cred_1",
                source=InboundSource(protocol="telegram", chat_id="123"),
                text="Test"
            )


class TestVerifyGatewayToken:
    """Test verify_gateway_token auth dependency."""

    def test_verify_gateway_token_valid(self):
        """Valid gateway token passes without exception."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=settings.GATEWAY_INBOUND_TOKEN
        )
        # Should not raise
        result = verify_gateway_token(credentials)
        assert result is None

    def test_verify_gateway_token_invalid(self):
        """Invalid gateway token raises 401 HTTPException."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid-token-xyz"
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_gateway_token(credentials)
        assert exc_info.value.status_code == 401
        assert "Invalid gateway token" in exc_info.value.detail
