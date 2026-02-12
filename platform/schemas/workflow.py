"""Workflow schemas."""

from datetime import datetime

from pydantic import BaseModel


class WorkflowIn(BaseModel):
    name: str
    slug: str
    description: str = ""
    is_active: bool = True
    is_public: bool = False
    is_default: bool = False
    tags: list[str] | None = None
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    is_default: bool | None = None
    tags: list[str] | None = None
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None


class WorkflowOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str
    is_active: bool
    is_public: bool
    is_default: bool
    tags: list[str] | None = None
    error_handler_workflow_id: int | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    node_count: int = 0
    edge_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowDetailOut(WorkflowOut):
    nodes: list["NodeOut"] = []
    edges: list["EdgeOut"] = []


# Forward refs resolved after NodeOut/EdgeOut are defined
from schemas.node import NodeOut, EdgeOut  # noqa: E402, F401

WorkflowDetailOut.model_rebuild()
