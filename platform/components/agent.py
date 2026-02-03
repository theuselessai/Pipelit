"""Agent component — LangGraph react agent with tools."""

from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from components import register
from services.llm import resolve_llm_for_node

logger = logging.getLogger(__name__)


@register("agent")
def agent_factory(node):
    """Build an agent graph node."""
    llm = resolve_llm_for_node(node)
    concrete = node.component_config.concrete
    system_prompt = getattr(concrete, "system_prompt", "")
    node_id = node.node_id

    tools = _resolve_tools(node)

    agent = create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=system_prompt) if system_prompt else None,
    )

    def agent_node(state: dict) -> dict:
        messages = list(state.get("messages", []))
        result = agent.invoke({"messages": messages})
        out_messages = result.get("messages", [])

        final_content = ""
        for msg in reversed(out_messages):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                final_content = msg.content
                break

        return {
            "messages": out_messages,
            "node_outputs": {node_id: final_content},
        }

    return agent_node


def _resolve_tools(node) -> list:
    """Resolve LangChain tools from edge_label='tool' edges connected to this agent."""
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
                    WorkflowEdge.edge_label == "tool",
                )
                .all()
            )
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
                    lc_tool = factory(tool_db_node)
                    tools.append(_wrap_tool_with_events(lc_tool, tool_db_node.node_id, node))
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to resolve tools for agent %s", node.node_id)

    return tools


def _wrap_tool_with_events(lc_tool, tool_node_id, agent_node):
    """Wrap a LangChain tool to publish node_status WS events."""
    original_fn = lc_tool.func

    def wrapped(*args, **kwargs):
        _publish_tool_status(tool_node_id, "running", agent_node)
        try:
            result = original_fn(*args, **kwargs)
            _publish_tool_status(tool_node_id, "success", agent_node)
            return result
        except Exception:
            _publish_tool_status(tool_node_id, "failed", agent_node)
            raise

    lc_tool.func = wrapped
    return lc_tool


def _publish_tool_status(tool_node_id: str, status: str, agent_node):
    """Publish node_status event for a tool node via Redis."""
    try:
        import json
        import time
        import redis

        from config import settings

        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        payload = {
            "type": "node_status",
            "data": {"node_id": tool_node_id, "status": status},
            "timestamp": time.time(),
        }
        # Publish to workflow channel
        from models.node import WorkflowNode
        from database import SessionLocal
        db = SessionLocal()
        try:
            wf_node = db.query(WorkflowNode).filter_by(
                workflow_id=agent_node.workflow_id,
                node_id=agent_node.node_id,
            ).first()
            if wf_node and wf_node.workflow:
                slug = wf_node.workflow.slug
                payload["channel"] = f"workflow:{slug}"
                r.publish(f"workflow:{slug}", json.dumps(payload))
        finally:
            db.close()
    except Exception:
        pass
