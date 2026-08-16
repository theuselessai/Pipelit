"""Tests for keyless LLM credentials — local inference servers.

A local inference server (llama.cpp, vLLM, LM Studio, Ollama, MLX) needs no API
key, so an `openai_compatible` credential with an empty `api_key` is a valid
setup rather than a misconfiguration.  Two separate places used to reject it:

  * the connection test sent a literal ``"Bearer "``, which httpx refuses to
    transmit (``LocalProtocolError: Illegal header value b'Bearer '``), so the
    request never left the process and the test reported a failure that had
    nothing to do with the server;
  * ``create_llm_from_db`` handed the empty string to the OpenAI SDK, which
    raises ``OpenAIError: Missing credentials``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def keyless_credential(db, user_profile):
    """An openai_compatible credential pointing at a local server, no API key."""
    from models.credential import BaseCredential, LLMProviderCredential

    base = BaseCredential(
        user_profile_id=user_profile.id,
        name="local inference",
        credential_type="llm",
    )
    db.add(base)
    db.flush()
    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type="openai_compatible",
        api_key="",
        base_url="http://192.168.0.73:8080/v1",
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


class TestAuthHeaders:
    def test_key_present_sends_bearer(self):
        from api.credentials import _auth_headers

        assert _auth_headers("sk-abc") == {"Authorization": "Bearer sk-abc"}

    def test_empty_key_sends_no_header(self):
        from api.credentials import _auth_headers

        assert _auth_headers("") == {}

    def test_none_key_sends_no_header(self):
        from api.credentials import _auth_headers

        assert _auth_headers(None) == {}

    @pytest.mark.parametrize("key", ["", None, "  ", "sk-abc"])
    def test_never_emits_a_token_less_bearer(self, key):
        """No input may produce ``Bearer`` with nothing after it.

        That is the malformed value httpx rejects at send time (it validates
        when serializing the request, not when the Headers object is built), so
        the guarantee has to hold here rather than being caught downstream.
        """
        from api.credentials import _auth_headers

        header = _auth_headers(key).get("Authorization")

        if header is not None:
            assert header.startswith("Bearer ")
            assert header[len("Bearer "):].strip(), f"empty token in {header!r}"


class TestKeylessConnectionTest:
    def test_test_endpoint_omits_authorization(self, auth_client, keyless_credential):
        with patch("api.credentials.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="{}")
            resp = auth_client.post(f"/api/v1/credentials/{keyless_credential.id}/test/")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "Authorization" not in mock_get.call_args.kwargs["headers"]

    def test_test_endpoint_targets_the_configured_base_url(self, auth_client, keyless_credential):
        with patch("api.credentials.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="{}")
            auth_client.post(f"/api/v1/credentials/{keyless_credential.id}/test/")

        assert mock_get.call_args.args[0] == "http://192.168.0.73:8080/v1/models"


class TestKeylessRuntimeClient:
    def test_client_builds_without_an_api_key(self):
        """The OpenAI SDK refuses to construct with an empty key; stand one in."""
        from services.llm import create_llm_from_db

        cred = SimpleNamespace(
            provider_type="openai_compatible",
            api_key="",
            base_url="http://192.168.0.73:8080/v1",
        )

        llm = create_llm_from_db(cred, "some-local-model")

        assert str(llm.openai_api_base) == "http://192.168.0.73:8080/v1"

    def test_real_key_is_not_replaced(self):
        from services.llm import create_llm_from_db

        cred = SimpleNamespace(
            provider_type="openai_compatible",
            api_key="sk-real-key",
            base_url="http://example.invalid/v1",
        )

        llm = create_llm_from_db(cred, "some-model")

        assert llm.openai_api_key.get_secret_value() == "sk-real-key"
