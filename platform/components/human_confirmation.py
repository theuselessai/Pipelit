"""Human confirmation component — reads _resume_input from orchestrator state."""

from __future__ import annotations

from components import register


@register("human_confirmation")
def human_confirmation_factory(node):
    """Build a human_confirmation graph node."""
    extra = node.component_config.extra_config
    prompt_template = extra.get("prompt", "Please confirm to proceed.")
    node_id = node.node_id

    def human_confirmation_node(state: dict) -> dict:
        # If _resume_input is present, the orchestrator has resumed after interruption
        user_response = state.get("_resume_input")

        if user_response is None:
            # First invocation — the orchestrator should have interrupted before/after
            # this node via interrupt_before/interrupt_after flags. If we get here without
            # _resume_input, treat it as unconfirmed.
            return {
                "route": "cancelled",
                "node_outputs": {
                    node_id: {
                        "confirmed": False,
                        "user_response": None,
                        "prompt": prompt_template,
                    }
                },
            }

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
