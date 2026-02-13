"""Tests for execution cancel endpoint cleanup (Fix 3.3).

Verifies that cancelling an execution:
- Sets status to cancelled and completed_at
- Cleans up Redis keys
- Publishes a WS event
- Is a no-op for non-cancellable statuses
- Returns 404 for missing executions
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.execution import WorkflowExecution


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


def _make_execution(db, workflow, user_profile, *, status="running"):
    ex = WorkflowExecution(
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        thread_id="test-thread",
        status=status,
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ex


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCancelCleanup:
    """Tests for the cancel execution endpoint cleanup."""

    @patch("ws.broadcast.broadcast")
    @patch("services.execution_recovery._cleanup_redis")
    def test_cancel_sets_status_and_completed_at(self, mock_redis, mock_broadcast, auth_client, db, workflow, user_profile):
        """Cancelling a running execution sets status=cancelled and completed_at."""
        ex = _make_execution(db, workflow, user_profile, status="running")

        resp = auth_client.post(f"/api/v1/executions/{ex.execution_id}/cancel/")
        assert resp.status_code == 200

        db.refresh(ex)
        assert ex.status == "cancelled"
        assert ex.completed_at is not None

    @patch("ws.broadcast.broadcast")
    @patch("services.execution_recovery._cleanup_redis")
    def test_cancel_calls_cleanup_redis(self, mock_redis, mock_broadcast, auth_client, db, workflow, user_profile):
        """Cancelling calls _cleanup_redis with the execution_id."""
        ex = _make_execution(db, workflow, user_profile, status="running")

        auth_client.post(f"/api/v1/executions/{ex.execution_id}/cancel/")

        mock_redis.assert_called_once_with(ex.execution_id)

    @patch("ws.broadcast.broadcast")
    @patch("services.execution_recovery._cleanup_redis")
    def test_cancel_publishes_ws_event(self, mock_redis, mock_broadcast, auth_client, db, workflow, user_profile):
        """Cancelling publishes an execution_cancelled WS event."""
        ex = _make_execution(db, workflow, user_profile, status="running")

        auth_client.post(f"/api/v1/executions/{ex.execution_id}/cancel/")

        mock_broadcast.assert_called_once_with(
            f"workflow:{workflow.slug}",
            "execution_cancelled",
            {"execution_id": ex.execution_id},
        )

    @patch("ws.broadcast.broadcast")
    @patch("services.execution_recovery._cleanup_redis")
    def test_cancel_noop_for_completed(self, mock_redis, mock_broadcast, auth_client, db, workflow, user_profile):
        """Cancelling a completed execution is a no-op."""
        ex = _make_execution(db, workflow, user_profile, status="completed")

        resp = auth_client.post(f"/api/v1/executions/{ex.execution_id}/cancel/")
        assert resp.status_code == 200

        db.refresh(ex)
        assert ex.status == "completed"
        mock_redis.assert_not_called()
        mock_broadcast.assert_not_called()

    @patch("ws.broadcast.broadcast")
    @patch("services.execution_recovery._cleanup_redis")
    def test_cancel_nonexistent_returns_404(self, mock_redis, mock_broadcast, auth_client):
        """Cancelling a nonexistent execution returns 404."""
        resp = auth_client.post("/api/v1/executions/nonexistent-id/cancel/")
        assert resp.status_code == 404
