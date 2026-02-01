"""Planner agent component — stub (renamed from plan_and_execute)."""

from components import register


@register("planner_agent")
def planner_agent_factory(node):
    def planner_agent_node(state: dict) -> dict:
        raise NotImplementedError(
            "Component 'planner_agent' not yet implemented. "
            "Requires planner/replanner loop with LangGraph subgraph."
        )

    return planner_agent_node
