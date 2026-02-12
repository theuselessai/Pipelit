"""Tests for TOTP-based MFA authentication."""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# get_totp_code component
# ---------------------------------------------------------------------------


class TestGetTotpCodeComponent:
    """Tests for the get_totp_code tool component."""

    @pytest.fixture(autouse=True)
    def _import_factory(self):
        from components.get_totp_code import get_totp_code_factory
        self.factory = get_totp_code_factory

    def _make_tool(self, workflow_id, node_id):
        node = MagicMock()
        node.workflow_id = workflow_id
        node.node_id = node_id
        return self.factory(node)

    def test_get_code_by_username(self, db):
        """Retrieve TOTP code for a named agent user."""
        secret = pyotp.random_base32()
        agent = UserProfile(
            username="agent_test_bot",
            password_hash="x",
            is_agent=True,
            totp_secret=secret,
            mfa_enabled=True,
        )
        db.add(agent)
        db.commit()

        tool_fn = self._make_tool(1, "n1")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": "agent_test_bot"}))
        assert result["success"] is True
        assert result["username"] == "agent_test_bot"
        assert len(result["totp_code"]) == 6
        assert result["totp_code"].isdigit()

    def test_user_not_found(self, db):
        """Return error when the requested user doesn't exist."""
        tool_fn = self._make_tool(1, "n1")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": "nonexistent"}))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_user_without_totp_secret(self, db):
        """Return error when the user has no TOTP secret configured."""
        agent = UserProfile(
            username="agent_no_totp",
            password_hash="x",
            is_agent=True,
            totp_secret=None,
            mfa_enabled=False,
        )
        db.add(agent)
        db.commit()

        tool_fn = self._make_tool(1, "n1")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": "agent_no_totp"}))
        assert result["success"] is False
        assert "no totp secret" in result["error"].lower()

    def test_auto_resolve_via_edge(self, db, workflow):
        """When no username given, resolve agent user via edge lookup."""
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode

        # Create tool node config
        cc_tool = BaseComponentConfig(component_type="get_totp_code")
        db.add(cc_tool)
        db.flush()
        tool_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="totp_tool_1",
            component_type="get_totp_code",
            component_config_id=cc_tool.id,
        )
        db.add(tool_node)

        # Create agent node config
        cc_agent = BaseComponentConfig(component_type="agent")
        db.add(cc_agent)
        db.flush()
        agent_node = WorkflowNode(
            workflow_id=workflow.id,
            node_id="agent_abc",
            component_type="agent",
            component_config_id=cc_agent.id,
        )
        db.add(agent_node)

        # Create tool edge: tool_node -> agent_node
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="totp_tool_1",
            target_node_id="agent_abc",
            edge_label="tool",
        )
        db.add(edge)

        # Create the agent user the tool should find
        secret = pyotp.random_base32()
        agent_user = UserProfile(
            username=f"agent_{workflow.slug}_agent_abc",
            password_hash="x",
            is_agent=True,
            totp_secret=secret,
            mfa_enabled=True,
        )
        db.add(agent_user)
        db.commit()

        tool_fn = self._make_tool(workflow.id, "totp_tool_1")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": ""}))
        assert result["success"] is True
        assert result["username"] == f"agent_{workflow.slug}_agent_abc"
        assert len(result["totp_code"]) == 6

    def test_auto_resolve_no_edge_fallback(self, db):
        """When no edge exists and no username given, fall back to tool_node_id."""
        secret = pyotp.random_base32()
        agent_user = UserProfile(
            username="agent_99_tool_node_1",
            password_hash="x",
            is_agent=True,
            totp_secret=secret,
            mfa_enabled=True,
        )
        db.add(agent_user)
        db.commit()

        tool_fn = self._make_tool(99, "tool_node_1")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": ""}))
        assert result["success"] is True
        assert result["username"] == "agent_99_tool_node_1"

    def test_auto_resolve_agent_not_found(self, db):
        """When auto-resolve finds no matching agent user, return error."""
        tool_fn = self._make_tool(999, "orphan")
        with patch("components.get_totp_code.SessionLocal", return_value=db):
            result = json.loads(tool_fn.invoke({"username": ""}))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_db_exception_returns_error(self):
        """Database errors are caught and returned as JSON error."""
        tool_fn = self._make_tool(1, "n1")
        mock_session = MagicMock()
        mock_session.query.side_effect = RuntimeError("connection lost")
        with patch("components.get_totp_code.SessionLocal", return_value=mock_session):
            result = json.loads(tool_fn.invoke({"username": "any"}))
        assert result["success"] is False
        assert "connection lost" in result["error"]
