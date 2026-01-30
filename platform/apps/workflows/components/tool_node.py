"""Tool node component — execute tool calls from previous AI message."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from apps.workflows.components import register
from apps.workflows.components.react_agent import _resolve_tools


@register("tool_node")
def tool_node_factory(node):
    """Build a tool_node graph node."""
    tools = _resolve_tools(node)
    tool_map = {t.name: t for t in tools}
    node_id = node.node_id

    def tool_node_fn(state: dict) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {"node_outputs": {node_id: None}}

        last_msg = messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return {"node_outputs": {node_id: None}}

        result_messages = []
        outputs = {}
        for call in tool_calls:
            tool = tool_map.get(call["name"])
            if tool is None:
                result = f"Tool '{call['name']}' not found"
            else:
                result = tool.invoke(call["args"])

            result_messages.append(
                ToolMessage(content=str(result), tool_call_id=call["id"])
            )
            outputs[call["name"]] = result

        return {
            "messages": result_messages,
            "node_outputs": {node_id: outputs},
        }

    return tool_node_fn
