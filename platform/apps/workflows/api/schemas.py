from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema

ComponentTypeStr = Literal[
    "categorizer", "router", "chat_model", "react_agent", "plan_and_execute",
    "tool_node", "aggregator", "human_confirmation", "parallel", "workflow",
    "code", "loop", "wait", "merge", "filter", "transform", "sort", "limit",
    "http_request", "error_handler", "output_parser",
]
TriggerTypeStr = Literal[
    "telegram_message", "telegram_chat", "schedule", "webhook", "manual",
    "workflow", "error",
]
EdgeTypeStr = Literal["direct", "conditional"]


# ── Workflow ──────────────────────────────────────────────────────────────────


class WorkflowIn(Schema):
    name: str
    slug: str
    description: str = ""
    is_active: bool = True
    is_public: bool = False
    is_default: bool = False
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None


class WorkflowUpdate(Schema):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    is_default: bool | None = None
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None


class WorkflowOut(Schema):
    id: int
    name: str
    slug: str
    description: str
    is_active: bool
    is_public: bool
    is_default: bool
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    node_count: int = 0
    edge_count: int = 0
    trigger_count: int = 0
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_node_count(obj):
        return obj.nodes.count()

    @staticmethod
    def resolve_edge_count(obj):
        return obj.edges.count()

    @staticmethod
    def resolve_trigger_count(obj):
        return obj.triggers.count()


class WorkflowDetailOut(WorkflowOut):
    nodes: list["NodeOut"] = []
    edges: list["EdgeOut"] = []
    triggers: list["TriggerOut"] = []

    @staticmethod
    def resolve_nodes(obj):
        return obj.nodes.all()

    @staticmethod
    def resolve_edges(obj):
        return obj.edges.all()

    @staticmethod
    def resolve_triggers(obj):
        return obj.triggers.all()


# ── Node ──────────────────────────────────────────────────────────────────────


class ComponentConfigData(Schema):
    system_prompt: str = ""
    extra_config: dict = {}
    llm_model_id: int | None = None
    llm_credential_id: int | None = None


class NodeIn(Schema):
    node_id: str
    component_type: ComponentTypeStr
    is_entry_point: bool = False
    interrupt_before: bool = False
    interrupt_after: bool = False
    position_x: int = 0
    position_y: int = 0
    config: ComponentConfigData = ComponentConfigData()
    subworkflow_id: int | None = None
    code_block_id: int | None = None


class NodeUpdate(Schema):
    node_id: str | None = None
    component_type: ComponentTypeStr | None = None
    is_entry_point: bool | None = None
    interrupt_before: bool | None = None
    interrupt_after: bool | None = None
    position_x: int | None = None
    position_y: int | None = None
    config: ComponentConfigData | None = None
    subworkflow_id: int | None = None
    code_block_id: int | None = None


class NodeOut(Schema):
    id: int
    node_id: str
    component_type: ComponentTypeStr
    is_entry_point: bool
    interrupt_before: bool
    interrupt_after: bool
    position_x: int
    position_y: int
    config: ComponentConfigData
    subworkflow_id: int | None = None
    code_block_id: int | None = None
    updated_at: datetime

    @staticmethod
    def resolve_config(obj):
        cc = obj.component_config
        return {
            "system_prompt": cc.system_prompt,
            "extra_config": cc.extra_config,
            "llm_model_id": cc.llm_model_id,
            "llm_credential_id": cc.llm_credential_id,
        }


# ── Edge ──────────────────────────────────────────────────────────────────────


class EdgeIn(Schema):
    source_node_id: str
    target_node_id: str = ""
    edge_type: EdgeTypeStr = "direct"
    condition_mapping: dict | None = None
    priority: int = 0


class EdgeUpdate(Schema):
    source_node_id: str | None = None
    target_node_id: str | None = None
    edge_type: EdgeTypeStr | None = None
    condition_mapping: dict | None = None
    priority: int | None = None


class EdgeOut(Schema):
    id: int
    source_node_id: str
    target_node_id: str
    edge_type: EdgeTypeStr
    condition_mapping: dict | None = None
    priority: int


# ── Trigger ───────────────────────────────────────────────────────────────────


class TriggerIn(Schema):
    trigger_type: TriggerTypeStr
    credential_id: int | None = None
    config: dict = {}
    is_active: bool = True
    priority: int = 0


class TriggerUpdate(Schema):
    trigger_type: TriggerTypeStr | None = None
    credential_id: int | None = None
    config: dict | None = None
    is_active: bool | None = None
    priority: int | None = None


class TriggerOut(Schema):
    id: int
    trigger_type: TriggerTypeStr
    credential_id: int | None = None
    config: dict
    is_active: bool
    priority: int
    created_at: datetime


# ── Execution ─────────────────────────────────────────────────────────────────


class ExecutionOut(Schema):
    execution_id: UUID
    workflow_slug: str
    status: str
    error_message: str
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @staticmethod
    def resolve_workflow_slug(obj):
        return obj.workflow.slug


class ExecutionLogOut(Schema):
    id: int
    node_id: str
    status: str
    input: Any | None = None
    output: Any | None = None
    error: str
    duration_ms: int
    timestamp: datetime


class ExecutionDetailOut(ExecutionOut):
    final_output: Any | None = None
    trigger_payload: Any | None = None
    logs: list[ExecutionLogOut] = []

    @staticmethod
    def resolve_logs(obj):
        return obj.logs.all()
