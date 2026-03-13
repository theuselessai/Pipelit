"""Comprehensive tests for user management API endpoints.

Covers: CRUD users, self-service, API key management, input validation,
last-admin demotion guard, and key expiration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient

from models.user import APIKey, UserProfile, UserRole


# ── Fixtures ─────────────────────────────────────────────────────────────────


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
        username="admin-user",
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
    key = APIKey(user_id=admin_user.id, key=raw, name="default", prefix=raw[:8])
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@pytest.fixture
def admin_client(client, admin_key):
    client.headers["Authorization"] = f"Bearer {admin_key.key}"
    return client


@pytest.fixture
def normal_user(db):
    user = UserProfile(
        username="normal-user",
        password_hash=bcrypt.hashpw(b"normalpass", bcrypt.gensalt()).decode(),
        role=UserRole.NORMAL,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def normal_key(db, normal_user):
    raw = str(uuid.uuid4())
    key = APIKey(user_id=normal_user.id, key=raw, name="default", prefix=raw[:8])
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@pytest.fixture
def normal_client(client, normal_key):
    c = TestClient(client.app)
    c.headers["Authorization"] = f"Bearer {normal_key.key}"
    return c


# ── TestCreateUser ───────────────────────────────────────────────────────────


class TestCreateUser:
    """POST /api/v1/users/"""

    def test_admin_creates_user(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "newuser", "password": "securepass1"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "normal"
        assert "id" in data

    def test_duplicate_username_409(self, admin_client):
        admin_client.post(
            "/api/v1/users/",
            json={"username": "dup", "password": "securepass1"},
        )
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "dup", "password": "securepass2"},
        )
        assert resp.status_code == 409

    def test_password_too_short_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "shortpw", "password": "short"},
        )
        assert resp.status_code == 422

    def test_invalid_role_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "badrole", "password": "securepass1", "role": "superadmin"},
        )
        assert resp.status_code == 422

    def test_empty_username_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "", "password": "securepass1"},
        )
        assert resp.status_code == 422

    def test_normal_user_forbidden(self, normal_client):
        resp = normal_client.post(
            "/api/v1/users/",
            json={"username": "nope", "password": "securepass1"},
        )
        assert resp.status_code == 403


# ── TestListUsers ────────────────────────────────────────────────────────────


class TestListUsers:
    """GET /api/v1/users/"""

    def test_admin_lists_users_with_pagination(self, admin_client, admin_user, normal_user):
        resp = admin_client.get("/api/v1/users/?offset=0&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        usernames = [u["username"] for u in data["users"]]
        assert "admin-user" in usernames
        assert "normal-user" in usernames

    def test_normal_user_forbidden(self, normal_client):
        resp = normal_client.get("/api/v1/users/")
        assert resp.status_code == 403


# ── TestGetUser ──────────────────────────────────────────────────────────────


class TestGetUser:
    """GET /api/v1/users/{id}"""

    def test_admin_gets_user(self, admin_client, normal_user):
        resp = admin_client.get(f"/api/v1/users/{normal_user.id}")
        assert resp.status_code == 200
        assert resp.json()["username"] == "normal-user"

    def test_nonexistent_user_404(self, admin_client):
        resp = admin_client.get("/api/v1/users/99999")
        assert resp.status_code == 404

    def test_normal_user_forbidden(self, normal_client, admin_user):
        resp = normal_client.get(f"/api/v1/users/{admin_user.id}")
        assert resp.status_code == 403


# ── TestUpdateUser ───────────────────────────────────────────────────────────


class TestUpdateUser:
    """PATCH /api/v1/users/{id}"""

    def test_admin_updates_role(self, admin_client, db, normal_user):
        resp = admin_client.patch(
            f"/api/v1/users/{normal_user.id}",
            json={"role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_admin_updates_password(self, admin_client, normal_user):
        resp = admin_client.patch(
            f"/api/v1/users/{normal_user.id}",
            json={"password": "newpassword123"},
        )
        assert resp.status_code == 200

    def test_prevent_demoting_last_admin(self, admin_client, admin_user):
        resp = admin_client.patch(
            f"/api/v1/users/{admin_user.id}",
            json={"role": "normal"},
        )
        assert resp.status_code == 409
        assert "last admin" in resp.json()["detail"].lower()

    def test_nonexistent_user_404(self, admin_client):
        resp = admin_client.patch(
            "/api/v1/users/99999",
            json={"role": "admin"},
        )
        assert resp.status_code == 404

    def test_normal_user_forbidden(self, normal_client, admin_user):
        resp = normal_client.patch(
            f"/api/v1/users/{admin_user.id}",
            json={"role": "normal"},
        )
        assert resp.status_code == 403


# ── TestDeleteUser ───────────────────────────────────────────────────────────


class TestDeleteUser:
    """DELETE /api/v1/users/{id}"""

    def test_admin_soft_deletes_user(self, admin_client, db, normal_user, normal_key):
        resp = admin_client.delete(f"/api/v1/users/{normal_user.id}")
        assert resp.status_code == 204
        # Keys should be deactivated
        db.refresh(normal_key)
        assert normal_key.is_active is False

    def test_nonexistent_user_404(self, admin_client):
        resp = admin_client.delete("/api/v1/users/99999")
        assert resp.status_code == 404

    def test_normal_user_forbidden(self, normal_client, admin_user):
        resp = normal_client.delete(f"/api/v1/users/{admin_user.id}")
        assert resp.status_code == 403


# ── TestSelfService ──────────────────────────────────────────────────────────


class TestSelfService:
    """Self-service endpoints under /api/v1/users/me*"""

    def test_get_own_profile(self, normal_client, normal_user):
        resp = normal_client.get("/api/v1/users/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == "normal-user"

    def test_update_own_password(self, normal_client):
        resp = normal_client.patch(
            "/api/v1/users/me",
            json={"password": "newpassword123"},
        )
        assert resp.status_code == 200

    def test_update_own_name(self, normal_client):
        resp = normal_client.patch(
            "/api/v1/users/me",
            json={"first_name": "Alice", "last_name": "Smith"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["first_name"] == "Alice"
        assert data["last_name"] == "Smith"

    def test_cannot_change_role_via_self_update(self, normal_client):
        resp = normal_client.patch(
            "/api/v1/users/me",
            json={"role": "admin"},
        )
        # role field not in SelfUpdateIn → should be ignored (422 or 200 with no change)
        if resp.status_code == 200:
            assert resp.json()["role"] == "normal"
        else:
            # Pydantic strict mode may reject extra fields
            assert resp.status_code == 422

    def test_create_own_key(self, normal_client):
        resp = normal_client.post(
            "/api/v1/users/me/keys",
            json={"name": "my-key"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "key" in data  # full key shown at creation
        assert data["name"] == "my-key"

    def test_list_own_keys(self, normal_client, normal_key):
        resp = normal_client.get("/api/v1/users/me/keys")
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) >= 1
        # Full key should NOT be in list response
        for k in keys:
            assert "key" not in k or k.get("key") is None

    def test_revoke_own_key(self, normal_client, db, normal_user):
        # Create a key to revoke
        create_resp = normal_client.post(
            "/api/v1/users/me/keys",
            json={"name": "to-revoke"},
        )
        key_id = create_resp.json()["id"]
        resp = normal_client.delete(f"/api/v1/users/me/keys/{key_id}")
        assert resp.status_code == 204

    def test_revoke_other_users_key_404(self, normal_client, admin_key):
        resp = normal_client.delete(f"/api/v1/users/me/keys/{admin_key.id}")
        assert resp.status_code == 404


# ── TestAdminKeyManagement ───────────────────────────────────────────────────


class TestAdminKeyManagement:
    """Admin key management for any user: /api/v1/users/{id}/keys*"""

    def test_create_key_for_user(self, admin_client, normal_user):
        resp = admin_client.post(
            f"/api/v1/users/{normal_user.id}/keys",
            json={"name": "admin-created"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "admin-created"
        assert "key" in resp.json()

    def test_list_user_keys(self, admin_client, normal_user, normal_key):
        resp = admin_client.get(f"/api/v1/users/{normal_user.id}/keys")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_revoke_user_key(self, admin_client, db, normal_user):
        # Create a key first
        create_resp = admin_client.post(
            f"/api/v1/users/{normal_user.id}/keys",
            json={"name": "to-revoke"},
        )
        key_id = create_resp.json()["id"]
        resp = admin_client.delete(
            f"/api/v1/users/{normal_user.id}/keys/{key_id}"
        )
        assert resp.status_code == 204

    def test_nonexistent_user_404(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/99999/keys",
            json={"name": "nope"},
        )
        assert resp.status_code == 404


# ── TestAPIKeyExpiration ─────────────────────────────────────────────────────


class TestAPIKeyExpiration:
    """API key expiration validation."""

    def test_past_expires_at_400(self, normal_client):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        resp = normal_client.post(
            "/api/v1/users/me/keys",
            json={"name": "expired", "expires_at": past},
        )
        assert resp.status_code == 400
        assert "future" in resp.json()["detail"].lower()

    def test_future_expires_at_succeeds(self, normal_client):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        resp = normal_client.post(
            "/api/v1/users/me/keys",
            json={"name": "valid-expiry", "expires_at": future},
        )
        assert resp.status_code == 201


# ── TestInputValidation ──────────────────────────────────────────────────────


class TestInputValidation:
    """Input validation edge cases."""

    def test_username_too_long_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "x" * 151, "password": "securepass1"},
        )
        assert resp.status_code == 422

    def test_password_exactly_8_chars_succeeds(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "exact8pw", "password": "12345678"},
        )
        assert resp.status_code == 201

    def test_invalid_role_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/users/",
            json={"username": "badrole2", "password": "securepass1", "role": "invalid"},
        )
        assert resp.status_code == 422
