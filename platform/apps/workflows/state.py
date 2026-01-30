"""WorkflowState TypedDict for LangGraph graph execution."""

from __future__ import annotations

import operator
from typing import Annotated, Any

from langgraph.graph import MessagesState
from langchain_core.messages import AnyMessage


def add_messages(
    left: list[AnyMessage],
    right: list[AnyMessage],
) -> list[AnyMessage]:
    """Reducer that appends messages (delegates to LangGraph's built-in)."""
    from langgraph.graph import add_messages as _add

    return _add(left, right)


class WorkflowState(MessagesState):
    """Full workflow execution state passed between LangGraph nodes."""

    # Trigger context
    trigger: dict[str, Any]
    user_context: dict[str, Any]

    # Execution tracking
    current_node: str
    execution_id: str
    route: str

    # Results
    branch_results: dict[str, Any]
    plan: list[dict[str, Any]]
    node_outputs: Annotated[dict[str, Any], operator.or_]
    output: Any

    # Control flow
    loop_state: dict[str, Any]
    error: str
    should_retry: bool
