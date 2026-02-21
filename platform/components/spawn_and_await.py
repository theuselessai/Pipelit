"""spawn_and_await tool — LangChain tool for spawning child workflows in parallel."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import ToolException, tool

from components import register

logger = logging.getLogger(__name__)


@register("spawn_and_await")
def spawn_and_await_factory(node):
    """Return a list with one LangChain tool: spawn_and_await.

    When invoked inside an agent's reasoning loop, this tool calls
    ``interrupt()`` from LangGraph to checkpoint the agent mid-tool-call.
    On resume (after all children complete), ``interrupt()`` returns the
    list of child results and the tool returns them as a JSON string.
    """

    @tool
    def spawn_and_await(tasks: list[dict]) -> str:
        """Spawn one or more child workflows in parallel and wait for all results.

        Use workflow_slug="self" to spawn another instance of the current workflow.

        Args:
            tasks: List of dicts, each with:
                - workflow_slug: "self" for current workflow, or target workflow slug
                - input_text: Instructions for the child instance

        Returns:
            JSON array of results, one per task (same order as input).
        """
        from langgraph.types import interrupt

        if not tasks:
            raise ToolException("tasks list cannot be empty")
        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise ToolException(f"Task {i} must be a dict, got {type(task).__name__}")
            if "workflow_slug" not in task:
                raise ToolException(f"Task {i} missing required field 'workflow_slug'")

        result = interrupt({"action": "spawn_and_await", "tasks": tasks})

        # On resume, interrupt() returns the list of child results.
        # If the result contains an _error key, raise so the agent's
        # error handling kicks in instead of the LLM retrying the tool.
        if isinstance(result, dict) and "_error" in result:
            raise ToolException(f"Spawn failed: {result['_error']}")

        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)

    return [spawn_and_await]
