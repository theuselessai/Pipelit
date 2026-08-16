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

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
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


class TestMailboxCredentialTest:
    """A mailbox credential must be testable from the Credentials page.

    Without it, a bad value is only discovered mid-execution: an admin secret
    pasted one character short reached the service, was correctly refused, and
    surfaced as a failed workflow run rather than as a bad credential.
    """

    def _tool(self, secret="s", config=None):
        return SimpleNamespace(
            tool_type="mailbox",
            config={"base_url": "https://mail.invalid", "domain": "mail.invalid"} if config is None else config,
            secret=secret,
        )

    def test_valid_credential_passes(self):
        from api.credentials import _test_tool_credential

        with patch("services.mailbox.list_unknown_mails", return_value=[]):
            result = _test_tool_credential(self._tool())

        assert result["ok"] is True

    def test_rejected_secret_reports_the_services_own_message(self):
        from api.credentials import _test_tool_credential
        from services.mailbox import MailboxError

        with patch("services.mailbox.list_unknown_mails",
                   side_effect=MailboxError("GET /admin/mails_unknow failed: You need to provide "
                                            "the admin password to access this page", 401)):
            result = _test_tool_credential(self._tool(secret="truncated"))

        assert result["ok"] is False
        assert "admin password" in result["error"]

    def test_unreachable_host_is_reported_not_raised(self):
        """An unreachable host is the likeliest thing a connection test meets;
        letting httpx escape turns the endpoint into a 500."""
        from api.credentials import _test_tool_credential

        with patch("services.mailbox.list_unknown_mails",
                   side_effect=httpx.ConnectError("Name or service not known")):
            result = _test_tool_credential(self._tool())

        assert result["ok"] is False
        assert "Could not reach" in result["error"]

    def test_missing_fields_name_the_field(self):
        from api.credentials import _test_tool_credential

        result = _test_tool_credential(self._tool(secret=""))

        assert result["ok"] is False
        assert "admin_auth" in result["error"]

    def test_the_secret_is_never_echoed_back(self):
        from api.credentials import _test_tool_credential
        from services.mailbox import MailboxError

        secret = "super-secret-admin-auth"
        with patch("services.mailbox.list_unknown_mails", side_effect=MailboxError("nope", 401)):
            result = _test_tool_credential(self._tool(secret=secret))

        assert secret not in json.dumps(result)

    def test_an_untested_tool_type_says_so(self):
        """Rather than the misleading 'LLM credential not found' 404 it used to give."""
        from api.credentials import _test_tool_credential

        result = _test_tool_credential(
            SimpleNamespace(tool_type="searxng", config={"url": "http://x"}, secret="")
        )

        assert result["ok"] is False
        assert "searxng" in result["error"]


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
