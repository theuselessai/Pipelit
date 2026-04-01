"""Tests for the Providers API endpoints (/api/v1/providers/)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

# Module path for patching agentgateway_config service functions.
# Endpoint functions use local imports so we patch on the service module.
_AGW = "services.agentgateway_config"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(db):
    """Create a test FastAPI app with DB overridden to use test session."""
    from main import app as _app
    from database import get_db

    def _override_get_db():
        yield db

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    """Authenticated client (admin user from conftest)."""
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def normal_user(db):
    """Create a non-admin user with an API key."""
    import uuid

    import bcrypt
    from models.user import APIKey, UserProfile, UserRole

    profile = UserProfile(
        username="normaluser",
        password_hash=bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode(),
        external_user_id="normal-999",
        role=UserRole.NORMAL,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    raw = str(uuid.uuid4())
    key = APIKey(user_id=profile.id, key=raw, name="normal-key", prefix=raw[:8])
    db.add(key)
    db.commit()
    db.refresh(key)
    return profile, key


@pytest.fixture
def normal_client(client, normal_user):
    """Authenticated client for a normal (non-admin) user."""
    _, key = normal_user
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client


# ---------------------------------------------------------------------------
# Mocks for agentgateway config service
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_agw_enabled():
    """Mock settings.AGENTGATEWAY_ENABLED = True."""
    with patch("api.providers.settings") as mock_settings:
        mock_settings.AGENTGATEWAY_ENABLED = True
        mock_settings.AGENTGATEWAY_DIR = "/tmp/fake-agw"
        mock_settings.FIELD_ENCRYPTION_KEY = "test-key"
        yield mock_settings


@pytest.fixture
def mock_agw_disabled():
    """Mock settings.AGENTGATEWAY_ENABLED = False."""
    with patch("api.providers.settings") as mock_settings:
        mock_settings.AGENTGATEWAY_ENABLED = False
        yield mock_settings


# ---------------------------------------------------------------------------
# AGENTGATEWAY_ENABLED guard
# ---------------------------------------------------------------------------


class TestAgentgatewayGuard:
    """All endpoints should return 404 when AGENTGATEWAY_ENABLED is False."""

    def test_create_provider_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.post("/api/v1/providers/", json={
            "provider": "openai", "provider_type": "openai",
            "api_key": "sk-test", "base_url": "",
        })
        assert resp.status_code == 404

    def test_list_providers_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.get("/api/v1/providers/")
        assert resp.status_code == 404

    def test_delete_provider_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.delete("/api/v1/providers/openai/")
        assert resp.status_code == 404

    def test_fetch_models_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.get("/api/v1/providers/openai/fetch-models/")
        assert resp.status_code == 404

    def test_add_models_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.post("/api/v1/providers/openai/models/", json={"models": []})
        assert resp.status_code == 404

    def test_delete_model_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.delete("/api/v1/providers/openai/models/gpt-4o/")
        assert resp.status_code == 404

    def test_list_models_disabled(self, auth_client, mock_agw_disabled):
        resp = auth_client.get("/api/v1/providers/openai/models/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin-only enforcement
# ---------------------------------------------------------------------------


class TestAdminOnly:
    """Non-admin users should get 403 on all endpoints."""

    def test_create_provider_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.post("/api/v1/providers/", json={
            "provider": "openai", "provider_type": "openai",
            "api_key": "sk-test", "base_url": "",
        })
        assert resp.status_code == 403

    def test_list_providers_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.get("/api/v1/providers/")
        assert resp.status_code == 403

    def test_delete_provider_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.delete("/api/v1/providers/openai/")
        assert resp.status_code == 403

    def test_fetch_models_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.get("/api/v1/providers/openai/fetch-models/")
        assert resp.status_code == 403

    def test_add_models_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.post("/api/v1/providers/openai/models/", json={"models": []})
        assert resp.status_code == 403

    def test_delete_model_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.delete("/api/v1/providers/openai/models/gpt-4o/")
        assert resp.status_code == 403

    def test_list_models_non_admin(self, normal_client, mock_agw_enabled):
        resp = normal_client.get("/api/v1/providers/openai/models/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Create provider
# ---------------------------------------------------------------------------


class TestCreateProvider:
    @patch(f"{_AGW}.reassemble_config")
    @patch(f"{_AGW}.add_provider")
    @patch(f"{_AGW}.write_provider_key")
    def test_create_provider_calls_services(
        self, mock_write_key, mock_add_provider, mock_reassemble,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.post("/api/v1/providers/", json={
            "provider": "venice",
            "provider_type": "openai_compatible",
            "api_key": "sk-venice-123",
            "base_url": "https://api.venice.ai/api/v1",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["provider"] == "venice"
        assert data["provider_type"] == "openai_compatible"
        assert data["models"] == []

        mock_write_key.assert_called_once_with("venice", "sk-venice-123")
        mock_add_provider.assert_called_once()
        call_kwargs = mock_add_provider.call_args
        assert call_kwargs[1]["provider"] == "venice" or call_kwargs[0][0] == "venice"
        mock_reassemble.assert_called_once()

    @patch(f"{_AGW}.reassemble_config")
    @patch(f"{_AGW}.add_provider")
    @patch(f"{_AGW}.write_provider_key")
    def test_create_provider_url_parsing(
        self, mock_write_key, mock_add_provider, mock_reassemble,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.post("/api/v1/providers/", json={
            "provider": "custom",
            "provider_type": "openai_compatible",
            "api_key": "sk-test",
            "base_url": "https://api.example.com:8443/v1",
        })
        assert resp.status_code == 201

        call_kwargs = mock_add_provider.call_args[1]
        assert call_kwargs["host_override"] == "api.example.com:8443"
        assert "/chat/completions" in call_kwargs["path_override"]

    @patch(f"{_AGW}.reassemble_config")
    @patch(f"{_AGW}.add_provider")
    @patch(f"{_AGW}.write_provider_key")
    def test_create_anthropic_provider_path_suffix(
        self, mock_write_key, mock_add_provider, mock_reassemble,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.post("/api/v1/providers/", json={
            "provider": "anthropic",
            "provider_type": "anthropic",
            "api_key": "sk-ant-test",
            "base_url": "https://api.anthropic.com/v1",
        })
        assert resp.status_code == 201

        call_kwargs = mock_add_provider.call_args[1]
        assert call_kwargs["path_override"].endswith("/messages")

    @patch(f"{_AGW}.reassemble_config")
    @patch(f"{_AGW}.add_provider")
    @patch(f"{_AGW}.write_provider_key")
    def test_create_provider_no_base_url(
        self, mock_write_key, mock_add_provider, mock_reassemble,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.post("/api/v1/providers/", json={
            "provider": "openai",
            "provider_type": "openai",
            "api_key": "sk-openai",
            "base_url": "",
        })
        assert resp.status_code == 201
        call_kwargs = mock_add_provider.call_args[1]
        assert call_kwargs["host_override"] == ""
        assert call_kwargs["path_override"] == ""


# ---------------------------------------------------------------------------
# List providers
# ---------------------------------------------------------------------------


class TestListProviders:
    @patch(f"{_AGW}.list_models", return_value=[
        {"slug": "gpt-4o", "model_name": "gpt-4o", "route": "openai-gpt-4o"},
    ])
    @patch(f"{_AGW}.get_provider_config", return_value={
        "provider": {"openAI": {}},
        "hostOverride": "api.openai.com:443",
    })
    @patch(f"{_AGW}.list_providers", return_value=["openai"])
    def test_list_providers_returns_structure(
        self, mock_list, mock_config, mock_models,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.get("/api/v1/providers/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["provider"] == "openai"
        assert data[0]["provider_type"] == "openai"
        assert len(data[0]["models"]) == 1

    @patch(f"{_AGW}.list_providers", return_value=[])
    def test_list_providers_empty(self, mock_list, auth_client, mock_agw_enabled):
        resp = auth_client.get("/api/v1/providers/")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Delete provider
# ---------------------------------------------------------------------------


class TestDeleteProvider:
    @patch(f"{_AGW}.remove_provider")
    def test_delete_provider_calls_service(
        self, mock_remove, auth_client, mock_agw_enabled,
    ):
        resp = auth_client.delete("/api/v1/providers/venice/")
        assert resp.status_code == 204
        mock_remove.assert_called_once_with("venice")


# ---------------------------------------------------------------------------
# Add models (batch)
# ---------------------------------------------------------------------------


class TestAddModels:
    @patch(f"{_AGW}.list_models", return_value=[
        {"slug": "gpt-4o", "model_name": "gpt-4o", "route": "openai-gpt-4o"},
        {"slug": "gpt-4o-mini", "model_name": "gpt-4o-mini", "route": "openai-gpt-4o-mini"},
    ])
    @patch(f"{_AGW}.reassemble_config")
    @patch(f"{_AGW}.add_model")
    def test_add_models_batch(
        self, mock_add_model, mock_reassemble, mock_list_models,
        auth_client, mock_agw_enabled,
    ):
        resp = auth_client.post("/api/v1/providers/openai/models/", json={
            "models": [
                {"slug": "gpt-4o", "model_name": "gpt-4o"},
                {"slug": "gpt-4o-mini", "model_name": "gpt-4o-mini"},
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["provider"] == "openai"
        assert len(data["models"]) == 2

        # Each model added with reassemble=False
        assert mock_add_model.call_count == 2
        for call in mock_add_model.call_args_list:
            assert call[1]["reassemble"] is False

        # Single reassemble at the end
        mock_reassemble.assert_called_once()


# ---------------------------------------------------------------------------
# Delete model
# ---------------------------------------------------------------------------


class TestDeleteModel:
    @patch(f"{_AGW}.remove_model")
    def test_delete_model_calls_service(
        self, mock_remove, auth_client, mock_agw_enabled,
    ):
        resp = auth_client.delete("/api/v1/providers/openai/models/gpt-4o/")
        assert resp.status_code == 204
        mock_remove.assert_called_once_with("openai", "gpt-4o")


# ---------------------------------------------------------------------------
# List models
# ---------------------------------------------------------------------------


class TestListModels:
    @patch(f"{_AGW}.list_models", return_value=[
        {"slug": "gpt-4o", "model_name": "gpt-4o", "route": "openai-gpt-4o"},
    ])
    def test_list_models_returns_list(
        self, mock_list, auth_client, mock_agw_enabled,
    ):
        resp = auth_client.get("/api/v1/providers/openai/models/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["slug"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Fetch models (from provider API)
# ---------------------------------------------------------------------------


class TestFetchModels:
    @patch("api.providers._fetch_provider_models")
    def test_fetch_models_returns_list(
        self, mock_fetch, auth_client, mock_agw_enabled,
    ):
        mock_fetch.return_value = [
            {"id": "gpt-4o", "name": "gpt-4o"},
            {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
        ]
        resp = auth_client.get("/api/v1/providers/openai/fetch-models/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "gpt-4o"

    @patch("api.providers._fetch_provider_models")
    def test_fetch_models_provider_error(
        self, mock_fetch, auth_client, mock_agw_enabled,
    ):
        mock_fetch.side_effect = Exception("Connection refused")
        resp = auth_client.get("/api/v1/providers/openai/fetch-models/")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# URL parsing unit tests
# ---------------------------------------------------------------------------


class TestParseBaseUrl:
    def test_empty_url(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("", "openai")
        assert host == ""
        assert path == ""

    def test_openai_standard(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("https://api.openai.com/v1", "openai")
        assert host == "api.openai.com:443"
        assert path == "/v1/chat/completions"

    def test_anthropic_standard(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("https://api.anthropic.com/v1", "anthropic")
        assert host == "api.anthropic.com:443"
        assert path == "/v1/messages"

    def test_custom_port(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("https://api.example.com:8443/v1", "openai_compatible")
        assert host == "api.example.com:8443"
        assert path == "/v1/chat/completions"

    def test_http_default_port(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("http://localhost/v1", "openai_compatible")
        assert host == "localhost:80"
        assert path == "/v1/chat/completions"

    def test_already_has_suffix_openai(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url(
            "https://api.example.com/v1/chat/completions", "openai_compatible",
        )
        assert path == "/v1/chat/completions"

    def test_already_has_suffix_anthropic(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url(
            "https://api.anthropic.com/v1/messages", "anthropic",
        )
        assert path == "/v1/messages"

    def test_glm_gets_chat_completions(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("https://api.z.ai/api/paas/v4", "glm")
        assert path == "/api/paas/v4/chat/completions"

    def test_trailing_slash_stripped(self):
        from api.providers import _parse_base_url

        host, path = _parse_base_url("https://api.openai.com/v1/", "openai")
        assert path == "/v1/chat/completions"
