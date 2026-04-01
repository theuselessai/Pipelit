"""LangChain LLM client factory routing through agentgateway.

Creates ``BaseChatModel`` instances whose ``base_url`` points at the
agentgateway LLM proxy (port 4000 by default). The JWT issued by
``jwt_issuer.mint_llm_token()`` is passed as the Bearer token.
agentgateway validates it, enforces CEL authorization rules, then
proxies the request to the upstream provider using the real API key
stored in ``config.d/backends/<name>.yaml``.

**Auth header behaviour by provider:**

* **OpenAI / GLM / openai_compatible** — ``ChatOpenAI(api_key=jwt)``
  sends ``Authorization: Bearer <jwt>``.  Works natively.

* **Anthropic** — The Anthropic SDK sends the api_key as ``x-api-key``,
  *not* ``Authorization: Bearer``.  agentgateway validates the JWT from
  the ``Authorization`` header.  To work around this we pass the JWT via
  ``default_headers={"Authorization": "Bearer <jwt>"}`` and set
  ``api_key`` to a dummy value (``"jwt-via-bearer"``).  The upstream
  ``x-api-key`` header is replaced by agentgateway's ``backendAuth``
  before proxying, so the dummy value never reaches the real API.
"""

from __future__ import annotations

import logging

import httpx
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Supported provider types — must match credential.provider_type values.
_OPENAI_LIKE_PROVIDERS = {"openai", "glm", "openai_compatible", "openai-compatible"}


def create_proxied_llm(
    jwt_token: str,
    provider_type: str,
    backend_name: str,
    model: str,
    agentgateway_url: str,
    **kwargs,
) -> BaseChatModel:
    """Create a LangChain chat model that routes through agentgateway.

    Parameters
    ----------
    jwt_token:
        Short-lived ES256 JWT from ``jwt_issuer.mint_llm_token()``.
    provider_type:
        One of ``"openai"``, ``"anthropic"``, ``"glm"``,
        ``"openai_compatible"``.
    backend_name:
        agentgateway backend name used for path-based routing.
        URL becomes ``{agentgateway_url}/{backend_name}/...``.
    model:
        Model name, e.g. ``"gpt-4o"`` or ``"claude-sonnet-4-20250514"``.
    agentgateway_url:
        agentgateway LLM listener address, e.g. ``http://localhost:4000``.
    **kwargs:
        Forwarded to the LangChain constructor (``temperature``,
        ``max_tokens``, etc.).

    Returns
    -------
    BaseChatModel
        A LangChain chat model pointing at the agentgateway proxy.
    """
    base_url = f"{agentgateway_url.rstrip('/')}/{backend_name}"

    if provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # ChatAnthropic → Anthropic SDK sends api_key as ``x-api-key``.
        # agentgateway expects the JWT in the ``Authorization: Bearer`` header.
        # We inject the Bearer header via ``default_headers`` and use a
        # placeholder api_key (the real key is injected by agentgateway).
        return ChatAnthropic(
            api_key="jwt-via-bearer",
            base_url=base_url,
            model=model,
            default_headers={"Authorization": f"Bearer {jwt_token}"},
            **kwargs,
        )

    if provider_type not in _OPENAI_LIKE_PROVIDERS:
        raise ValueError(
            f"Unsupported provider type for agentgateway proxy: {provider_type!r}. "
            f"Expected one of: openai, anthropic, glm, openai_compatible."
        )

    # OpenAI-like providers: ChatOpenAI sends api_key as Bearer natively.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=jwt_token,
        base_url=base_url,
        model=model,
        **kwargs,
    )


async def check_agentgateway_health(agentgateway_url: str) -> tuple[bool, str]:
    """Check whether agentgateway is reachable.

    Returns ``(ok, message)`` where *ok* is ``True`` when the service
    responds (even with 401/403 — that means JWT auth is enforced, which
    is the expected healthy state).
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{agentgateway_url.rstrip('/')}/")
            # 401/403 means agentgateway is up and enforcing JWT auth — healthy.
            if resp.status_code in (401, 403):
                return True, "agentgateway is running (JWT auth enforced)"
            return True, f"agentgateway responded with {resp.status_code}"
    except httpx.ConnectError:
        return (
            False,
            f"agentgateway at {agentgateway_url} is unreachable. "
            "Check that agentgateway is running.",
        )
    except httpx.TimeoutException:
        return (
            False,
            f"agentgateway at {agentgateway_url} timed out after 5 seconds.",
        )
    except Exception as exc:
        return False, f"agentgateway health check failed: {exc}"
