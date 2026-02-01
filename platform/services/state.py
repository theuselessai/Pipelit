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
