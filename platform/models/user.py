"""User and API key models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    first_name: Mapped[str] = mapped_column(String(150), default="")
    last_name: Mapped[str] = mapped_column(String(150), default="")
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    github_username: Mapped[str] = mapped_column(String(255), default="")
    gitlab_username: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Agent user fields
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    api_key: Mapped[APIKey | None] = relationship("APIKey", back_populates="user", uselist=False)
    credentials: Mapped[list] = relationship("BaseCredential", back_populates="user_profile")
    created_by_agent: Mapped[UserProfile | None] = relationship(
        "UserProfile", remote_side="UserProfile.id", foreign_keys=[created_by_agent_id]
    )

    def __repr__(self):
        return f"<UserProfile {self.username} (tg:{self.telegram_user_id})>"


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        __import__("sqlalchemy").ForeignKey("user_profiles.id", ondelete="CASCADE"),
        unique=True,
    )
    key: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[UserProfile] = relationship("UserProfile", back_populates="api_key")

    def __repr__(self):
        return f"<APIKey for user_id={self.user_id}>"
