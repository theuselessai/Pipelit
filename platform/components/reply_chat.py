"""Reply Chat component — sends a message back to the chat caller."""
from __future__ import annotations

from components import register


@register("reply_chat")
def reply_chat_factory(node):
    concrete = node.component_config.concrete
    message_template = (
        getattr(concrete, "system_prompt", None)
        or (getattr(concrete, "extra_config", None) or {}).get("message", "")
    )
    node_id = node.node_id

    def reply_chat_node(state: dict) -> dict:
        message = message_template or ""
        # Use legacy path: return node_outputs dict directly so orchestrator
        # calls merge_state_update which sets state keys directly
        return {
            "node_outputs": {node_id: {"output": message}},
            "output": message,
        }

    return reply_chat_node
