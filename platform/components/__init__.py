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
    ai_model,
    calculator,
    categorizer,
    code,
    code_execute,
    control_flow,
    create_agent_user,
    epic_tools,
    get_totp_code,
    platform_api,
    spawn_and_await,
    task_tools,
    workflow_create,
    workflow_discover,
    whoami,
    data_ops,
    datetime_tool,
    http_request,
    human_confirmation,
    identify_user,
    memory_read,
    memory_write,
    output_parser,
    agent,
    deep_agent,
    router,
    run_command,
    subworkflow,
    switch,
    trigger,
    scheduler_tools,
    system_health,
    web_search,
)
