"""WorkflowNode, BaseComponentConfig (STI), and WorkflowEdge models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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


# ---------------------------------------------------------------------------
# Component config — single-table inheritance
# ---------------------------------------------------------------------------


class BaseComponentConfig(Base):
    __tablename__ = "component_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    component_type: Mapped[str] = mapped_column(String(30))
    extra_config: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # STI fields — ModelComponentConfig
    llm_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    presence_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_format: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Sub-component FKs — link ai_model config to agent config
    llm_model_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("component_configs.id", ondelete="SET NULL", name="fk_llm_model_config"),
        nullable=True,
    )

    # STI fields — AIComponentConfig
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # STI fields — CodeComponentConfig
    code_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    code_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # STI fields — TriggerComponentConfig
    credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL", name="fk_trigger_credential"),
        nullable=True,
    )
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Discriminator
    __mapper_args__ = {
        "polymorphic_on": "component_type",
        "polymorphic_identity": "__base__",
    }

    # Relationship to credential for trigger configs
    credential: Mapped["BaseCredential | None"] = relationship(  # noqa: F821
        "BaseCredential", foreign_keys=[credential_id]
    )
    llm_credential: Mapped["BaseCredential | None"] = relationship(  # noqa: F821
        "BaseCredential", foreign_keys=[llm_credential_id]
    )

    @property
    def concrete(self):
        """Return self — with STI, self is already the concrete instance."""
        return self

    def __repr__(self):
        return f"<Config({self.component_type})>"


class ModelComponentConfig(BaseComponentConfig):
    """Config for ai_model nodes."""
    __mapper_args__ = {"polymorphic_identity": "ai_model"}


class AIComponentConfig(BaseComponentConfig):
    """Base for AI nodes — uses system_prompt. Multiple identities registered below."""
    __mapper_args__ = {"polymorphic_identity": "agent"}


class _CategorizerConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "categorizer"}


class _RouterConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "router"}


class _ExtractorConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "extractor"}


class _SwitchConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "switch"}


class CodeComponentConfig(BaseComponentConfig):
    """Config for code-type components."""
    __mapper_args__ = {"polymorphic_identity": "code"}


# Register remaining code-type identities
class _LoopConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "loop"}


class _FilterConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "filter"}


class _MergeConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "merge"}


class _WaitConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "wait"}


class _ErrorHandlerConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "error_handler"}


class ToolComponentConfig(BaseComponentConfig):
    """Config for tool-type sub-components."""
    __mapper_args__ = {"polymorphic_identity": "run_command"}


class _HttpRequestConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "http_request"}


class _WebSearchConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "web_search"}


class _CalculatorConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "calculator"}


class _DatetimeConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "datetime"}


class _CreateAgentUserConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "create_agent_user"}


class _PlatformApiConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "platform_api"}


class _WhoamiConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "whoami"}


class _EpicToolsConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "epic_tools"}


class _TaskToolsConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "task_tools"}


class OtherComponentConfig(BaseComponentConfig):
    """Config for human_confirmation, aggregator, workflow, output_parser."""
    __mapper_args__ = {"polymorphic_identity": "human_confirmation"}


class _AggregatorConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "aggregator"}


class _WorkflowConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "workflow"}


class _OutputParserConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "output_parser"}


class _MemoryReadConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "memory_read"}


class _MemoryWriteConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "memory_write"}


class _IdentifyUserConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "identify_user"}


class _CodeExecuteConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "code_execute"}


class TriggerComponentConfig(BaseComponentConfig):
    """Config for trigger nodes."""
    __mapper_args__ = {"polymorphic_identity": "trigger_telegram"}


class _TriggerWebhookConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_webhook"}


class _TriggerScheduleConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_schedule"}


class _TriggerManualConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_manual"}


class _TriggerWorkflowConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_workflow"}


class _TriggerErrorConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_error"}


class _TriggerChatConfig(BaseComponentConfig):
    __mapper_args__ = {"polymorphic_identity": "trigger_chat"}


# Mapping from component_type string to the config class to use for creation
COMPONENT_TYPE_TO_CONFIG: dict[str, type[BaseComponentConfig]] = {
    "ai_model": ModelComponentConfig,
    "agent": AIComponentConfig,
    "categorizer": AIComponentConfig,
    "router": AIComponentConfig,
    "extractor": AIComponentConfig,
    "switch": OtherComponentConfig,
    "code": CodeComponentConfig,
    "loop": CodeComponentConfig,
    "filter": CodeComponentConfig,
    "merge": CodeComponentConfig,
    "wait": CodeComponentConfig,
    "error_handler": CodeComponentConfig,
    "run_command": ToolComponentConfig,
    "http_request": ToolComponentConfig,
    "web_search": ToolComponentConfig,
    "calculator": ToolComponentConfig,
    "datetime": ToolComponentConfig,
    "create_agent_user": ToolComponentConfig,
    "platform_api": ToolComponentConfig,
    "whoami": ToolComponentConfig,
    "epic_tools": ToolComponentConfig,
    "task_tools": ToolComponentConfig,
    "human_confirmation": OtherComponentConfig,
    "aggregator": OtherComponentConfig,
    "workflow": OtherComponentConfig,
    "output_parser": OtherComponentConfig,
    "memory_read": OtherComponentConfig,
    "memory_write": OtherComponentConfig,
    "identify_user": OtherComponentConfig,
    "code_execute": OtherComponentConfig,
    "trigger_telegram": TriggerComponentConfig,
    "trigger_webhook": TriggerComponentConfig,
    "trigger_schedule": TriggerComponentConfig,
    "trigger_manual": TriggerComponentConfig,
    "trigger_workflow": TriggerComponentConfig,
    "trigger_error": TriggerComponentConfig,
    "trigger_chat": TriggerComponentConfig,
}


# ---------------------------------------------------------------------------
# WorkflowNode
# ---------------------------------------------------------------------------


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_id", name="uq_workflow_node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(255))
    component_type: Mapped[str] = mapped_column(String(30))
    component_config_id: Mapped[int] = mapped_column(
        ForeignKey("component_configs.id", ondelete="CASCADE")
    )
    subworkflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    code_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("code_blocks.id", ondelete="SET NULL"), nullable=True
    )
    is_entry_point: Mapped[bool] = mapped_column(Boolean, default=False)
    interrupt_before: Mapped[bool] = mapped_column(Boolean, default=False)
    interrupt_after: Mapped[bool] = mapped_column(Boolean, default=False)
    position_x: Mapped[int] = mapped_column(Integer, default=0)
    position_y: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    workflow: Mapped["Workflow"] = relationship(  # noqa: F821
        "Workflow", back_populates="nodes", foreign_keys=[workflow_id]
    )
    component_config: Mapped[BaseComponentConfig] = relationship(
        "BaseComponentConfig", foreign_keys=[component_config_id]
    )

    def __repr__(self):
        return f"<Node {self.node_id} ({self.component_type})>"


# ---------------------------------------------------------------------------
# WorkflowEdge
# ---------------------------------------------------------------------------


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    source_node_id: Mapped[str] = mapped_column(String(255))
    target_node_id: Mapped[str] = mapped_column(String(255), default="")
    edge_type: Mapped[str] = mapped_column(String(15), default="direct")
    edge_label: Mapped[str] = mapped_column(String(20), default="")
    condition_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    condition_value: Mapped[str] = mapped_column(String(100), default="", server_default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="edges")  # noqa: F821

    def __repr__(self):
        return f"<Edge {self.source_node_id} -> {self.target_node_id}>"
