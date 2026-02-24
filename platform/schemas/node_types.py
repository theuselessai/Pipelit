"""Node type registry with port definitions."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel


class DataType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    MESSAGE = "message"
    MESSAGES = "messages"
    IMAGE = "image"
    FILE = "file"
    ANY = "any"


class PortDefinition(BaseModel):
    name: str
    data_type: DataType = DataType.ANY
    description: str = ""
    required: bool = False
    default: Any = None


class NodeTypeSpec(BaseModel):
    component_type: str
    display_name: str
    description: str = ""
    category: str = "general"
    inputs: list[PortDefinition] = []
    outputs: list[PortDefinition] = []
    requires_model: bool = False
    requires_tools: bool = False
    requires_memory: bool = False
    requires_output_parser: bool = False
    requires_skills: bool = False
    executable: bool = True
    config_schema: dict[str, Any] = {}


NODE_TYPE_REGISTRY: dict[str, NodeTypeSpec] = {}


def register_node_type(spec: NodeTypeSpec) -> NodeTypeSpec:
    NODE_TYPE_REGISTRY[spec.component_type] = spec
    return spec


def get_node_type(component_type: str) -> NodeTypeSpec | None:
    return NODE_TYPE_REGISTRY.get(component_type)
