"""Tests for credentials API — GLM (LLM-typed) credentials are rejected.

Phase 1(b) hard cutover: pipelit no longer stores or tests LLM provider
keys — agentgateway is the sole holder. Direct-provider test/models calls
for GLM (and every other LLM provider) return 410 Gone.
"""

from __future__ import annotations

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
    """A leftover GLM llm-typed credential row (metadata only, no api_key)."""
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
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


class TestGLMCredentialRejected:
    """LLM credential management (create/test/models) is gone — 410."""

    def test_glm_create_rejected(self, auth_client):
        resp = auth_client.post(
            "/api/v1/credentials/",
            json={
                "name": "GLM Key",
                "credential_type": "llm",
                "detail": {"provider_type": "glm", "api_key": "test-glm-key"},
            },
        )
        assert resp.status_code == 410
        assert "agentgateway" in resp.json()["detail"]

    def test_glm_test_credential_rejected(self, auth_client, glm_credential):
        resp = auth_client.post(f"/api/v1/credentials/{glm_credential.id}/test/")
        assert resp.status_code == 410
        assert "agentgateway" in resp.json()["detail"]

    def test_glm_list_models_rejected(self, auth_client, glm_credential):
        resp = auth_client.get(f"/api/v1/credentials/{glm_credential.id}/models/")
        assert resp.status_code == 410
        assert "agentgateway" in resp.json()["detail"]

    def test_glm_update_rejected(self, auth_client, glm_credential):
        resp = auth_client.patch(
            f"/api/v1/credentials/{glm_credential.id}/",
            json={"detail": {"api_key": "new-key"}},
        )
        assert resp.status_code == 410

    def test_glm_leftover_row_still_deletable(self, auth_client, glm_credential):
        """Cleanup of legacy llm rows keeps working."""
        resp = auth_client.delete(f"/api/v1/credentials/{glm_credential.id}/")
        assert resp.status_code == 204
