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


def _route_provider_to_type(provider: str) -> str:
    """Map a route prefix to a provider_type string.

    Used when ``backend_route`` is set and no DB credential is available.
    """
    _map = {"openai": "openai", "anthropic": "anthropic", "glm": "glm"}
    return _map.get(provider, "openai_compatible")


def _fake_credential_from_route(backend_route: str):
    """Return a minimal credential-like object inferred from a backend route string.

    Used by ``resolve_credential_for_node()`` when only ``backend_route`` is
    configured (no DB credential).  Callers that inspect ``.provider_type``
    (e.g. web-search provider detection) will get a sensible value.
    """
    from collections import namedtuple

    FakeCredential = namedtuple("FakeCredential", ["provider_type", "base_url", "api_key"])
    prefix = backend_route.split("-", 1)[0] if "-" in backend_route else backend_route
    return FakeCredential(
        provider_type=_route_provider_to_type(prefix),
        base_url="",
        api_key="",
    )


def _resolve_backend_name(credential=None, backend_route: str | None = None) -> str:
    """Resolve the agentgateway backend route name.

    Priority:
    1. If *backend_route* is provided (from node config), use it directly.
    2. If *credential* is provided, derive from credential metadata (legacy).
    """
    if backend_route:
        return backend_route

    # Legacy fallback: derive from credential
    if credential is None:
        return ""
    if credential.provider_type in ("openai", "anthropic", "glm"):
        return credential.provider_type
    # openai_compatible: use sanitized name from base credential
    base_name = ""
    if hasattr(credential, "base_credentials") and credential.base_credentials:
        base_name = credential.base_credentials.name
    base_name = base_name or f"custom-{credential.base_credentials_id}"
    return base_name.lower().replace(" ", "-").replace("_", "-")


def create_llm_from_db(
    credential,
    model_name: str,
    *,
    user_profile_id: int | None = None,
    user_role: str | None = None,
    backend_route: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    top_p: float | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    response_format: dict | None = None,
) -> BaseChatModel:
    from config import settings

    # -- agentgateway proxy path --
    if settings.AGENTGATEWAY_ENABLED and settings.AGENTGATEWAY_URL:
        resolved_route = _resolve_backend_name(credential, backend_route)
        return _create_llm_via_agentgateway(
            credential,
            model_name,
            backend_route=resolved_route,
            user_profile_id=user_profile_id,
            user_role=user_role,
            temperature=temperature,
            max_tokens=max_tokens,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            top_p=top_p,
            timeout=timeout,
            max_retries=max_retries,
            response_format=response_format,
        )

    # -- direct provider path (unchanged) --
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


