"""WorkflowState TypedDict for LangGraph graph execution."""

from __future__ import annotations

import operator
from typing import Annotated, Any

from langgraph.graph import MessagesState
from langchain_core.messages import AnyMessage


def add_messages(left: list[AnyMessage], right: list[AnyMessage]) -> list[AnyMessage]:
    from langgraph.graph import add_messages as _add
    return _add(left, right)


class WorkflowState(MessagesState):
    trigger: dict[str, Any]
    user_context: dict[str, Any]
    current_node: str
    execution_id: str
    route: str
    branch_results: dict[str, Any]
    plan: list[dict[str, Any]]
    node_outputs: Annotated[dict[str, Any], operator.or_]
    output: Any
    loop_state: dict[str, Any]
    error: str
    should_retry: bool


def merge_state_update(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge a node's output into the accumulated state.

    Merge semantics:
    - ``messages`` → append
    - ``node_outputs`` → dict merge (``|``)
    - everything else → overwrite
    """
    merged = dict(current)
    for key, value in update.items():
        if key == "messages":
            merged["messages"] = merged.get("messages", []) + (value or [])
        elif key == "node_outputs":
            merged["node_outputs"] = {**merged.get("node_outputs", {}), **(value or {})}
        else:
            merged[key] = value
    return merged


def serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Serialize state for Redis storage. Converts LangChain messages to dicts."""
    from langchain_core.messages import messages_to_dict

    out = dict(state)
    msgs = out.get("messages")
    if msgs:
        out["messages"] = messages_to_dict(msgs)
    return out


def deserialize_state(data: dict[str, Any]) -> dict[str, Any]:
    """Deserialize state from Redis storage. Converts message dicts back."""
    from langchain_core.messages import messages_from_dict

    out = dict(data)
    msgs = out.get("messages")
    if msgs and isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        out["messages"] = messages_from_dict(msgs)
    return out
