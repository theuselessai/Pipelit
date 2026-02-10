"""Node and Edge schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ComponentTypeStr = Literal[
    "categorizer", "router", "extractor", "ai_model", "agent", "switch",
    "run_command", "http_request", "web_search", "calculator", "datetime", "create_agent_user", "platform_api", "whoami", "epic_tools", "task_tools",
    "spawn_and_await", "workflow_create",
    "aggregator", "human_confirmation", "workflow",
    "code", "code_execute", "loop", "wait", "merge", "filter",
    "error_handler", "output_parser",
    "memory_read", "memory_write", "identify_user",
    "trigger_telegram", "trigger_webhook", "trigger_schedule",
    "trigger_manual", "trigger_workflow", "trigger_error", "trigger_chat",
]
EdgeTypeStr = Literal["direct", "conditional"]
EdgeLabelStr = Literal["", "llm", "tool", "memory", "output_parser", "loop_body", "loop_return"]


class ComponentConfigData(BaseModel):
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
    # Sub-component links
    llm_model_config_id: int | None = None
    # Trigger fields
    credential_id: int | None = None
    is_active: bool = True
    priority: int = 0
    trigger_config: dict = {}


class NodeIn(BaseModel):
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


class NodeUpdate(BaseModel):
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


class NodeOut(BaseModel):
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

    model_config = {"from_attributes": True}


class EdgeIn(BaseModel):
    source_node_id: str
    target_node_id: str = ""
    edge_type: EdgeTypeStr = "direct"
    edge_label: EdgeLabelStr = ""
    condition_mapping: dict | None = None
    condition_value: str = ""
    priority: int = 0


class EdgeUpdate(BaseModel):
    source_node_id: str | None = None
    target_node_id: str | None = None
    edge_type: EdgeTypeStr | None = None
    edge_label: EdgeLabelStr | None = None
    condition_mapping: dict | None = None
    condition_value: str | None = None
    priority: int | None = None


class EdgeOut(BaseModel):
    id: int
    source_node_id: str
    target_node_id: str
    edge_type: EdgeTypeStr
    edge_label: EdgeLabelStr = ""
    condition_mapping: dict | None = None
    condition_value: str = ""
    priority: int

    model_config = {"from_attributes": True}
