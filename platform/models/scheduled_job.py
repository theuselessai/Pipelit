"""ScheduledJob model — self-rescheduling recurring job state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    # Links
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    trigger_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))

    # Schedule config
    interval_seconds: Mapped[int] = mapped_column(Integer)
    total_repeats: Mapped[int] = mapped_column(Integer, default=0)  # 0 = infinite
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)

    # Payload passed to trigger
    trigger_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # State
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | paused | stopped | dead | done
    current_repeat: Mapped[int] = mapped_column(Integer, default=0)
    current_retry: Mapped[int] = mapped_column(Integer, default=0)

    # Tracking
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship("Workflow")  # noqa: F821
    user_profile: Mapped["UserProfile"] = relationship("UserProfile")  # noqa: F821

    def __repr__(self):
        return f"<ScheduledJob {self.id} ({self.status})>"
