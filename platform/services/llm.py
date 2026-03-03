"""DB-backed LLM factory for workflow components."""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _is_empty_text_block(block) -> bool:
    """True if block is a text content block with empty text.

    Handles both plain dicts and Pydantic v2 model instances (e.g.
    anthropic.types.TextBlock) which the LangGraph checkpointer preserves
    via msgpack EXT_PYDANTIC_V2 serialisation.
    """
    if isinstance(block, dict):
        return block.get("type") == "text" and not block.get("text")
    if hasattr(block, "type") and hasattr(block, "text"):
        return getattr(block, "type") == "text" and not getattr(block, "text")
    return False


def _sanitize_message_content(messages):
    """Strip empty text blocks from all messages before sending to the API.

    Some providers (e.g. GLM) reject {"type": "text", "text": ""} content blocks.
    These accumulate in conversation memory across provider switches.
    Handles both plain dicts and Pydantic v2 objects from the checkpointer.
    """
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        cleaned = [
            block for block in content
            if not _is_empty_text_block(block)
        ]
        if len(cleaned) != len(content):
            msg.content = cleaned


def _make_sanitized_chat_openai():
    """Return a ChatOpenAI subclass that strips empty text blocks before API calls."""
    from langchain_openai import ChatOpenAI

    class SanitizedChatOpenAI(ChatOpenAI):
        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            # Strip empty text blocks from the final payload.
            # Uses _is_empty_text_block to catch both plain dicts AND Pydantic
            # objects that _format_message_content() passes through unchanged.
            for msg in payload.get("messages", []):
                content = msg.get("content")
                if isinstance(content, list):
                    cleaned = [
                        block for block in content
                        if not _is_empty_text_block(block)
                    ]
                    if len(cleaned) != len(content):
                        msg["content"] = cleaned
            return payload

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            _sanitize_message_content(messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            _sanitize_message_content(messages)
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    return SanitizedChatOpenAI


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
        SanitizedChatOpenAI = _make_sanitized_chat_openai()
        if frequency_penalty is not None:
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
        if response_format is not None:
            kwargs["model_kwargs"] = {"response_format": response_format}
        return SanitizedChatOpenAI(api_key=api_key, **kwargs)

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if credential.base_url:
            kwargs["base_url"] = credential.base_url
        return ChatAnthropic(api_key=api_key, **kwargs)

    if provider_type == "glm":
        SanitizedChatOpenAI = _make_sanitized_chat_openai()
        base = credential.base_url or "https://api.z.ai/api/paas/v4/"
        kwargs["base_url"] = base
        kwargs["use_responses_api"] = False
        return SanitizedChatOpenAI(api_key=api_key, **kwargs)

    if provider_type == "openai_compatible":
        SanitizedChatOpenAI = _make_sanitized_chat_openai()
        if frequency_penalty is not None:
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
        if response_format is not None:
            kwargs["model_kwargs"] = {"response_format": response_format}
        if credential.base_url:
            kwargs["base_url"] = credential.base_url
        return SanitizedChatOpenAI(api_key=api_key, **kwargs)

    raise ValueError(f"Unsupported provider type: {provider_type}")


def resolve_llm_for_node(node, db: Session | None = None) -> BaseChatModel:
    from database import SessionLocal
    from models.credential import BaseCredential

    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        cc = node.component_config

        if cc.component_type == "ai_model":
            if not cc.model_name or not cc.llm_credential_id:
                raise ValueError(
                    f"Node '{node.node_id}' (ai_model) requires both "
                    "model_name and llm_credential on its config."
                )
            base_cred = db.query(BaseCredential).filter(BaseCredential.id == cc.llm_credential_id).first()
            if not base_cred:
                raise ValueError(
                    f"Credential ID {cc.llm_credential_id} not found for node '{node.node_id}'. "
                    "It may have been deleted."
                )
            llm_cred = base_cred.llm_credential
            if not llm_cred:
                raise ValueError(
                    f"Credential ID {cc.llm_credential_id} for node '{node.node_id}' "
                    "has no LLM provider configuration."
                )
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
                if not base_cred:
                    raise ValueError(
                        f"Credential ID {tc.llm_credential_id} not found for ai_model config "
                        f"linked to node '{node.node_id}'. It may have been deleted."
                    )
                llm_cred = base_cred.llm_credential
                if not llm_cred:
                    raise ValueError(
                        f"Credential ID {tc.llm_credential_id} for ai_model config "
                        f"linked to node '{node.node_id}' has no LLM provider configuration."
                    )
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
    finally:
        if own_session:
            db.close()


def resolve_credential_for_node(node, db: Session | None = None):
    """Resolve the LLMProviderCredential for a node (agent or ai_model).

    Same traversal as resolve_llm_for_node but returns the credential
    instead of the LLM instance. Used for provider detection (e.g. web search).
    """
    from database import SessionLocal
    from models.credential import BaseCredential

    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        cc = node.component_config

        if cc.component_type == "ai_model":
            if not cc.llm_credential_id:
                raise ValueError(f"Node '{node.node_id}' (ai_model) has no credential.")
            base_cred = db.query(BaseCredential).filter(BaseCredential.id == cc.llm_credential_id).first()
            if not base_cred or not base_cred.llm_credential:
                raise ValueError(f"Credential ID {cc.llm_credential_id} not found for node '{node.node_id}'.")
            return base_cred.llm_credential

        if cc.llm_model_config_id:
            from models.node import BaseComponentConfig as BCC
            tc = db.get(BCC, cc.llm_model_config_id)
            if tc and tc.component_type == "ai_model" and tc.llm_credential_id:
                base_cred = db.query(BaseCredential).filter(BaseCredential.id == tc.llm_credential_id).first()
                if not base_cred or not base_cred.llm_credential:
                    raise ValueError(f"Credential not found for ai_model config linked to node '{node.node_id}'.")
                return base_cred.llm_credential

        raise ValueError(f"Node '{node.node_id}' has no connected ai_model node.")
    finally:
        if own_session:
            db.close()
