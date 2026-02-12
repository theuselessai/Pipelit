"""WorkflowExecution, ExecutionLog, and PendingTask models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    execution_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    trigger_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_nodes.id", ondelete="SET NULL"), nullable=True
    )
    parent_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_executions.execution_id", ondelete="SET NULL"), nullable=True
    )
    parent_node_id: Mapped[str] = mapped_column(String(255), default="")
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))
    thread_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(15), default="pending")
    trigger_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cost tracking
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")  # noqa: F821
    trigger_node: Mapped["WorkflowNode | None"] = relationship("WorkflowNode")  # noqa: F821
    user_profile: Mapped["UserProfile"] = relationship("UserProfile")  # noqa: F821
    logs: Mapped[list["ExecutionLog"]] = relationship(
        "ExecutionLog", back_populates="execution", cascade="all, delete-orphan"
    )
    pending_tasks: Mapped[list["PendingTask"]] = relationship(
        "PendingTask", back_populates="execution", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Execution {self.execution_id} ({self.status})>"


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.execution_id", ondelete="CASCADE")
    )
    node_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(15))
    input: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    execution: Mapped[WorkflowExecution] = relationship("WorkflowExecution", back_populates="logs")

    def __repr__(self):
        return f"<Log {self.node_id} ({self.status})>"


class PendingTask(Base):
    __tablename__ = "pending_tasks"

    task_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.execution_id", ondelete="CASCADE")
    )
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    node_id: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    execution: Mapped[WorkflowExecution] = relationship("WorkflowExecution", back_populates="pending_tasks")
    user_profile: Mapped["UserProfile"] = relationship("UserProfile")  # noqa: F821

    def __repr__(self):
        return f"<PendingTask {self.task_id}>"
