"""Agent component — LangGraph react agent with tools."""

from __future__ import annotations

import logging
import os
import threading

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from components import register
from services.llm import resolve_llm_for_node

logger = logging.getLogger(__name__)

# Lazy singleton for SqliteSaver checkpointer
_checkpointer = None
_checkpointer_lock = threading.Lock()


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
                _checkpointer = SqliteSaver(conn)
                _checkpointer.setup()
                logger.info("Initialized SqliteSaver checkpointer at %s", db_path)
    return _checkpointer


@register("agent")
def agent_factory(node):
    """Build an agent graph node."""
    llm = resolve_llm_for_node(node)
    concrete = node.component_config.concrete
    system_prompt = getattr(concrete, "system_prompt", None) or ""
    extra = getattr(concrete, "extra_config", None) or {}
    workflow_id = node.workflow_id
    node_id = node.node_id
    conversation_memory = extra.get("conversation_memory", False)

    logger.warning(
        "Agent %s: system_prompt=%r, conversation_memory=%s, extra_config=%r",
        node_id, system_prompt[:80] if system_prompt else None, conversation_memory, extra,
    )

    tools = _resolve_tools(node)

    agent_kwargs = dict(
        model=llm,
        tools=tools,
        # SystemMessage applied as pre-LLM transform (not stored in checkpoint)
        prompt=SystemMessage(content=system_prompt) if system_prompt else None,
    )
    if conversation_memory:
        agent_kwargs["checkpointer"] = _get_checkpointer()

    agent = create_react_agent(**agent_kwargs)

    # HumanMessage fallback for providers that ignore the system role (e.g. Venice.ai).
    # Stable id prevents duplication across checkpointer invocations.
    _prompt_fallback = (
        HumanMessage(
            content=f"[System instructions — follow these for the entire conversation]\n{system_prompt}",
            id="system_prompt_fallback",
        )
        if system_prompt
        else None
    )

    def agent_node(state: dict) -> dict:
        messages = list(state.get("messages", []))

        # If this agent has no tools, strip tool-related messages from upstream
        # agents to avoid confusing the LLM with foreign tool calls/responses.
        if not tools:
            from langchain_core.messages import ToolMessage as _ToolMessage
            cleaned = []
            for msg in messages:
                if isinstance(msg, _ToolMessage):
                    continue
                if hasattr(msg, "type") and msg.type == "ai" and getattr(msg, "tool_calls", None):
                    continue
                cleaned.append(msg)
            messages = cleaned

        if _prompt_fallback:
            messages = [_prompt_fallback] + messages
        logger.warning("Agent %s: sending %d messages (has_prompt=%s)", node_id, len(messages), bool(system_prompt))

        config = None
        if conversation_memory:
            user_ctx = state.get("user_context", {})
            user_id = user_ctx.get("user_profile_id", "anon")
            chat_id = user_ctx.get("telegram_chat_id", "")
            thread_id = (
                f"{user_id}:{chat_id}:{workflow_id}"
                if chat_id
                else f"{user_id}:{workflow_id}"
            )
            config = {"configurable": {"thread_id": thread_id}}

        from datetime import datetime, timezone

        result = agent.invoke({"messages": messages}, config=config)
        out_messages = result.get("messages", [])

        # Add timestamps to AI messages that don't have one
        now = datetime.now(timezone.utc).isoformat() + "Z"
        for msg in out_messages:
            if hasattr(msg, "type") and msg.type == "ai":
                if hasattr(msg, "additional_kwargs") and "timestamp" not in msg.additional_kwargs:
                    msg.additional_kwargs["timestamp"] = now

        final_content = ""
        for msg in reversed(out_messages):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                final_content = msg.content
                break

        return {
            "_messages": out_messages,
            "output": final_content,
        }

    return agent_node


def _resolve_tools(node) -> list:
    """Resolve LangChain tools from edge_label='tool' or 'memory' edges connected to this agent."""
    tools = []
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
                    if isinstance(result, list):
                        for lc_tool in result:
                            logger.info("Agent %s: wrapping tool %s from %s (%s)", node.node_id, lc_tool.name, tool_db_node.node_id, tool_db_node.component_type)
                            tools.append(_wrap_tool_with_events(lc_tool, tool_db_node.node_id, node))
                    else:
                        logger.info("Agent %s: wrapping tool %s (%s)", node.node_id, tool_db_node.node_id, tool_db_node.component_type)
                        tools.append(_wrap_tool_with_events(result, tool_db_node.node_id, node))
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to resolve tools for agent %s", node.node_id)

    return tools


def _wrap_tool_with_events(lc_tool, tool_node_id, agent_node):
    """Wrap a LangChain tool to publish node_status WS events."""
    from functools import wraps

    original_fn = lc_tool.func
    # Cache workflow_id for use when tool is invoked later
    workflow_id = agent_node.workflow_id
    agent_node_id = agent_node.node_id

    @wraps(original_fn)
    def wrapped(*args, **kwargs):
        logger.info("Tool %s invoked, publishing running status", tool_node_id)
        _publish_tool_status(tool_node_id, "running", workflow_id, agent_node_id)
        try:
            result = original_fn(*args, **kwargs)
            logger.info("Tool %s completed successfully", tool_node_id)
            _publish_tool_status(tool_node_id, "success", workflow_id, agent_node_id)
            return result
        except Exception as e:
            logger.info("Tool %s failed: %s", tool_node_id, e)
            _publish_tool_status(tool_node_id, "failed", workflow_id, agent_node_id)
            raise

    lc_tool.func = wrapped
    return lc_tool


def _publish_tool_status(tool_node_id: str, status: str, workflow_id: int, agent_node_id: str):
    """Publish node_status event for a tool node via Redis."""
    try:
        from ws.broadcast import broadcast

        # Get workflow slug
        from models.node import WorkflowNode
        from database import SessionLocal

        db = SessionLocal()
        try:
            wf_node = db.query(WorkflowNode).filter_by(
                workflow_id=workflow_id,
                node_id=agent_node_id,
            ).first()
            if wf_node and wf_node.workflow:
                slug = wf_node.workflow.slug
                logger.info("Broadcasting tool status: node=%s status=%s workflow=%s", tool_node_id, status, slug)
                broadcast(f"workflow:{slug}", "node_status", {"node_id": tool_node_id, "status": status})
            else:
                logger.warning("Could not find workflow for agent node %s", agent_node_id)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to publish tool status for node %s", tool_node_id)
