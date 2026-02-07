"""Chat model component — invoke LLM with messages."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from components import register
from services.llm import resolve_llm_for_node


@register("chat_model")
def chat_model_factory(node):
    """Build a chat_model graph node."""
    llm = resolve_llm_for_node(node)
    system_prompt = node.component_config.system_prompt

    def chat_model_node(state: dict) -> dict:
        messages = list(state.get("messages", []))
        if system_prompt:
            messages = [SystemMessage(content=system_prompt)] + messages

        response = llm.invoke(messages)
        return {
            "_messages": [response],
            "output": response.content,
        }

    return chat_model_node
