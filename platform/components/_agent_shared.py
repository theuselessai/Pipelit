"""Shared utilities for agent and deep_agent components."""

from __future__ import annotations

import logging
import os
import threading
from typing import Annotated, Any

from typing_extensions import NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState, OmitFromOutput

logger = logging.getLogger(__name__)


class PipelitAgentState(AgentState[Any]):
    """Extends AgentState with execution_id so middleware can access it."""

    execution_id: NotRequired[Annotated[str | None, OmitFromOutput]]


class PipelitAgentMiddleware(AgentMiddleware):
    """Broadcasts tool status and chat message WebSocket events."""

    state_schema = PipelitAgentState

    def __init__(self, tool_metadata: dict[str, dict], agent_node_id: str, workflow_slug: str):
        super().__init__()
        self._tool_metadata = tool_metadata  # {tool_name: {tool_node_id, component_type}}
        self._agent_node_id = agent_node_id
        self._workflow_slug = workflow_slug

    def wrap_tool_call(self, request, handler):
        tool_name = request.tool_call.get("name", "") if isinstance(request.tool_call, dict) else getattr(request.tool_call, "name", "")
        meta = self._tool_metadata.get(tool_name, {})
        tool_node_id = meta.get("tool_node_id", "")
        component_type = meta.get("component_type", "")

        # For built-in tools (not in metadata), use a synthetic node ID
        if not tool_node_id:
            tool_node_id = f"_builtin_{tool_name}"

        exec_id = None
        state = request.state
        if isinstance(state, dict):
            exec_id = state.get("execution_id")

        _publish_tool_status(
            tool_node_id=tool_node_id, status="running",
            workflow_slug=self._workflow_slug,
            agent_node_id=self._agent_node_id,
            tool_name=tool_name, tool_component_type=component_type,
            execution_id=exec_id,
        )
        try:
            result = handler(request)
            _publish_tool_status(
                tool_node_id=tool_node_id, status="success",
                workflow_slug=self._workflow_slug,
                agent_node_id=self._agent_node_id,
                tool_name=tool_name, tool_component_type=component_type,
                execution_id=exec_id,
            )
            return result
        except Exception as e:
            from langgraph.errors import GraphInterrupt
            if isinstance(e, GraphInterrupt):
                _publish_tool_status(
                    tool_node_id=tool_node_id, status="waiting",
                    workflow_slug=self._workflow_slug,
                    agent_node_id=self._agent_node_id,
                    tool_name=tool_name, tool_component_type=component_type,
                    execution_id=exec_id,
                )
                raise
            _publish_tool_status(
                tool_node_id=tool_node_id, status="failed",
                workflow_slug=self._workflow_slug,
                agent_node_id=self._agent_node_id,
                tool_name=tool_name, tool_component_type=component_type,
                execution_id=exec_id,
            )
            raise

    def wrap_model_call(self, request, handler):
        response = handler(request)
        try:
            exec_id = None
            state = request.state
            if isinstance(state, dict):
                exec_id = state.get("execution_id")
            elif hasattr(state, "execution_id"):
                exec_id = state.execution_id

            if not exec_id or not self._workflow_slug:
                return response

            # Extract text from the last AI message in response.result
            messages = response.result if hasattr(response, "result") else []
            text = ""
            for msg in reversed(messages):
                content = getattr(msg, "content", None)
                if not content:
                    continue
                # Handle Anthropic list format: [{"type": "text", "text": "..."}]
                if isinstance(content, list):
                    text_parts = [
                        block["text"] for block in content
                        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
                    ]
                    text = "\n".join(text_parts)
                else:
                    text = str(content)
                if text.strip():
                    break

            if text.strip():
                from services.orchestrator import _publish_event
                _publish_event(
                    exec_id,
                    "chat_message",
                    {"text": text, "node_id": self._agent_node_id},
                    workflow_slug=self._workflow_slug,
                )
        except Exception:
            logger.debug("PipelitAgentMiddleware.wrap_model_call publish failed (non-fatal)", exc_info=True)
        return response


# Lazy singleton for SqliteSaver checkpointer (permanent — conversation memory)
_checkpointer = None
_checkpointer_lock = threading.Lock()

# Lazy singleton for RedisSaver checkpointer (ephemeral — interrupt/resume)
_redis_checkpointer = None
_redis_checkpointer_lock = threading.Lock()


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        with _checkpointer_lock:
            if _checkpointer is None:
                import sqlite3
                from langgraph.checkpoint.sqlite import SqliteSaver

                db_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "checkpoints.db",
                )
                conn = sqlite3.connect(db_path, check_same_thread=False)
                saver = SqliteSaver(conn)
                saver.setup()
                _checkpointer = saver
                logger.info("Initialized SqliteSaver checkpointer at %s", db_path)
    return _checkpointer


