"""Node and Edge schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel

# The built-in types. This is no longer the whole set: node types are also
# derived at import from binary catalogs (schemas/binary_catalogs.py), which are
# operator-supplied and therefore unknowable here. So the validator below checks
# the live registry and falls back to this tuple, rather than the tuple being a
# Literal that would reject every derived type.
STATIC_COMPONENT_TYPES = (
    "categorizer",
    "router",
    "extractor",
    "ai_model",
    "agent",
    "deep_agent",
    "switch",
    "assertion",
    "run_command",
    "get_totp_code",
    "platform_api",
    "whoami",
    "spawn_and_await",
    "workflow_create",
    "workflow_discover",
    "scheduler_tools",
    "system_health",
    "human_confirmation",
    "workflow",
    "code",
    "code_execute",
    "loop",
    "wait",
    "merge",
    "filter",
    "error_handler",
    "output_parser",
    "memory_read",
    "memory_write",
    "identify_user",
    "trigger_telegram",
    "trigger_schedule",
    "trigger_manual",
    "trigger_workflow",
    "trigger_error",
    "trigger_chat",
    "reply_chat",
    "skill",
    "validate_gherkin",
    "validate_topology",
    "mailbox_action",
    "mailbox_parse",
)


def _known_component_type(value: str) -> str:
    from schemas.node_types import NODE_TYPE_REGISTRY

    if value in NODE_TYPE_REGISTRY or value in STATIC_COMPONENT_TYPES:
        return value
    raise ValueError(
        f"unknown component_type {value!r}. Derived types need their binary's "
        f"catalog present in platform/catalogs/ — see that directory's README."
    )


ComponentTypeStr = Annotated[str, AfterValidator(_known_component_type)]

EdgeTypeStr = Literal["direct", "conditional"]
# "memory" was removed — migration 0d301d48b86a converts all memory edges to tool edges.
EdgeLabelStr = Literal["", "llm", "tool", "output_parser", "loop_body", "loop_return", "skill"]


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
    input_template: str | None = None


class NodeIn(BaseModel):
    # Intentionally optional — backend auto-generates "{component_type}_{hex}" when omitted.
    # NodeOut.node_id is always non-null (populated after creation).
    node_id: str | None = None
    label: str | None = None
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
    label: str | None = None
    component_type: ComponentTypeStr | None = None
    is_entry_point: bool | None = None
    interrupt_before: bool | None = None
    interrupt_after: bool | None = None
    position_x: int | None = None
    position_y: int | None = None
    config: ComponentConfigData | None = None
    subworkflow_id: int | None = None
    code_block_id: int | None = None


class ScheduleJobInfo(BaseModel):
    id: str
    status: str
    run_count: int
    error_count: int
    current_repeat: int
    current_retry: int
    total_repeats: int
    max_retries: int
    timeout_seconds: int
    interval_seconds: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_error: str = ""
    created_at: datetime | None = None


class NodeOut(BaseModel):
    id: int
    node_id: str
    label: str | None = None
    # Deliberately unvalidated on the way OUT. A node whose binary catalog is
    # absent must still be readable — otherwise one missing file makes an entire
    # workflow unloadable, which is a far worse failure than showing a type the
    # palette cannot offer.
    component_type: str
    is_entry_point: bool
    interrupt_before: bool
    interrupt_after: bool
    position_x: int
    position_y: int
    config: ComponentConfigData
    subworkflow_id: int | None = None
    code_block_id: int | None = None
    updated_at: datetime
    schedule_job: ScheduleJobInfo | None = None

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
