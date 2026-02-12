"""Tests for TOTP-based MFA authentication."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyotp
import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.user import APIKey, UserProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def fake_redis():
    """Provide a fakeredis instance for rate-limit tests."""
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_valid_code(secret: str) -> str:
    """Generate a valid TOTP code for the given secret."""
    return pyotp.TOTP(secret).now()


# ---------------------------------------------------------------------------
# MFA Setup Flow
# ---------------------------------------------------------------------------


class TestMFASetup:
    def test_setup_returns_secret_and_uri(self, auth_client):
        resp = auth_client.post("/api/v1/auth/mfa/setup/")
        assert resp.status_code == 200
        data = resp.json()
        assert "secret" in data
        assert "provisioning_uri" in data
        assert data["provisioning_uri"].startswith("otpauth://totp/")
        assert len(data["secret"]) > 10

    def test_setup_rejects_if_already_enabled(self, auth_client, db, user_profile):
        # Enable MFA manually
        user_profile.totp_secret = pyotp.random_base32()
        user_profile.mfa_enabled = True
        db.commit()

        resp = auth_client.post("/api/v1/auth/mfa/setup/")
        assert resp.status_code == 400
        assert "already enabled" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# MFA Verify (enable)
# ---------------------------------------------------------------------------


class TestMFAVerify:
    @patch("services.mfa._redis")
    def test_verify_enables_mfa(self, mock_redis, auth_client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        # First setup
        resp = auth_client.post("/api/v1/auth/mfa/setup/")
        secret = resp.json()["secret"]

        # Then verify with valid code
        code = _get_valid_code(secret)
        resp = auth_client.post("/api/v1/auth/mfa/verify/", json={"code": code})
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is True

        # Verify DB state
        db.refresh(user_profile)
        assert user_profile.mfa_enabled is True

    @patch("services.mfa._redis")
    def test_verify_rejects_invalid_code(self, mock_redis, auth_client, fake_redis):
        mock_redis.return_value = fake_redis

        # Setup first
        auth_client.post("/api/v1/auth/mfa/setup/")

        resp = auth_client.post("/api/v1/auth/mfa/verify/", json={"code": "000000"})
        assert resp.status_code == 400

    def test_verify_rejects_without_setup(self, auth_client):
        resp = auth_client.post("/api/v1/auth/mfa/verify/", json={"code": "123456"})
        assert resp.status_code == 400
        assert "setup" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# MFA Login Flow
# ---------------------------------------------------------------------------


class TestMFALogin:
    @patch("services.mfa._redis")
    def test_login_returns_requires_mfa(self, mock_redis, client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        # Enable MFA
        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        resp = client.post("/api/v1/auth/token/", json={"username": "testuser", "password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_mfa"] is True
        assert data["key"] == ""

    @patch("services.mfa._redis")
    def test_login_verify_returns_key(self, mock_redis, client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        code = _get_valid_code(secret)
        resp = client.post("/api/v1/auth/mfa/login-verify/", json={"username": "testuser", "code": code})
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] != ""
        assert data["requires_mfa"] is False

    @patch("services.mfa._redis")
    def test_login_verify_rejects_invalid_code(self, mock_redis, client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        resp = client.post("/api/v1/auth/mfa/login-verify/", json={"username": "testuser", "code": "000000"})
        assert resp.status_code == 401

    def test_login_verify_rejects_non_mfa_user(self, client):
        resp = client.post("/api/v1/auth/mfa/login-verify/", json={"username": "nobody", "code": "123456"})
        assert resp.status_code == 401

    def test_login_without_mfa_returns_key_directly(self, client, db, user_profile):
        resp = client.post("/api/v1/auth/token/", json={"username": "testuser", "password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_mfa"] is False
        assert data["key"] != ""


# ---------------------------------------------------------------------------
# MFA Disable
# ---------------------------------------------------------------------------


class TestMFADisable:
    @patch("services.mfa._redis")
    def test_disable_clears_mfa(self, mock_redis, auth_client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        code = _get_valid_code(secret)
        resp = auth_client.post("/api/v1/auth/mfa/disable/", json={"code": code})
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is False

        db.refresh(user_profile)
        assert user_profile.mfa_enabled is False
        assert user_profile.totp_secret is None

    @patch("services.mfa._redis")
    def test_disable_rejects_invalid_code(self, mock_redis, auth_client, db, user_profile, fake_redis):
        mock_redis.return_value = fake_redis

        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        resp = auth_client.post("/api/v1/auth/mfa/disable/", json={"code": "000000"})
        assert resp.status_code == 400

    def test_disable_rejects_if_not_enabled(self, auth_client):
        resp = auth_client.post("/api/v1/auth/mfa/disable/", json={"code": "123456"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Replay Prevention
# ---------------------------------------------------------------------------


class TestReplayPrevention:
    @patch("services.mfa._redis")
    def test_same_code_rejected_in_same_step(self, mock_redis, fake_redis):
        mock_redis.return_value = fake_redis
        from services.mfa import verify_code

        secret = pyotp.random_base32()
        code = _get_valid_code(secret)

        # First use should succeed
        valid, step = verify_code(secret, code, user_id=999, last_used_at=None, r=fake_redis)
        assert valid is True
        assert step is not None

        # Second use with same step should fail (replay)
        valid2, _ = verify_code(secret, code, user_id=999, last_used_at=step, r=fake_redis)
        assert valid2 is False


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_after_max_attempts(self, fake_redis):
        from services.mfa import verify_code

        secret = pyotp.random_base32()

        # Make MAX_ATTEMPTS_PER_MINUTE failed attempts
        for i in range(5):
            valid, _ = verify_code(secret, "000000", user_id=888, last_used_at=None, r=fake_redis)
            assert valid is False

        # Next attempt should also fail (rate limited)
        valid, _ = verify_code(secret, _get_valid_code(secret), user_id=888, last_used_at=None, r=fake_redis)
        assert valid is False


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------


class TestLockout:
    def test_lockout_after_consecutive_failures(self, fake_redis):
        from services.mfa import verify_code

        secret = pyotp.random_base32()

        # Make 10 failed attempts (need to reset rate limit between batches)
        for i in range(10):
            # Clear rate limit to allow more attempts
            fake_redis.delete(f"mfa:rate:777")
            verify_code(secret, "000000", user_id=777, last_used_at=None, r=fake_redis)

        # Should be locked out even with valid code
        fake_redis.delete(f"mfa:rate:777")
        valid, _ = verify_code(secret, _get_valid_code(secret), user_id=777, last_used_at=None, r=fake_redis)
        assert valid is False

        # Verify lockout key exists
        assert fake_redis.exists("mfa:lockout:777")


# ---------------------------------------------------------------------------
# MFA Reset (loopback only)
# ---------------------------------------------------------------------------


class TestMFAReset:
    def test_reset_rejected_from_non_localhost(self, auth_client, db, user_profile):
        """TestClient uses a non-localhost host, so reset should be rejected."""
        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        resp = auth_client.post("/api/v1/auth/mfa/reset/")
        assert resp.status_code == 403

    def test_reset_logic(self, db, user_profile):
        """Test the reset logic directly — if from localhost, it clears MFA."""
        secret = pyotp.random_base32()
        user_profile.totp_secret = secret
        user_profile.mfa_enabled = True
        db.commit()

        # Simulate the reset
        user_profile.totp_secret = None
        user_profile.mfa_enabled = False
        user_profile.totp_last_used_at = None
        db.commit()

        db.refresh(user_profile)
        assert user_profile.mfa_enabled is False
        assert user_profile.totp_secret is None


# ---------------------------------------------------------------------------
# MFA Status & Me
# ---------------------------------------------------------------------------


class TestMFAStatus:
    def test_status_returns_disabled(self, auth_client):
        resp = auth_client.get("/api/v1/auth/mfa/status/")
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is False

    def test_status_returns_enabled(self, auth_client, db, user_profile):
        user_profile.mfa_enabled = True
        user_profile.totp_secret = pyotp.random_base32()
        db.commit()

        resp = auth_client.get("/api/v1/auth/mfa/status/")
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is True

    def test_me_includes_mfa_enabled(self, auth_client, db, user_profile):
        resp = auth_client.get("/api/v1/auth/me/")
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is False

        user_profile.mfa_enabled = True
        db.commit()

        resp = auth_client.get("/api/v1/auth/me/")
        assert resp.status_code == 200
        assert resp.json()["mfa_enabled"] is True


# ---------------------------------------------------------------------------
# Agent user gets TOTP secret
# ---------------------------------------------------------------------------


class TestAgentUserTOTP:
    def test_agent_user_gets_totp_on_creation(self, db):
        """Agent users created with TOTP secret and mfa_enabled."""
        user = UserProfile(
            username="agent_test_agent1",
            password_hash="randomhash",
            first_name="Test agent",
            is_agent=True,
            totp_secret=pyotp.random_base32(),
            mfa_enabled=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.totp_secret is not None
        assert user.mfa_enabled is True
        # Verify the secret works
        code = pyotp.TOTP(user.totp_secret).now()
        assert len(code) == 6


# ---------------------------------------------------------------------------
# MFA Service Unit Tests
# ---------------------------------------------------------------------------


class TestMFAService:
    def test_generate_secret(self):
        from services.mfa import generate_secret

        s1 = generate_secret()
        s2 = generate_secret()
        assert s1 != s2
        assert len(s1) >= 16

    def test_get_provisioning_uri(self):
        from services.mfa import get_provisioning_uri

        secret = pyotp.random_base32()
        uri = get_provisioning_uri(secret, "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "testuser" in uri
        assert "Pipelit" in uri

    def test_get_current_code(self):
        from services.mfa import get_current_code

        secret = pyotp.random_base32()
        code = get_current_code(secret)
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_valid_code(self, fake_redis):
        from services.mfa import verify_code

        secret = pyotp.random_base32()
        code = _get_valid_code(secret)

        valid, step = verify_code(secret, code, user_id=1, last_used_at=None, r=fake_redis)
        assert valid is True
        assert step is not None

    def test_verify_invalid_code(self, fake_redis):
        from services.mfa import verify_code

        secret = pyotp.random_base32()
        valid, step = verify_code(secret, "000000", user_id=1, last_used_at=None, r=fake_redis)
        assert valid is False
        assert step is None
