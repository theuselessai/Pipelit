"""DB-backed LLM factory for workflow components."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session


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
    provider_type = credential.provider_type
    api_key = credential.api_key

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


def resolve_llm_for_node(node, db: Session | None = None) -> BaseChatModel:
    from database import SessionLocal
    from models.credential import BaseCredential

    if db is None:
        db = SessionLocal()

    cc = node.component_config

    if cc.component_type == "ai_model":
        if not cc.model_name or not cc.llm_credential_id:
            raise ValueError(
                f"Node '{node.node_id}' (ai_model) requires both "
                "model_name and llm_credential on its config."
            )
        base_cred = db.query(BaseCredential).filter(BaseCredential.id == cc.llm_credential_id).first()
        llm_cred = base_cred.llm_credential
        return create_llm_from_db(
            llm_cred,
            cc.model_name,
            temperature=cc.temperature,
            max_tokens=cc.max_tokens,
            frequency_penalty=cc.frequency_penalty,
            presence_penalty=cc.presence_penalty,
            top_p=cc.top_p,
            timeout=cc.timeout,
            max_retries=cc.max_retries,
            response_format=cc.response_format,
        )

    # AI nodes: resolve via llm_model_config_id FK (set when ai_model edge is created)
    if cc.llm_model_config_id:
        from models.node import BaseComponentConfig as BCC
        tc = db.get(BCC, cc.llm_model_config_id)
        if tc and tc.component_type == "ai_model" and tc.model_name and tc.llm_credential_id:
            base_cred = db.query(BaseCredential).filter(BaseCredential.id == tc.llm_credential_id).first()
            llm_cred = base_cred.llm_credential
            return create_llm_from_db(
                llm_cred,
                tc.model_name,
                temperature=tc.temperature,
                max_tokens=tc.max_tokens,
                frequency_penalty=tc.frequency_penalty,
                presence_penalty=tc.presence_penalty,
                top_p=tc.top_p,
                timeout=tc.timeout,
                max_retries=tc.max_retries,
                response_format=tc.response_format,
            )

    raise ValueError(
        f"Node '{node.node_id}' has no connected ai_model node via edge_label='llm'."
    )
