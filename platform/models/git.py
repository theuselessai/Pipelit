"""Git repository, commit, and sync task models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class GitRepository(Base):
    __tablename__ = "git_repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("git_credentials.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(20))  # github, gitlab, bitbucket
    remote_url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    local_path: Mapped[str] = mapped_column(String(500))
    last_commit_hash: Mapped[str] = mapped_column(String(40), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    commits: Mapped[list["GitCommit"]] = relationship("GitCommit", back_populates="repository", cascade="all, delete-orphan")


class GitCommit(Base):
    __tablename__ = "git_commits"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("git_repositories.id", ondelete="CASCADE"))
    commit_hash: Mapped[str] = mapped_column(String(40), unique=True)
    message: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    committed_at: Mapped[datetime] = mapped_column(DateTime)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    repository: Mapped[GitRepository] = relationship("GitRepository", back_populates="commits")


class GitSyncTask(Base):
    __tablename__ = "git_sync_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("git_repositories.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(10))  # push, pull, both
    status: Mapped[str] = mapped_column(String(15), default="pending")
    commit_message: Mapped[str] = mapped_column(Text, default="")
    commit_hash: Mapped[str] = mapped_column(String(40), default="")
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    error_log: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    triggered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
