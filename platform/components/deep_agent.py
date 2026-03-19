"""Deep Agent component — deepagents-powered agent with built-in tools."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent

from components import register
from components._agent_shared import (
    PipelitAgentMiddleware,
    _build_backend,
    _compute_skill_path_mapping,
    _get_ai_model_extra,
    _get_checkpointer,
    _get_redis_checkpointer,
    _make_skill_aware_backend,
    _resolve_credential_field,
    _resolve_tools,
    _resolve_skills,
    _wrap_llm_with_native_tools,
    extract_text_content,
    strip_thinking_blocks,
    strip_web_search_blocks,
)
from services.activity_watchdog import ActivityWatchdog, DEFAULT_INACTIVITY_TIMEOUT, DEFAULT_MAX_WALL_TIME
from services.llm import resolve_llm_for_node
from services.token_usage import (
    calculate_cost,
    extract_usage_from_messages,
    get_model_name_for_node,
)

logger = logging.getLogger(__name__)


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

    # Prepend environment capabilities to system prompt
    try:
        from services.capabilities import detect_capabilities, format_capability_context
        caps = detect_capabilities()
        cap_context = format_capability_context(caps)
        if cap_context:
            system_prompt = f"{cap_context}\n\n{system_prompt}" if system_prompt else cap_context
    except (ImportError, RuntimeError):
        logger.debug("deep_agent: failed to inject capability context", exc_info=True)

    workflow_id = node.workflow_id
    workflow_slug = node.workflow.slug if node.workflow else ""
    node_id = node.node_id
    conversation_memory = extra.get("conversation_memory", False)
    max_completion_tokens = getattr(concrete, "max_tokens", None)
    context_window_override = extra.get("context_window", None)
    if context_window_override is not None:
        try:
            context_window_override = int(context_window_override)
        except (ValueError, TypeError):
            logger.warning("Invalid context_window value %r for deep_agent %s, ignoring", context_window_override, node_id)
            context_window_override = None

    enable_todos = extra.get("enable_todos", False)

    logger.info(
        "DeepAgent %s: system_prompt=%r, conversation_memory=%s, "
        "todos=%s, extra_config=%r",
        node_id, system_prompt[:80] if system_prompt else None,
        conversation_memory, enable_todos, extra,
    )

    # Resolve canvas-connected external tools (same as regular agent)
    tools, tool_metadata = _resolve_tools(node)
    skill_paths = _resolve_skills(node)

    # Web search — always resolve best available search backend
    native_search_tools: list[dict] = []
    try:
        from services.web_search import resolve_web_search_tools
        from services.llm import resolve_credential_for_node
        cred = resolve_credential_for_node(node)
        use_native = _get_ai_model_extra(node).get("use_native_search", False)
        from database import SessionLocal
        with SessionLocal() as search_db:
            native, lc_tools = resolve_web_search_tools(cred, search_db, use_native_search=use_native)
            native_search_tools = native
            tools.extend(lc_tools)
        if native_search_tools:
            logger.info("DeepAgent %s: injecting %d native search tools", node_id, len(native_search_tools))
        elif lc_tools:
            logger.info("DeepAgent %s: added %d search tools", node_id, len(lc_tools))
    except Exception:
        logger.warning("Failed to resolve web search for deep_agent %s", node_id, exc_info=True)

    if native_search_tools:
        llm = _wrap_llm_with_native_tools(llm, native_search_tools)

    # Activity watchdog — extends RQ timeout while agent is active
    inactivity_timeout = int(extra.get("inactivity_timeout", DEFAULT_INACTIVITY_TIMEOUT))
    max_wall_time = int(extra.get("max_wall_time", DEFAULT_MAX_WALL_TIME))
    watchdog = ActivityWatchdog(inactivity_timeout=inactivity_timeout, max_wall_time=max_wall_time)

    # Checkpointer selection (same logic as regular agent)
    checkpointer = None
    if conversation_memory:
        checkpointer = _get_checkpointer()
    else:
        # Deep agents may use subagent interrupts, always need a checkpointer
        checkpointer = _get_redis_checkpointer()

    # Build middleware
    middleware = PipelitAgentMiddleware(tool_metadata, node_id, workflow_slug, watchdog=watchdog)

    # Build memory list for create_deep_agent
    memory_features: list[str] = ["filesystem"]  # always enabled (sandboxed)
    if enable_todos:
        memory_features.append("todos")

    # Build backend — always sandboxed to workspace directory
    backend = _build_backend(extra, skill_paths=skill_paths if skill_paths else None)

    # Build subagents
    subagents = _build_subagents(extra)

    # Note: create_deep_agent already includes SummarizationMiddleware internally
    # with sensible defaults (fraction-based if model has profile, absolute tokens otherwise).
    # We only add trim_messages as a hard safety net below in deep_agent_node().

    agent_kwargs: dict = dict(
        model=llm,
        tools=tools or None,
        system_prompt=system_prompt or None,
        middleware=[middleware],
        checkpointer=checkpointer,
        memory=memory_features,
        backend=backend,
    )
    if subagents:
        agent_kwargs["subagents"] = subagents
    if skill_paths:
        # Compute sandbox path mapping for bwrap mounts
        sandbox_skill_paths, sandbox_to_host = _compute_skill_path_mapping(skill_paths)

        # Check if bwrap is active — if so, use sandbox paths; otherwise use host paths
        use_sandbox_paths = getattr(backend, "_resolution", None) and backend._resolution.mode == "bwrap"
        effective_skill_paths = sandbox_skill_paths if use_sandbox_paths else skill_paths
        effective_sandbox_to_host = sandbox_to_host if use_sandbox_paths else None

        # Wrap the sandboxed backend so SkillsMiddleware reads skill files
        # from real filesystem while agent writes stay sandboxed.
        agent_kwargs["backend"] = _make_skill_aware_backend(
            backend, effective_skill_paths, sandbox_to_host=effective_sandbox_to_host,
        )
        agent_kwargs["skills"] = effective_skill_paths
        logger.info("DeepAgent %s: passing %d skill sources with SkillAwareBackend (bwrap=%s)", node_id, len(skill_paths), use_sandbox_paths)

        # Inject skill provider paths into system prompt so agent knows about them
        if use_sandbox_paths and sandbox_skill_paths:
            provider_list = ", ".join(f"`{p}/`" for p in sandbox_skill_paths)
            skill_context = f"\nSkill providers (read-only): {provider_list}"
            system_prompt = f"{system_prompt}{skill_context}" if system_prompt else skill_context.lstrip()
            agent_kwargs["system_prompt"] = system_prompt

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

        watchdog.start()
        try:
            return _deep_agent_node_inner(state)
        finally:
            watchdog.stop()

    def _deep_agent_node_inner(state: dict) -> dict:
        from datetime import datetime, timezone

        _input_override = state.get("_input_override")
        if _input_override:
            messages = [HumanMessage(content=_input_override)]
        else:
            messages = list(state.get("messages", []))

        if _prompt_fallback:
            messages = [_prompt_fallback] + messages

        # Trim messages as hard safety net against context overflow
        from services.context import trim_messages_for_model
        messages = trim_messages_for_model(
            messages, model_name,
            max_completion_tokens=max_completion_tokens,
            context_window_override=context_window_override,
        )

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
                chat_id = user_ctx.get("chat_id") or user_ctx.get("telegram_chat_id", "")
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
        strip_thinking_blocks(out_messages)
        strip_web_search_blocks(out_messages)

        # Add timestamps to AI messages
        now = datetime.now(timezone.utc).isoformat() + "Z"
        for msg in out_messages:
            if hasattr(msg, "type") and msg.type == "ai":
                if hasattr(msg, "additional_kwargs") and "timestamp" not in msg.additional_kwargs:
                    msg.additional_kwargs["timestamp"] = now

        final_content = ""
        for msg in reversed(out_messages):
            if hasattr(msg, "content") and msg.content and msg.type == "ai":
                final_content = extract_text_content(msg.content)
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
