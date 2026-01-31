"""DB-backed LLM factory for workflow components."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel


def create_llm_from_db(
    credential,
    model_name: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    top_p: float | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    response_format: dict | None = None,
) -> BaseChatModel:
    """Create a LangChain chat model from DB records.

    Args:
        credential: LLMProviderCredentials instance (has provider_type, api_key, base_url).
        model_name: Model identifier string (e.g. "gpt-4o", "claude-sonnet-4-20250514").
        temperature, max_tokens, etc.: Optional LLM params. None means provider default.
    """
    provider_type = credential.provider_type
    api_key = credential.api_key

    # Build common kwargs, omitting None values
    kwargs: dict = {"model": model_name}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if top_p is not None:
        kwargs["top_p"] = top_p
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries

    if provider_type == "openai":
        from langchain_openai import ChatOpenAI

        if frequency_penalty is not None:
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
        if response_format is not None:
            kwargs["model_kwargs"] = {"response_format": response_format}
        return ChatOpenAI(api_key=api_key, **kwargs)

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(api_key=api_key, **kwargs)

    if provider_type == "openai_compatible":
        from langchain_openai import ChatOpenAI

        if frequency_penalty is not None:
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
        if response_format is not None:
            kwargs["model_kwargs"] = {"response_format": response_format}
        return ChatOpenAI(api_key=api_key, base_url=credential.base_url, **kwargs)

    raise ValueError(f"Unsupported provider type: {provider_type}")


def resolve_llm_for_node(node) -> BaseChatModel:
    """Resolve LLM for a WorkflowNode.

    For ai_model nodes: read directly from ModelComponentConfig.
    For AI nodes (simple_agent, planner_agent, categorizer, router): walk edges
    with edge_label='llm' to find connected ai_model node.
    """
    from apps.workflows.models.node import ModelComponentConfig, WorkflowEdge

    config = node.component_config
    concrete = config.concrete

    # Direct LLM config on ModelComponentConfig
    if isinstance(concrete, ModelComponentConfig):
        if not concrete.model_name or not concrete.llm_credential_id:
            raise ValueError(
                f"Node '{node.node_id}' (ai_model) requires both "
                "model_name and llm_credential on its config."
            )
        llm_cred = concrete.llm_credential.llm_credential  # BaseCredentials -> LLMProviderCredentials
        return create_llm_from_db(
            llm_cred,
            concrete.model_name,
            temperature=concrete.temperature,
            max_tokens=concrete.max_tokens,
            frequency_penalty=concrete.frequency_penalty,
            presence_penalty=concrete.presence_penalty,
            top_p=concrete.top_p,
            timeout=concrete.timeout,
            max_retries=concrete.max_retries,
            response_format=concrete.response_format,
        )

    # AI nodes: resolve via edge_label='llm'
    llm_edges = WorkflowEdge.objects.filter(
        workflow=node.workflow,
        source_node_id=node.node_id,
        edge_label="llm",
    )
    for edge in llm_edges:
        try:
            target_node = node.workflow.nodes.select_related(
                "component_config",
            ).get(node_id=edge.target_node_id)
        except Exception:
            continue

        target_concrete = target_node.component_config.concrete
        if isinstance(target_concrete, ModelComponentConfig):
            if target_concrete.model_name and target_concrete.llm_credential_id:
                llm_cred = target_concrete.llm_credential.llm_credential
                return create_llm_from_db(
                    llm_cred,
                    target_concrete.model_name,
                    temperature=target_concrete.temperature,
                    max_tokens=target_concrete.max_tokens,
                    frequency_penalty=target_concrete.frequency_penalty,
                    presence_penalty=target_concrete.presence_penalty,
                    top_p=target_concrete.top_p,
                    timeout=target_concrete.timeout,
                    max_retries=target_concrete.max_retries,
                    response_format=target_concrete.response_format,
                )

    raise ValueError(
        f"Node '{node.node_id}' in workflow '{node.workflow.slug}' "
        "has no connected ai_model node via edge_label='llm'. "
        "Connect it to an ai_model node with an LLM edge."
    )
