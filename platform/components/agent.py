"""Agent component — LangGraph react agent with tools."""

from __future__ import annotations

import logging
import os
import threading
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from components import register
from services.llm import resolve_llm_for_node
from services.token_usage import (
    calculate_cost,
    extract_usage_from_messages,
    get_model_name_for_node,
)

logger = logging.getLogger(__name__)

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


@register("agent")
def agent_factory(node):
    """Build an agent graph node."""
    llm = resolve_llm_for_node(node)
    model_name = get_model_name_for_node(node)
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

    # Detect spawn_and_await tool
    has_spawn_tool = any(
        getattr(t, "name", "") == "spawn_and_await" for t in tools
    )

    # Dual checkpointer selection:
    #   conversation_memory=True → SqliteSaver (permanent, also supports interrupt/resume)
    #   has_spawn_tool=True (no conversation_memory) → RedisSaver (ephemeral)
    #   Neither → None (one-shot, no checkpointer)
    checkpointer = None
    if conversation_memory:
        checkpointer = _get_checkpointer()
    elif has_spawn_tool:
        checkpointer = _get_redis_checkpointer()

    agent_kwargs = dict(
        model=llm,
        tools=tools,
        # SystemMessage applied as pre-LLM transform (not stored in checkpoint)
        prompt=SystemMessage(content=system_prompt) if system_prompt else None,
    )
    if checkpointer is not None:
        agent_kwargs["checkpointer"] = checkpointer

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
        from datetime import datetime, timezone
        from langgraph.types import Command

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

        # Build thread config for checkpointer
        config = None
        if checkpointer is not None:
            if conversation_memory:
                user_ctx = state.get("user_context", {})
                user_id = user_ctx.get("user_profile_id", "anon")
                chat_id = user_ctx.get("telegram_chat_id", "")
                thread_id = (
                    f"{user_id}:{chat_id}:{workflow_id}"
                    if chat_id
                    else f"{user_id}:{workflow_id}"
                )
            else:
                # Ephemeral thread for spawn_and_await interrupt/resume
                execution_id = state.get("execution_id", "unknown")
                thread_id = f"exec:{execution_id}:{node_id}"
            config = {"configurable": {"thread_id": thread_id}}

        # Check if we're resuming from a child workflow result
        child_result = state.get("_subworkflow_results", {}).get(node_id)
        if child_result is not None and has_spawn_tool and checkpointer is not None:
            # Resume: agent graph restores from checkpoint, interrupt() returns child_result
            logger.info("Agent %s: resuming from child result", node_id)
            result = agent.invoke(Command(resume=child_result), config=config)
        else:
            try:
                result = agent.invoke({"messages": messages}, config=config)
            except Exception as exc:
                # Check if this is a GraphInterrupt from spawn_and_await
                from langgraph.errors import GraphInterrupt
                if isinstance(exc, GraphInterrupt) and exc.interrupts:
                    interrupt_data = exc.interrupts[0].value if exc.interrupts else {}
                    logger.info(
                        "Agent %s: interrupted by spawn_and_await, creating child execution: %s",
                        node_id, interrupt_data,
                    )
                    return _try_create_child(interrupt_data, state, node_id)
                raise

            # With a checkpointer, LangGraph catches GraphInterrupt internally
            # and returns the result with an "__interrupt__" key instead of raising.
            if has_spawn_tool and isinstance(result, dict) and "__interrupt__" in result:
                interrupts = result["__interrupt__"]
                if interrupts:
                    interrupt_val = interrupts[0].value if hasattr(interrupts[0], "value") else {}
                    if isinstance(interrupt_val, dict) and interrupt_val.get("action") == "spawn_workflow":
                        logger.info(
                            "Agent %s: detected interrupt in return value, creating child: %s",
                            node_id, interrupt_val,
                        )
                        return _try_create_child(interrupt_val, state, node_id)

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

        # Extract token usage from AI messages (best-effort — never crash the node)
        try:
            usage = extract_usage_from_messages(out_messages).copy()
            usage["cost_usd"] = calculate_cost(
                model_name, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            )
            usage["tool_invocations"] = sum(
                len(getattr(msg, "tool_calls", []) or [])
                for msg in out_messages
                if hasattr(msg, "type") and msg.type == "ai"
            )
        except Exception:
            usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "tool_invocations": 0}

        return {
            "_messages": out_messages,
            "_token_usage": usage,
            "output": final_content,
        }

    return agent_node


