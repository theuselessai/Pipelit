from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema

CredentialTypeStr = Literal["git", "llm", "telegram", "tool"]

ComponentTypeStr = Literal[
    "categorizer", "router", "extractor", "ai_model", "simple_agent", "planner_agent",
    "tool_node", "aggregator", "human_confirmation", "parallel", "workflow",
    "code", "loop", "wait", "merge", "filter", "transform", "sort", "limit",
    "http_request", "error_handler", "output_parser",
    "trigger_telegram", "trigger_webhook", "trigger_schedule",
    "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat",
]
EdgeTypeStr = Literal["direct", "conditional"]
EdgeLabelStr = Literal["", "llm", "tool", "memory", "output_parser"]


# -- Workflow ------------------------------------------------------------------


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
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_node_count(obj):
        return obj.nodes.count()

    @staticmethod
    def resolve_edge_count(obj):
        return obj.edges.count()


class WorkflowDetailOut(WorkflowOut):
    nodes: list["NodeOut"] = []
    edges: list["EdgeOut"] = []

    @staticmethod
    def resolve_nodes(obj):
        return obj.nodes.all()

    @staticmethod
    def resolve_edges(obj):
        return obj.edges.all()


# -- Node ----------------------------------------------------------------------


class ComponentConfigData(Schema):
    system_prompt: str = ""
    extra_config: dict = {}
    llm_credential_id: int | None = None
    model_name: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    top_p: float | None = None
    timeout: int | None = None
    max_retries: int | None = None
    response_format: dict | None = None
    # Trigger fields
    credential_id: int | None = None
    is_active: bool = True
    priority: int = 0
    trigger_config: dict = {}


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
        concrete = cc.concrete
        result = {
            "system_prompt": getattr(concrete, "system_prompt", ""),
            "extra_config": cc.extra_config,
            "llm_credential_id": None,
            "model_name": "",
            "temperature": None,
            "max_tokens": None,
            "frequency_penalty": None,
            "presence_penalty": None,
            "top_p": None,
            "timeout": None,
            "max_retries": None,
            "response_format": None,
            "credential_id": None,
            "is_active": True,
            "priority": 0,
            "trigger_config": {},
        }
        from apps.workflows.models.node import ModelComponentConfig, TriggerComponentConfig

        if isinstance(concrete, ModelComponentConfig):
            result["llm_credential_id"] = concrete.llm_credential_id
            result["model_name"] = concrete.model_name
            result["temperature"] = concrete.temperature
            result["max_tokens"] = concrete.max_tokens
            result["frequency_penalty"] = concrete.frequency_penalty
            result["presence_penalty"] = concrete.presence_penalty
            result["top_p"] = concrete.top_p
            result["timeout"] = concrete.timeout
            result["max_retries"] = concrete.max_retries
            result["response_format"] = concrete.response_format
        elif isinstance(concrete, TriggerComponentConfig):
            result["credential_id"] = concrete.credential_id
            result["is_active"] = concrete.is_active
            result["priority"] = concrete.priority
            result["trigger_config"] = concrete.trigger_config
        return result


# -- Edge ----------------------------------------------------------------------


class EdgeIn(Schema):
    source_node_id: str
    target_node_id: str = ""
    edge_type: EdgeTypeStr = "direct"
    edge_label: EdgeLabelStr = ""
    condition_mapping: dict | None = None
    priority: int = 0


class EdgeUpdate(Schema):
    source_node_id: str | None = None
    target_node_id: str | None = None
    edge_type: EdgeTypeStr | None = None
    edge_label: EdgeLabelStr | None = None
    condition_mapping: dict | None = None
    priority: int | None = None


class EdgeOut(Schema):
    id: int
    source_node_id: str
    target_node_id: str
    edge_type: EdgeTypeStr
    edge_label: str = ""
    condition_mapping: dict | None = None
    priority: int


# -- Execution -----------------------------------------------------------------


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


# -- Credentials ---------------------------------------------------------------


class ChatMessageIn(Schema):
    text: str


class ChatMessageOut(Schema):
    execution_id: UUID
    status: str
    response: str


class CredentialIn(Schema):
    name: str
    credential_type: CredentialTypeStr
    detail: dict | None = None


class CredentialUpdate(Schema):
    name: str | None = None
    detail: dict | None = None


class CredentialOut(Schema):
    id: int
    name: str
    credential_type: CredentialTypeStr
    detail: dict = {}
    created_at: datetime
    updated_at: datetime


# -- Credential test/models responses ------------------------------------------


class CredentialTestOut(Schema):
    ok: bool
    error: str = ""


class CredentialModelOut(Schema):
    id: str
    name: str
