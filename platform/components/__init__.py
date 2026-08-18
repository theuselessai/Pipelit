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
        # Node types derived from a binary catalog are registered when
        # components.binary_op imports, which may be before the catalogs have
        # been read. Rather than depend on that ordering, re-derive on a miss.
        from components.binary_auth import register_verb_types
        from components.binary_op import register_derived_types

        register_derived_types()
        register_verb_types()
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
    assertion,
    binary_auth,
    binary_op,
    categorizer,
    code,
    control_flow,
    data_ops,
    deep_agent,
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
    trigger,
    validate_gherkin,
    validate_topology,
    mailbox,
    whoami,
    workflow_create,
    workflow_discover,
)
