"""Tests for credentials API — GLM provider coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(db):
    """Create a test FastAPI app with DB overridden to use test session."""
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
def glm_credential(db, user_profile):
    from models.credential import BaseCredential, LLMProviderCredential

    base = BaseCredential(
        user_profile_id=user_profile.id,
        name="GLM Key",
        credential_type="llm",
    )
    db.add(base)
    db.flush()
    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type="glm",
        api_key="test-glm-key",
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


@pytest.fixture
def glm_credential_custom_url(db, user_profile):
    from models.credential import BaseCredential, LLMProviderCredential

    base = BaseCredential(
        user_profile_id=user_profile.id,
        name="GLM Custom URL",
        credential_type="llm",
    )
    db.add(base)
    db.flush()
    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type="glm",
        api_key="test-glm-key",
        base_url="https://custom.glm.api/v4",
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


class TestGLMCredential:
    """Test GLM provider in credentials API."""

    @patch("api.credentials.httpx.get")
    def test_glm_test_credential_success(self, mock_get, auth_client, glm_credential):
        """Test GLM credential test with valid API key returns success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "glm-4"}]}
        mock_get.return_value = mock_response

        resp = auth_client.post(f"/api/v1/credentials/{glm_credential.id}/test/")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("api.credentials.httpx.get")
    def test_glm_test_credential_with_custom_url(self, mock_get, auth_client, glm_credential_custom_url):
        """Test GLM credential test with custom base URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        resp = auth_client.post(f"/api/v1/credentials/{glm_credential_custom_url.id}/test/")

        assert resp.status_code == 200
        # Verify custom URL was used
        call_url = mock_get.call_args[0][0]
        assert "custom.glm.api" in call_url

    @patch("api.credentials.httpx.get")
    def test_glm_list_models(self, mock_get, auth_client, glm_credential):
        """Test listing GLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "glm-4", "object": "model"},
                {"id": "glm-4-plus", "object": "model"},
            ]
        }
        mock_get.return_value = mock_response

        resp = auth_client.get(f"/api/v1/credentials/{glm_credential.id}/models/")

        assert resp.status_code == 200
        models = resp.json()
        ids = [m["id"] for m in models]
        assert "glm-4" in ids
        assert "glm-4-plus" in ids