def _try_create_child(interrupt_data: dict, state: dict, node_id: str) -> dict:
    """Attempt to create a child execution; return error output instead of raising."""
    try:
        child_id = _create_child_from_interrupt(interrupt_data, state, node_id)
        return {"_subworkflow": {"child_execution_id": child_id}}
    except Exception as exc:
        logger.exception("Agent %s: failed to create child execution", node_id)
        return {"output": "spawn_and_await failed: unable to create child execution"}


def _create_child_from_interrupt(
    interrupt_data: dict,
    state: dict,
    parent_node_id: str,
) -> str:
    """Create a child WorkflowExecution from a spawn_and_await interrupt payload."""
    from database import SessionLocal
    from models.execution import WorkflowExecution
    from models.workflow import Workflow

    workflow_slug = interrupt_data.get("workflow_slug", "")
    input_text = interrupt_data.get("input_text", "")
    task_id = interrupt_data.get("task_id")
    input_data = interrupt_data.get("input_data", {})

    db = SessionLocal()
    try:
        target_workflow = (
            db.query(Workflow)
            .filter(Workflow.slug == workflow_slug, Workflow.deleted_at.is_(None))
            .first()
        )
        if not target_workflow:
            raise ValueError(f"spawn_and_await: target workflow not found: slug={workflow_slug!r}")

        parent_execution_id = state.get("execution_id", "")
        user_context = state.get("user_context", {})
        user_profile_id = user_context.get("user_profile_id")

        if not user_profile_id and parent_execution_id:
            parent_exec = (
                db.query(WorkflowExecution)
                .filter(WorkflowExecution.execution_id == parent_execution_id)
                .first()
            )
            if parent_exec:
                user_profile_id = parent_exec.user_profile_id

        if not user_profile_id:
            raise ValueError("spawn_and_await: cannot determine user_profile_id")

        trigger_payload = {
            "text": input_text,
            "payload": input_data,
        }

        child_execution = WorkflowExecution(
            workflow_id=target_workflow.id,
            user_profile_id=user_profile_id,
            thread_id=uuid.uuid4().hex,
            trigger_payload=trigger_payload,
            parent_execution_id=parent_execution_id,
            parent_node_id=parent_node_id,
        )
        db.add(child_execution)
        db.commit()
        db.refresh(child_execution)

        child_id = str(child_execution.execution_id)

        # Link task if provided
        if task_id:
            try:
                from models.epic import Task
                task = db.query(Task).filter(Task.id == task_id).first()
                if task:
                    task.execution_id = child_id
                    task.status = "running"
                    db.commit()
                    logger.info("spawn_and_await: linked task %s to child execution %s", task_id, child_id)
            except Exception:
                db.rollback()
                logger.exception("spawn_and_await: failed to link task %s", task_id)

        # Enqueue child execution on RQ
        import redis
        from rq import Queue
        from config import settings

        conn = redis.from_url(settings.REDIS_URL)
        q = Queue("workflows", connection=conn)
        from tasks import execute_workflow_job

        q.enqueue(execute_workflow_job, child_id)

        logger.info(
            "spawn_and_await: created child execution %s for workflow '%s' "
            "(parent=%s, node=%s)",
            child_id, target_workflow.slug, parent_execution_id, parent_node_id,
        )
        return child_id

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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
                            tool_name = getattr(lc_tool, 'name', lc_tool.__class__.__name__)
                            logger.info("Agent %s: wrapping tool %s from %s (%s)", node.node_id, tool_name, tool_db_node.node_id, tool_db_node.component_type)
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