def _create_llm_via_agentgateway(
    credential,
    model_name: str,
    *,
    backend_route: str | None = None,
    user_profile_id: int | None = None,
    user_role: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    top_p: float | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    response_format: dict | None = None,
) -> BaseChatModel:
    """Create an LLM routed through agentgateway.

    When *backend_route* is provided the credential may be ``None`` —
    the route is used directly and the provider type is inferred from the
    route prefix (e.g. ``"anthropic-claude-sonnet"`` → ``"anthropic"``).

    Lazy-imports agentgateway services to avoid circular imports.
    """
    import asyncio

    from config import settings
    from services.agentgateway_client import check_agentgateway_health, create_proxied_llm
    from services.jwt_issuer import mint_llm_token

    # Health check — run async in a sync context (RQ workers may lack a loop).
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. FastAPI endpoint) — create a
        # new loop in a thread to avoid "cannot run nested event loop".
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            ok, msg = pool.submit(
                asyncio.run, check_agentgateway_health(settings.AGENTGATEWAY_URL)
            ).result()
    else:
        ok, msg = asyncio.run(check_agentgateway_health(settings.AGENTGATEWAY_URL))

    if not ok:
        logger.warning("agentgateway health check failed: %s", msg)
        raise RuntimeError(f"agentgateway is unreachable: {msg}")

    # Derive backend_name and provider_type.
    backend_name = backend_route or _resolve_backend_name(credential)
    credential_id = getattr(credential, "base_credentials_id", 0) if credential else 0

    if credential is not None:
        provider_type = credential.provider_type
    elif backend_route:
        # Infer provider from route prefix: "venice-glm-4.7" → "venice" → "openai_compatible"
        prefix = backend_route.split("-", 1)[0] if "-" in backend_route else backend_route
        provider_type = _route_provider_to_type(prefix)
    else:
        provider_type = "openai_compatible"

    jwt_token = mint_llm_token(
        user_profile_id=user_profile_id or 0,
        role=user_role or "admin",
        credential_id=credential_id,
    )

    # Build kwargs to forward to the LangChain constructor.
    extra_kwargs: dict = {}
    if temperature is not None:
        extra_kwargs["temperature"] = temperature
    if max_tokens is not None:
        extra_kwargs["max_tokens"] = max_tokens
    if frequency_penalty is not None:
        extra_kwargs["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        extra_kwargs["presence_penalty"] = presence_penalty
    if top_p is not None:
        extra_kwargs["top_p"] = top_p
    if timeout is not None:
        extra_kwargs["timeout"] = timeout
    if max_retries is not None:
        extra_kwargs["max_retries"] = max_retries
    if response_format is not None:
        extra_kwargs["response_format"] = response_format

    return create_proxied_llm(
        jwt_token=jwt_token,
        provider_type=provider_type,
        backend_name=backend_name,
        model=model_name,
        agentgateway_url=settings.AGENTGATEWAY_URL,
        **extra_kwargs,
    )


def resolve_llm_for_node(node, db: Session | None = None) -> BaseChatModel:
    from database import SessionLocal
    from models.credential import BaseCredential

    own_session = db is None
    if own_session:
        db = SessionLocal()

    # Derive user context from the workflow owner for JWT minting.
    # Falls back to safe defaults when the relationship is not loaded.
    user_profile_id: int | None = None
    user_role: str | None = None
    try:
        workflow = getattr(node, "workflow", None)
        if workflow is not None:
            user_profile_id = getattr(workflow, "owner_id", None)
    except Exception:
        pass  # Relationship not loaded — defaults will be used.

    try:
        cc = node.component_config
        backend_route = getattr(cc, "backend_route", None)

        if cc.component_type == "ai_model":
            # backend_route path: skip credential lookup entirely
            if backend_route:
                if not cc.model_name:
                    raise ValueError(
                        f"Node '{node.node_id}' has backend_route but no model_name."
                    )
                return create_llm_from_db(
                    None,
                    cc.model_name,
                    user_profile_id=user_profile_id,
                    user_role=user_role,
                    backend_route=backend_route,
                    temperature=cc.temperature,
                    max_tokens=cc.max_tokens,
                    frequency_penalty=cc.frequency_penalty,
                    presence_penalty=cc.presence_penalty,
                    top_p=cc.top_p,
                    timeout=cc.timeout,
                    max_retries=cc.max_retries,
                    response_format=cc.response_format,
                )

            # Legacy credential-based path
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
                user_profile_id=user_profile_id,
                user_role=user_role,
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
            if tc and tc.component_type == "ai_model":
                tc_backend_route = getattr(tc, "backend_route", None)

                # backend_route path on referenced config
                if tc_backend_route:
                    if not tc.model_name:
                        raise ValueError(
                            f"ai_model config linked to node '{node.node_id}' "
                            "has backend_route but no model_name."
                        )
                    return create_llm_from_db(
                        None,
                        tc.model_name,
                        user_profile_id=user_profile_id,
                        user_role=user_role,
                        backend_route=tc_backend_route,
                        temperature=tc.temperature,
                        max_tokens=tc.max_tokens,
                        frequency_penalty=tc.frequency_penalty,
                        presence_penalty=tc.presence_penalty,
                        top_p=tc.top_p,
                        timeout=tc.timeout,
                        max_retries=tc.max_retries,
                        response_format=tc.response_format,
                    )

                # Legacy credential-based path
                if tc.model_name and tc.llm_credential_id:
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
                        user_profile_id=user_profile_id,
                        user_role=user_role,
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
        backend_route = getattr(cc, "backend_route", None)

        if cc.component_type == "ai_model":
            # backend_route path: infer provider from route string
            if backend_route and not cc.llm_credential_id:
                return _fake_credential_from_route(backend_route)

            if not cc.llm_credential_id:
                raise ValueError(f"Node '{node.node_id}' (ai_model) has no credential.")
            base_cred = db.query(BaseCredential).filter(BaseCredential.id == cc.llm_credential_id).first()
            if not base_cred or not base_cred.llm_credential:
                raise ValueError(f"Credential ID {cc.llm_credential_id} not found for node '{node.node_id}'.")
            return base_cred.llm_credential

        if cc.llm_model_config_id:
            from models.node import BaseComponentConfig as BCC
            tc = db.get(BCC, cc.llm_model_config_id)
            if tc and tc.component_type == "ai_model":
                tc_backend_route = getattr(tc, "backend_route", None)
                if tc_backend_route and not tc.llm_credential_id:
                    return _fake_credential_from_route(tc_backend_route)
                if tc.llm_credential_id:
                    base_cred = db.query(BaseCredential).filter(BaseCredential.id == tc.llm_credential_id).first()
                    if not base_cred or not base_cred.llm_credential:
                        raise ValueError(f"Credential not found for ai_model config linked to node '{node.node_id}'.")
                    return base_cred.llm_credential

        raise ValueError(f"Node '{node.node_id}' has no connected ai_model node.")
    finally:
        if own_session:
            db.close()
