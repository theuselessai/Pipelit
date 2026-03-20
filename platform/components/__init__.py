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
from components import (  # noqa: E402, F401
    agent,
    ai_model,
    categorizer,
    code,
    control_flow,
    data_ops,
    deep_agent,
    epic_tools,
    get_totp_code,
    human_confirmation,
    identify_user,
    memory_read,
    memory_write,
    output_parser,
    platform_api,
    reply_chat,
    router,
    run_command,
    scheduler_tools,
    spawn_and_await,
    subworkflow,
    switch,
    system_health,
    task_tools,
    trigger,
    validate_gherkin,
    validate_topology,
    whoami,
    workflow_create,
    workflow_discover,
)
