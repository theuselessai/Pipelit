"""spawn_and_await tool — LangChain tool for spawning a child workflow and awaiting its result."""

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
    On resume (after the child completes), ``interrupt()`` returns the
    child's output and the tool returns it as a JSON string to the LLM.
    """

    @tool
    def spawn_and_await(
        workflow_slug: str,
        input_text: str = "",
        task_id: str | None = None,
        input_data: dict | None = None,
    ) -> str:
        """Spawn a child workflow and wait for its result.

        This tool launches another workflow as a child execution and pauses
        the current agent until the child completes.  The child's output is
        returned as a JSON string.

        Args:
            workflow_slug: Slug of the workflow to spawn.
            input_text: Text input to pass as the child's trigger text.
            task_id: Optional task ID to link the child execution to.
            input_data: Optional dict of additional data for the child trigger payload.

        Returns:
            JSON string with the child workflow's output.
        """
        from langgraph.types import interrupt

        result = interrupt({
            "action": "spawn_workflow",
            "workflow_slug": workflow_slug,
            "input_text": input_text,
            "task_id": task_id,
            "input_data": input_data if input_data is not None else {},
        })

        # On resume, interrupt() returns the child's output.
        # If the child failed, the result contains an _error key — raise so the
        # agent's error handling kicks in instead of the LLM retrying the tool.
        if isinstance(result, dict) and "_error" in result:
            raise ToolException(f"Child workflow failed: {result['_error']}")

        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)

    return [spawn_and_await]
