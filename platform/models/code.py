"""CodeBlock, version, test, and test run models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class CodeBlock(Base):
    __tablename__ = "code_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(20), default="python")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    file_path: Mapped[str] = mapped_column(String(500), default="")
    published_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_block_versions.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    draft_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_block_versions.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["CodeBlockVersion"]] = relationship(
        "CodeBlockVersion",
        back_populates="code_block",
        foreign_keys="CodeBlockVersion.code_block_id",
        cascade="all, delete-orphan",
    )


class CodeBlockVersion(Base):
    __tablename__ = "code_block_versions"
    __table_args__ = (
        UniqueConstraint("code_block_id", "version_number", name="uq_codeblock_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code_block_id: Mapped[int] = mapped_column(ForeignKey("code_blocks.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64))
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    commit_message: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    git_commit_id: Mapped[int | None] = mapped_column(
        ForeignKey("git_commits.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(10), default="ui")
    status: Mapped[str] = mapped_column(String(15), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    code_block: Mapped[CodeBlock] = relationship(
        "CodeBlock", back_populates="versions", foreign_keys=[code_block_id]
    )


class CodeBlockTest(Base):
    __tablename__ = "code_block_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_block_id: Mapped[int] = mapped_column(ForeignKey("code_blocks.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    input_data: Mapped[dict] = mapped_column(JSON)
    expected_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_error: Mapped[str] = mapped_column(String(500), default="")


class CodeBlockTestRun(Base):
    __tablename__ = "code_block_test_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("code_block_versions.id", ondelete="CASCADE"))
    test_id: Mapped[int] = mapped_column(ForeignKey("code_block_tests.id", ondelete="CASCADE"))
    passed: Mapped[bool] = mapped_column(Boolean)
    actual_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
