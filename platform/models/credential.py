"""Credential models — single table with credential_type discriminator columns."""

from __future__ import annotations

import os
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from database import Base

# ---------------------------------------------------------------------------
# Encrypted field type
# ---------------------------------------------------------------------------

_fernet_key = os.environ.get("FIELD_ENCRYPTION_KEY", "")
_fernet = Fernet(_fernet_key.encode()) if _fernet_key else None


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts string values using Fernet."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value and _fernet:
            return _fernet.encrypt(value.encode()).decode()
        return value

    def process_result_value(self, value, dialect):
        if value and _fernet:
            try:
                return _fernet.decrypt(value.encode()).decode()
            except Exception:
                return value
        return value


# ---------------------------------------------------------------------------
# Credential models
# ---------------------------------------------------------------------------


class BaseCredential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    credential_type: Mapped[str] = mapped_column(String(20))  # git, llm, telegram, tool
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user_profile: Mapped["UserProfile"] = relationship("UserProfile", back_populates="credentials")  # noqa: F821

    # One-to-one children
    git_credential: Mapped[GitCredential | None] = relationship(
        "GitCredential", back_populates="base_credentials", uselist=False, cascade="all, delete-orphan"
    )
    llm_credential: Mapped[LLMProviderCredential | None] = relationship(
        "LLMProviderCredential", back_populates="base_credentials", uselist=False, cascade="all, delete-orphan"
    )
    telegram_credential: Mapped[TelegramCredential | None] = relationship(
        "TelegramCredential", back_populates="base_credentials", uselist=False, cascade="all, delete-orphan"
    )
    tool_credential: Mapped[ToolCredential | None] = relationship(
        "ToolCredential", back_populates="base_credentials", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Credential {self.name} ({self.credential_type})>"


class GitCredential(Base):
    __tablename__ = "git_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_credentials_id: Mapped[int] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(20))  # github, gitlab, bitbucket
    credential_type: Mapped[str] = mapped_column(String(20))  # ssh_key, token, app
    ssh_private_key: Mapped[str] = mapped_column(EncryptedString(2000), default="")
    access_token: Mapped[str] = mapped_column(EncryptedString(500), default="")
    username: Mapped[str] = mapped_column(String(255), default="")
    webhook_secret: Mapped[str] = mapped_column(String(255), default="")

    base_credentials: Mapped[BaseCredential] = relationship("BaseCredential", back_populates="git_credential")


class LLMProviderCredential(Base):
    __tablename__ = "llm_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_credentials_id: Mapped[int] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), unique=True
    )
    provider_type: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    api_key: Mapped[str] = mapped_column(EncryptedString(500))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    organization_id: Mapped[str] = mapped_column(String(255), default="")
    custom_headers: Mapped[dict] = mapped_column(JSON, default=dict)

    base_credentials: Mapped[BaseCredential] = relationship("BaseCredential", back_populates="llm_credential")


class TelegramCredential(Base):
    __tablename__ = "telegram_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_credentials_id: Mapped[int] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), unique=True
    )
    bot_token: Mapped[str] = mapped_column(EncryptedString(500))
    allowed_user_ids: Mapped[str] = mapped_column(String(500), default="")

    base_credentials: Mapped[BaseCredential] = relationship("BaseCredential", back_populates="telegram_credential")


class ToolCredential(Base):
    __tablename__ = "tool_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_credentials_id: Mapped[int] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), unique=True
    )
    tool_type: Mapped[str] = mapped_column(String(20))  # searxng, browser, api
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    base_credentials: Mapped[BaseCredential] = relationship("BaseCredential", back_populates="tool_credential")
