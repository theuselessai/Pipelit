"""Deep Agent component — deepagents-powered agent with built-in tools."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent

from components import register
from components._agent_shared import (
    PipelitAgentMiddleware,
    _get_checkpointer,
    _get_redis_checkpointer,
    _resolve_tools,
)
from services.llm import resolve_llm_for_node
from services.token_usage import (
    calculate_cost,
    extract_usage_from_messages,
    get_model_name_for_node,
)

logger = logging.getLogger(__name__)


def _build_backend(extra: dict):
    """Build the filesystem backend from extra_config settings."""
    backend_type = extra.get("filesystem_backend", "state")

    if backend_type == "filesystem":
        from deepagents.backends.filesystem import FilesystemBackend
        root_dir = extra.get("filesystem_root_dir") or None
        return FilesystemBackend(root_dir=root_dir)
    elif backend_type == "store":
        # StoreBackend requires a LangGraph store — return None to let
        # create_deep_agent use the default if a store is provided separately.
        return None

    # Default: StateBackend — returned by create_deep_agent when backend=None
    return None


def _build_subagents(extra: dict) -> list[SubAgent] | None:
    """Build SubAgent list from extra_config.subagents."""
    subagent_defs = extra.get("subagents")
    if not subagent_defs or not isinstance(subagent_defs, list):
        return None

    subagents = []
    for sa_def in subagent_defs:
        if not isinstance(sa_def, dict):
            continue
        name = sa_def.get("name", "").strip()
        description = sa_def.get("description", "").strip()
        system_prompt = sa_def.get("system_prompt", "").strip()
        if not name or not description or not system_prompt:
            continue

        sa: SubAgent = {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
        }
        # Optional model override
        model = sa_def.get("model", "").strip()
        if model:
            sa["model"] = model

        subagents.append(sa)

    return subagents if subagents else None


@register("deep_agent")
def deep_agent_factory(node):
    """Build a deep agent graph node using create_deep_agent."""
    llm = resolve_llm_for_node(node)
    try:
        model_name = get_model_name_for_node(node)
    except Exception:
        logger.warning("Failed to resolve model name for deep_agent %s; token costs will be $0", node.node_id)
        model_name = ""

    concrete = node.component_config.concrete
    system_prompt = getattr(concrete, "system_prompt", None) or ""
    extra = getattr(concrete, "extra_config", None) or {}
    workflow_id = node.workflow_id
    workflow_slug = node.workflow.slug if node.workflow else ""
    node_id = node.node_id
    conversation_memory = extra.get("conversation_memory", False)

    enable_filesystem = extra.get("enable_filesystem", False)
    enable_todos = extra.get("enable_todos", False)

    logger.info(
        "DeepAgent %s: system_prompt=%r, conversation_memory=%s, "
        "filesystem=%s, todos=%s, extra_config=%r",
        node_id, system_prompt[:80] if system_prompt else None,
        conversation_memory, enable_filesystem, enable_todos, extra,
    )

    # Resolve canvas-connected external tools (same as regular agent)
    tools, tool_metadata = _resolve_tools(node)

    # Checkpointer selection (same logic as regular agent)
    checkpointer = None
    if conversation_memory:
        checkpointer = _get_checkpointer()
    else:
        # Deep agents may use subagent interrupts, always need a checkpointer
        checkpointer = _get_redis_checkpointer()

    # Build middleware
    middleware = PipelitAgentMiddleware(tool_metadata, node_id, workflow_slug)

    # Build memory list for create_deep_agent
    memory_features: list[str] = []
    if enable_todos:
        memory_features.append("todos")
    if enable_filesystem:
        memory_features.append("filesystem")

    # Build backend
    backend = _build_backend(extra) if enable_filesystem else None

    # Build subagents
    subagents = _build_subagents(extra)

    agent_kwargs: dict = dict(
        model=llm,
        tools=tools or None,
        system_prompt=system_prompt or None,
        middleware=[middleware],
        checkpointer=checkpointer,
    )
    if memory_features:
        agent_kwargs["memory"] = memory_features
    if backend is not None:
        agent_kwargs["backend"] = backend
    if subagents:
        agent_kwargs["subagents"] = subagents

    agent = create_deep_agent(**agent_kwargs)

    # HumanMessage fallback for providers that ignore the system role
    _prompt_fallback = (
        HumanMessage(
            content=f"[System instructions — follow these for the entire conversation]\n{system_prompt}",
            id="system_prompt_fallback",
        )
        if system_prompt
        else None
    )

    def deep_agent_node(state: dict) -> dict:
        from datetime import datetime, timezone

        messages = list(state.get("messages", []))

        if _prompt_fallback:
            messages = [_prompt_fallback] + messages
        logger.info("DeepAgent %s: sending %d messages", node_id, len(messages))

        # Build thread config for checkpointer
        config = None
        if checkpointer is not None:
            is_child = state.get("_is_child_execution", False)
            if is_child:
                execution_id = state.get("execution_id", "unknown")
                thread_id = f"exec:{execution_id}:{node_id}"
            elif conversation_memory:
                user_ctx = state.get("user_context", {})
                user_id = user_ctx.get("user_profile_id", "anon")
                chat_id = user_ctx.get("telegram_chat_id", "")
                thread_id = (
                    f"{user_id}:{chat_id}:{workflow_id}"
                    if chat_id
                    else f"{user_id}:{workflow_id}"
                )
            else:
                execution_id = state.get("execution_id", "unknown")
                thread_id = f"exec:{execution_id}:{node_id}"
            config = {"configurable": {"thread_id": thread_id}}

        # Pass execution_id in the input so middleware can read it from state
        exec_id = state.get("execution_id")
        invoke_input: dict = {"messages": messages}
        if exec_id:
            invoke_input["execution_id"] = exec_id

        try:
            result = agent.invoke(invoke_input, config=config)
        except Exception:
            logger.exception("DeepAgent %s: agent.invoke() failed", node_id)
            raise

        out_messages = result.get("messages", [])

        # Add timestamps to AI messages
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

        # Extract token usage
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
            logger.exception("Failed to extract token usage for deep_agent %s", node.node_id)
            usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "tool_invocations": 0}

        return {
            "_messages": out_messages,
            "_token_usage": usage,
            "output": final_content,
        }

    return deep_agent_node
