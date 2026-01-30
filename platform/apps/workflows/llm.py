"""DB-backed LLM factory for workflow components."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel


def create_llm_from_db(
    llm_model,
    credential,
    temperature: float | None = None,
) -> BaseChatModel:
    """Create a LangChain chat model from DB records.

    Args:
        llm_model: LLMModel instance (has provider.provider_type, model_name, default_temperature).
        credential: LLMProviderCredentials instance (has api_key, base_url).
        temperature: Override temperature. Falls back to llm_model.default_temperature.
    """
    provider_type = llm_model.provider.provider_type
    model_name = llm_model.model_name
    temp = temperature if temperature is not None else llm_model.default_temperature
    api_key = credential.api_key

    if provider_type == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name, temperature=temp, api_key=api_key)

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, temperature=temp, api_key=api_key)

    if provider_type == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            temperature=temp,
            api_key=api_key,
            base_url=credential.base_url,
        )

    raise ValueError(f"Unsupported provider type: {provider_type}")


def resolve_llm_for_node(node) -> BaseChatModel:
    """Resolve LLM for a WorkflowNode from its ComponentConfig.

    Both llm_model and llm_credential must be set on the node's ComponentConfig.
    """
    config = node.component_config

    if not config.llm_model_id or not config.llm_credential_id:
        raise ValueError(
            f"Node '{node.node_id}' in workflow '{node.workflow.slug}' "
            "requires both llm_model and llm_credential on its ComponentConfig."
        )

    temp = config.extra_config.get("temperature")
    return create_llm_from_db(config.llm_model, config.llm_credential, temperature=temp)
