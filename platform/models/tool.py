"""Tool definition and mapping models."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ToolDefinition(Base):
    __tablename__ = "tool_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    tool_type: Mapped[str] = mapped_column(String(20))  # web_search, browser, api, custom
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    default_config: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_type: Mapped[str] = mapped_column(String(20), default="")


class WorkflowTool(Base):
    __tablename__ = "workflow_tools"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    tool_definition_id: Mapped[int] = mapped_column(ForeignKey("tool_definitions.id", ondelete="CASCADE"))
    config_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    tool_definition: Mapped[ToolDefinition] = relationship("ToolDefinition")


class ToolCredentialMapping(Base):
    __tablename__ = "tool_credential_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_definition_id: Mapped[int] = mapped_column(ForeignKey("tool_definitions.id", ondelete="CASCADE"))
    tool_credential_id: Mapped[int] = mapped_column(ForeignKey("tool_credentials.id", ondelete="CASCADE"))
    user_profile_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
