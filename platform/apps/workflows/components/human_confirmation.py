"""Human confirmation component — interrupt for user approval."""

from __future__ import annotations

from langgraph.types import interrupt

from apps.workflows.components import register


@register("human_confirmation")
def human_confirmation_factory(node):
    """Build a human_confirmation graph node."""
    extra = node.component_config.extra_config
    prompt_template = extra.get("prompt", "Please confirm to proceed.")
    node_id = node.node_id

    def human_confirmation_node(state: dict) -> dict:
        # Build prompt from template, substituting state values
        prompt = prompt_template
        for key, val in state.get("node_outputs", {}).items():
            prompt = prompt.replace(f"{{{key}}}", str(val))

        # LangGraph interrupt — suspends execution until resumed
        user_response = interrupt({"prompt": prompt, "node_id": node_id})

        confirmed = str(user_response).lower() in ("yes", "confirm", "true", "y", "1")
        return {
            "route": "confirmed" if confirmed else "cancelled",
            "node_outputs": {
                node_id: {
                    "confirmed": confirmed,
                    "user_response": user_response,
                }
            },
        }

    return human_confirmation_node
