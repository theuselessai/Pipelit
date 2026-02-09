"""Epic and Task models for multi-agent delegation."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Epic(Base):
    __tablename__ = "epics"

    id: Mapped[str] = mapped_column(
        String(20), primary_key=True, default=lambda: f"ep-{uuid4().hex[:12]}"
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list | None] = mapped_column(JSON, default=list)

    # Ownership
    created_by_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    user_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(String(20), default="planning", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)

    # Budget
    budget_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    spent_tokens: Mapped[int] = mapped_column(Integer, default=0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    agent_overhead_tokens: Mapped[int] = mapped_column(Integer, default=0)
    agent_overhead_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Progress
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Outcome
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="epic", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Epic {self.id} ({self.status})>"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(20), primary_key=True, default=lambda: f"tk-{uuid4().hex[:12]}"
    )
    epic_id: Mapped[str] = mapped_column(
        ForeignKey("epics.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list | None] = mapped_column(JSON, default=list)

    # Ownership
    created_by_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)

    # Workflow linkage
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workflow_source: Mapped[str] = mapped_column(String(20), default="inline")

    # Dependencies
    depends_on: Mapped[list | None] = mapped_column(JSON, default=list)

    # Requirements
    requirements: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # Cost
    estimated_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_tokens: Mapped[int] = mapped_column(Integer, default=0)
    actual_usd: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_invocations: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Outcome
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)

    # Notes
    notes: Mapped[list | None] = mapped_column(JSON, default=list)

    # Relationships
    epic: Mapped[Epic] = relationship("Epic", back_populates="tasks")

    def __repr__(self):
        return f"<Task {self.id} ({self.status})>"
