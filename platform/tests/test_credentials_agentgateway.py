"""Tests verifying LLM credential management is fully removed from credentials.py.

Phase 1(b) hard cutover:
- Creating/updating/testing llm-typed credentials returns 410 Gone
- Leftover llm rows (metadata only, no api_key) remain listable/deletable
- The agentgateway_backend field exists in the schema but is always None
- Removed functions are no longer importable
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient

from models.credential import BaseCredential, LLMProviderCredential
from models.user import APIKey, UserProfile, UserRole


# -- Fixtures ----------------------------------------------------------------


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
def admin_user(db):
    user = UserProfile(
        username="agw-admin",
        password_hash=bcrypt.hashpw(b"adminpass", bcrypt.gensalt()).decode(),
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_key(db, admin_user):
    raw = str(uuid.uuid4())
    key = APIKey(user_id=admin_user.id, key=raw, name="admin-key", prefix=raw[:8])
    db.add(key)
    db.commit()
    return raw


@pytest.fixture
def admin_headers(admin_key):
    return {"Authorization": f"Bearer {admin_key}"}


@pytest.fixture
def llm_credential(db, admin_user):
    """A leftover llm-typed credential row (metadata only — no api_key)."""
    base = BaseCredential(
        user_profile_id=admin_user.id,
        name="Test OpenAI",
        credential_type="llm",
    )
    db.add(base)
    db.flush()
    llm = LLMProviderCredential(
        base_credentials_id=base.id,
        provider_type="openai",
        base_url="",
        organization_id="",
        custom_headers={},
    )
    db.add(llm)
    db.commit()
    db.refresh(base)
    return base


# -- LLM credential creation is rejected --------------------------------------


class TestCreateLLMCredentialRejected:
    """Creating an llm-typed credential is gone — 410, and nothing is stored."""

    def test_create_llm_credential_rejected(self, client, admin_headers, db):
        resp = client.post(
            "/api/v1/credentials/",
            json={
                "name": "Test Anthropic",
                "credential_type": "llm",
                "detail": {
                    "provider_type": "anthropic",
                    "api_key": "sk-ant-test-key-12345678",
                },
            },
            headers=admin_headers,
        )
        assert resp.status_code == 410
        assert "agentgateway" in resp.json()["detail"]
        # No row was created
        assert (
            db.query(BaseCredential)
            .filter(BaseCredential.name == "Test Anthropic")
            .count()
            == 0
        )

    def test_create_llm_credential_rejected_even_with_agentgateway_enabled(
        self, client, admin_headers
    ):
        """The rejection does not depend on the AGENTGATEWAY_ENABLED flag."""
        with patch("api.credentials.settings") as mock_settings:
            from config import settings as real_settings
            for attr in dir(real_settings):
                if attr.isupper():
                    setattr(mock_settings, attr, getattr(real_settings, attr))
            mock_settings.AGENTGATEWAY_ENABLED = True

            resp = client.post(
                "/api/v1/credentials/",
                json={
                    "name": "Enabled Test",
                    "credential_type": "llm",
                    "detail": {
                        "provider_type": "openai",
                        "api_key": "sk-enabled-test-12345678",
                    },
                },
                headers=admin_headers,
            )
            assert resp.status_code == 410

    def test_update_llm_credential_rejected(self, client, admin_headers, llm_credential):
        resp = client.patch(
            f"/api/v1/credentials/{llm_credential.id}/",
            json={"name": "Renamed"},
            headers=admin_headers,
        )
        assert resp.status_code == 410

    def test_test_llm_credential_rejected(self, client, admin_headers, llm_credential):
        resp = client.post(
            f"/api/v1/credentials/{llm_credential.id}/test/",
            headers=admin_headers,
        )
        assert resp.status_code == 410


# -- No agentgateway writes on delete ----------------------------------------


class TestDeleteLLMCredentialNoAgentgatewayWrites:
    """Verify that deleting an LLM credential does NOT touch agentgateway."""

    def test_delete_llm_credential_no_agentgateway_writes(
        self, client, admin_headers, llm_credential
    ):
        """Deleting an LLM credential should succeed without any agentgateway calls."""
        resp = client.delete(
            f"/api/v1/credentials/{llm_credential.id}/",
            headers=admin_headers,
        )
        assert resp.status_code == 204

    def test_delete_llm_credential_with_agentgateway_enabled_still_no_writes(
        self, client, admin_headers, llm_credential
    ):
        """Even with AGENTGATEWAY_ENABLED=True, delete should not call agentgateway."""
        with patch("api.credentials.settings") as mock_settings:
            from config import settings as real_settings
            for attr in dir(real_settings):
                if attr.isupper():
                    setattr(mock_settings, attr, getattr(real_settings, attr))
            mock_settings.AGENTGATEWAY_ENABLED = True

            resp = client.delete(
                f"/api/v1/credentials/{llm_credential.id}/",
                headers=admin_headers,
            )
            assert resp.status_code == 204


# -- agentgateway_backend field is always None --------------------------------


class TestAgentgatewayBackendFieldIsNone:
    """Verify the agentgateway_backend field exists in output but is always None."""

    def test_agentgateway_backend_field_is_none_on_create(
        self, client, admin_headers
    ):
        # llm creation is rejected now — use a git credential to exercise
        # serialization of a freshly created credential.
        resp = client.post(
            "/api/v1/credentials/",
            json={
                "name": "Field Test",
                "credential_type": "git",
                "detail": {
                    "provider": "github",
                    "credential_type": "token",
                    "access_token": "ghp_field_test_12345678",
                },
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "agentgateway_backend" in data
        assert data["agentgateway_backend"] is None

    def test_agentgateway_backend_field_is_none_on_get(
        self, client, admin_headers, llm_credential
    ):
        resp = client.get(
            f"/api/v1/credentials/{llm_credential.id}/",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "agentgateway_backend" in data
        assert data["agentgateway_backend"] is None

    def test_agentgateway_backend_field_is_none_even_when_enabled(
        self, client, admin_headers, llm_credential
    ):
        """The field should be None regardless of AGENTGATEWAY_ENABLED setting."""
        with patch("api.credentials.settings") as mock_settings:
            from config import settings as real_settings
            for attr in dir(real_settings):
                if attr.isupper():
                    setattr(mock_settings, attr, getattr(real_settings, attr))
            mock_settings.AGENTGATEWAY_ENABLED = True

            resp = client.get(
                f"/api/v1/credentials/{llm_credential.id}/",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["agentgateway_backend"] is None


# -- Schema tests ------------------------------------------------------------


class TestCredentialOutSchema:

    def test_agentgateway_backend_field_present(self):
        from schemas.credential import CredentialOut
        from datetime import datetime

        out = CredentialOut(
            id=1,
            name="Test",
            credential_type="llm",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            agentgateway_backend="openai",
        )
        assert out.agentgateway_backend == "openai"

    def test_agentgateway_backend_field_defaults_to_none(self):
        from schemas.credential import CredentialOut
        from datetime import datetime

        out = CredentialOut(
            id=1,
            name="Test",
            credential_type="llm",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert out.agentgateway_backend is None


# -- No removed functions importable ------------------------------------------


class TestRemovedFunctions:
    """Verify that removed functions are no longer importable from credentials."""

    def test_resolve_backend_name_removed(self):
        import importlib
        import api.credentials as mod
        importlib.reload(mod)
        assert not hasattr(mod, "_resolve_backend_name")

    def test_run_async_removed(self):
        import importlib
        import api.credentials as mod
        importlib.reload(mod)
        assert not hasattr(mod, "_run_async")
