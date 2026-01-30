"""Plan-and-execute component — stub."""

from apps.workflows.components import register


@register("plan_and_execute")
def plan_and_execute_factory(node):
    def plan_and_execute_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'plan_and_execute' not yet implemented. "
            "Requires planner/replanner loop with LangGraph subgraph."
        )

    return plan_and_execute_node