def _get_redis_checkpointer():
    global _redis_checkpointer
    if _redis_checkpointer is None:
        with _redis_checkpointer_lock:
            if _redis_checkpointer is None:
                from langgraph.checkpoint.redis import RedisSaver
                from config import settings

                saver = RedisSaver(redis_url=settings.REDIS_URL)
                saver.setup()
                _redis_checkpointer = saver
                logger.info("Initialized RedisSaver checkpointer at %s", settings.REDIS_URL)
    return _redis_checkpointer


def _resolve_tools(node) -> tuple[list, dict[str, dict]]:
    """Resolve LangChain tools from edge_label='tool' or 'memory' edges connected to this agent.

    Returns:
        (tools, tool_metadata) where tool_metadata maps tool_name to
        {tool_node_id, component_type} for the middleware.
    """
    tools = []
    tool_metadata: dict[str, dict] = {}
    try:
        from database import SessionLocal
        from models.node import WorkflowEdge, WorkflowNode
        from components import get_component_factory

        db = SessionLocal()
        try:
            tool_edges = (
                db.query(WorkflowEdge)
                .filter(
                    WorkflowEdge.workflow_id == node.workflow_id,
                    WorkflowEdge.target_node_id == node.node_id,
                    WorkflowEdge.edge_label.in_(["tool", "memory"]),
                )
                .all()
            )
            logger.info("Agent %s: found %d tool edges", node.node_id, len(tool_edges))
            for edge in tool_edges:
                tool_db_node = (
                    db.query(WorkflowNode)
                    .filter_by(
                        workflow_id=node.workflow_id,
                        node_id=edge.source_node_id,
                    )
                    .first()
                )
                if tool_db_node:
                    factory = get_component_factory(tool_db_node.component_type)
                    result = factory(tool_db_node)
                    tool_component_type = tool_db_node.component_type
                    if isinstance(result, list):
                        for lc_tool in result:
                            tool_name = getattr(lc_tool, 'name', lc_tool.__class__.__name__)
                            logger.info("Agent %s: resolved tool %s from %s (%s)", node.node_id, tool_name, tool_db_node.node_id, tool_component_type)
                            tools.append(lc_tool)
                            tool_metadata[tool_name] = {"tool_node_id": tool_db_node.node_id, "component_type": tool_component_type}
                    else:
                        tool_name = getattr(result, 'name', result.__class__.__name__)
                        logger.info("Agent %s: resolved tool %s (%s)", node.node_id, tool_db_node.node_id, tool_component_type)
                        tools.append(result)
                        tool_metadata[tool_name] = {"tool_node_id": tool_db_node.node_id, "component_type": tool_component_type}
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to resolve tools for agent %s", node.node_id)

    return tools, tool_metadata


def _publish_tool_status(
    tool_node_id: str,
    status: str,
    workflow_slug: str,
    agent_node_id: str,
    tool_name: str = "",
    tool_component_type: str = "",
    execution_id: str | None = None,
):
    """Publish node_status event for a tool node via Redis.

    Uses the orchestrator's ``_publish_event`` when execution_id is available
    so the event includes execution_id (required by the ChatPanel WS handler).
    Falls back to ``broadcast`` for backward compatibility.
    """
    try:
        from schemas.node_types import get_node_type

        spec = get_node_type(tool_component_type)
        display_name = spec.display_name if spec else tool_component_type

        data = {
            "node_id": tool_node_id,
            "status": status,
            "tool_name": tool_name,
            "parent_node_id": agent_node_id,
            "is_tool_call": True,
            "component_type": tool_component_type,
            "display_name": display_name,
            "node_label": tool_node_id,
        }

        if execution_id and workflow_slug:
            # Use orchestrator's _publish_event so execution_id is included
            from services.orchestrator import _publish_event
            logger.info("Broadcasting tool status: node=%s status=%s workflow=%s exec=%s", tool_node_id, status, workflow_slug, execution_id)
            _publish_event(execution_id, "node_status", data, workflow_slug=workflow_slug)
        elif workflow_slug:
            from ws.broadcast import broadcast
            logger.info("Broadcasting tool status: node=%s status=%s workflow=%s", tool_node_id, status, workflow_slug)
            broadcast(f"workflow:{workflow_slug}", "node_status", data)
        else:
            logger.warning("No workflow slug for tool node %s, cannot broadcast", tool_node_id)
    except Exception:
        logger.exception("Failed to publish tool status for node %s", tool_node_id)
