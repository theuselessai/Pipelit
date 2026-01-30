"""Component registry for workflow node types."""

from __future__ import annotations

from typing import Any, Callable

COMPONENT_REGISTRY: dict[str, Callable[[Any], Callable[[dict], dict]]] = {}


def register(component_type: str):
    """Decorator to register a component factory."""

    def decorator(factory):
        COMPONENT_REGISTRY[component_type] = factory
        return factory

    return decorator


def get_component_factory(component_type: str):
    """Look up a registered component factory by type."""
    if component_type not in COMPONENT_REGISTRY:
        raise KeyError(
            f"Unknown component type: '{component_type}'. "
            f"Registered types: {sorted(COMPONENT_REGISTRY.keys())}"
        )
    return COMPONENT_REGISTRY[component_type]


# Import all component modules to trigger @register decorators
from apps.workflows.components import (  # noqa: E402, F401
    categorizer,
    chat,
    code,
    control_flow,
    data_ops,
    http_request,
    human_confirmation,
    output_parser,
    parallel,
    plan_and_execute,
    react_agent,
    router,
    subworkflow,
    tool_node,
)
