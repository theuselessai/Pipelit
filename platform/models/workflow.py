"""Workflow and WorkflowCollaborator models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("git_repositories.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    is_callable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    forked_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    error_handler_workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    max_execution_seconds: Mapped[int] = mapped_column(Integer, default=600, server_default=text("600"))
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # Relationships
    owner: Mapped["UserProfile"] = relationship("UserProfile", foreign_keys=[owner_id])  # noqa: F821
    error_handler_workflow: Mapped[Workflow | None] = relationship(
        "Workflow", remote_side="Workflow.id", foreign_keys=[error_handler_workflow_id]
    )
    nodes: Mapped[list] = relationship(
        "WorkflowNode", back_populates="workflow", foreign_keys="WorkflowNode.workflow_id",
        cascade="all, delete-orphan",
    )
    edges: Mapped[list] = relationship(
        "WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan"
    )
    collaborators: Mapped[list] = relationship(
        "WorkflowCollaborator", back_populates="workflow", cascade="all, delete-orphan"
    )
    executions: Mapped[list] = relationship(
        "WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Workflow {self.slug}>"


class WorkflowCollaborator(Base):
    __tablename__ = "workflow_collaborators"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(10))  # owner, editor, viewer
    invited_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="collaborators")
    user_profile: Mapped["UserProfile"] = relationship("UserProfile", foreign_keys=[user_profile_id])  # noqa: F821
