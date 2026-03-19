"""Reply Chat component — sends a message back to the chat caller."""
from __future__ import annotations

from components import register


@register("reply_chat")
def reply_chat_factory(node):
    concrete = node.component_config.concrete
    extra = getattr(concrete, "extra_config", None) or {}
    message_template = extra.get("message", "")
    node_id = node.node_id

    def reply_chat_node(state: dict) -> dict:
        # message_template is already resolved by orchestrator via extra_config resolution
        message = message_template or ""
        # Use legacy path: return node_outputs dict directly so orchestrator
        # calls merge_state_update which sets state keys directly
        return {
            "node_outputs": {node_id: {"output": message}},
            "output": message,
        }

    return reply_chat_node
