"""AI Model component — invoke LLM with messages."""

from __future__ import annotations

from components import register
from services.llm import resolve_llm_for_node


@register("ai_model")
def ai_model_factory(node):
    """Build an ai_model graph node."""
    llm = resolve_llm_for_node(node)
    node_id = node.node_id

    def ai_model_node(state: dict) -> dict:
        messages = list(state.get("messages", []))
        response = llm.invoke(messages)
        return {
            "messages": [response],
            "node_outputs": {node_id: response.content},
        }

    return ai_model_node
