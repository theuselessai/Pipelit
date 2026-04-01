"""Tests for agentgateway LLM proxy client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.agentgateway_client import (
    check_agentgateway_health,
    create_proxied_llm,
)

AGENTGATEWAY_URL = "http://localhost:4000"
JWT_TOKEN = "eyJ.test.jwt"
MODEL = "gpt-4o"


# ===================================================================
# create_proxied_llm — OpenAI provider
# ===================================================================


class TestCreateProxiedLlmOpenAI:
    def test_returns_chat_openai(self) -> None:
        from langchain_openai import ChatOpenAI

        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai",
            backend_name="openai",
            model=MODEL,
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert isinstance(llm, ChatOpenAI)

    def test_base_url_includes_backend_name(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai",
            backend_name="my-openai",
            model=MODEL,
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert str(llm.openai_api_base) == f"{AGENTGATEWAY_URL}/my-openai"

    def test_jwt_token_set_as_api_key(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai",
            backend_name="openai",
            model=MODEL,
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert llm.openai_api_key.get_secret_value() == JWT_TOKEN

    def test_extra_kwargs_forwarded(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai",
            backend_name="openai",
            model=MODEL,
            agentgateway_url=AGENTGATEWAY_URL,
            temperature=0.5,
            max_tokens=100,
        )

        assert llm.temperature == 0.5
        assert llm.max_tokens == 100

    def test_trailing_slash_stripped_from_url(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai",
            backend_name="openai",
            model=MODEL,
            agentgateway_url="http://localhost:4000/",
        )

        assert str(llm.openai_api_base) == f"{AGENTGATEWAY_URL}/openai"


# ===================================================================
# create_proxied_llm — Anthropic provider
# ===================================================================


class TestCreateProxiedLlmAnthropic:
    def test_returns_chat_anthropic(self) -> None:
        from langchain_anthropic import ChatAnthropic

        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="anthropic",
            backend_name="anthropic",
            model="claude-sonnet-4-20250514",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert isinstance(llm, ChatAnthropic)

    def test_base_url_includes_backend_name(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="anthropic",
            backend_name="my-anthropic",
            model="claude-sonnet-4-20250514",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        # ChatAnthropic stores base_url as anthropic_api_url
        assert str(llm.anthropic_api_url) == f"{AGENTGATEWAY_URL}/my-anthropic"

    def test_bearer_header_injected_via_default_headers(self) -> None:
        """ChatAnthropic sends api_key as x-api-key, not Bearer.

        We inject Authorization: Bearer via default_headers to pass the
        JWT to agentgateway.
        """
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="anthropic",
            backend_name="anthropic",
            model="claude-sonnet-4-20250514",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert llm.default_headers is not None
        assert llm.default_headers["Authorization"] == f"Bearer {JWT_TOKEN}"

    def test_api_key_is_placeholder(self) -> None:
        """api_key is a dummy value — the real key is injected by agentgateway."""
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="anthropic",
            backend_name="anthropic",
            model="claude-sonnet-4-20250514",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert llm.anthropic_api_key.get_secret_value() == "jwt-via-bearer"

    def test_extra_kwargs_forwarded(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="anthropic",
            backend_name="anthropic",
            model="claude-sonnet-4-20250514",
            agentgateway_url=AGENTGATEWAY_URL,
            temperature=0.7,
            max_tokens=200,
        )

        assert llm.temperature == 0.7
        assert llm.max_tokens == 200


# ===================================================================
# create_proxied_llm — GLM provider
# ===================================================================


class TestCreateProxiedLlmGLM:
    def test_returns_chat_openai(self) -> None:
        from langchain_openai import ChatOpenAI

        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="glm",
            backend_name="glm",
            model="glm-4",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert isinstance(llm, ChatOpenAI)

    def test_base_url_correct(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="glm",
            backend_name="glm",
            model="glm-4",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert str(llm.openai_api_base) == f"{AGENTGATEWAY_URL}/glm"

    def test_jwt_token_as_api_key(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="glm",
            backend_name="glm",
            model="glm-4",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert llm.openai_api_key.get_secret_value() == JWT_TOKEN


# ===================================================================
# create_proxied_llm — openai_compatible provider
# ===================================================================


class TestCreateProxiedLlmOpenAICompatible:
    def test_returns_chat_openai(self) -> None:
        from langchain_openai import ChatOpenAI

        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai_compatible",
            backend_name="venice",
            model="llama-3.3-70b",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert isinstance(llm, ChatOpenAI)

    def test_base_url_correct(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai_compatible",
            backend_name="venice",
            model="llama-3.3-70b",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert str(llm.openai_api_base) == f"{AGENTGATEWAY_URL}/venice"

    def test_jwt_token_as_api_key(self) -> None:
        llm = create_proxied_llm(
            jwt_token=JWT_TOKEN,
            provider_type="openai_compatible",
            backend_name="venice",
            model="llama-3.3-70b",
            agentgateway_url=AGENTGATEWAY_URL,
        )

        assert llm.openai_api_key.get_secret_value() == JWT_TOKEN


# ===================================================================
# create_proxied_llm — unsupported provider
# ===================================================================


class TestCreateProxiedLlmUnsupported:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported provider type"):
            create_proxied_llm(
                jwt_token=JWT_TOKEN,
                provider_type="bedrock",
                backend_name="aws",
                model="some-model",
                agentgateway_url=AGENTGATEWAY_URL,
            )


# ===================================================================
# check_agentgateway_health
# ===================================================================


class TestCheckAgentgatewayHealth:
    @pytest.mark.asyncio
    async def test_healthy_401_response(self) -> None:
        """401 means JWT auth is enforced — agentgateway is healthy."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401

        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is True
        assert "JWT auth enforced" in msg

    @pytest.mark.asyncio
    async def test_healthy_403_response(self) -> None:
        """403 also means auth is working — healthy."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403

        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is True
        assert "JWT auth enforced" in msg

    @pytest.mark.asyncio
    async def test_healthy_200_response(self) -> None:
        """200 — agentgateway is up (maybe no auth configured yet)."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200

        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is True
        assert "200" in msg

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """ConnectError means agentgateway is unreachable."""
        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is False
        assert "unreachable" in msg

    @pytest.mark.asyncio
    async def test_timeout_error(self) -> None:
        """TimeoutException means agentgateway did not respond in time."""
        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is False
        assert "timed out" in msg

    @pytest.mark.asyncio
    async def test_unexpected_error(self) -> None:
        """Catch-all for unexpected exceptions."""
        with patch("services.agentgateway_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = RuntimeError("something broke")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            ok, msg = await check_agentgateway_health(AGENTGATEWAY_URL)

        assert ok is False
        assert "health check failed" in msg
