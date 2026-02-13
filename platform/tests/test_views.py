"""Tests for webhook and manual execution views (FastAPI endpoints)."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from models.execution import WorkflowExecution


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db
    from auth import get_current_user

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def authed_client(app, user_profile):
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user_profile
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def anon_client(app):
    """Client with no auth override — should get 401/403."""
    return TestClient(app)


class TestManualExecuteView:
    def test_valid_manual_trigger(self, authed_client, db, user_profile, manual_trigger, workflow):
        with patch("handlers.redis") as mock_redis, \
             patch("handlers.Queue") as mock_queue_cls:
            mock_queue_cls.return_value.enqueue.return_value = None
            response = authed_client.post(
                f"/api/v1/workflows/{workflow.slug}/execute/",
                json={"text": "go"},
            )

        assert response.status_code == 200

    def test_workflow_not_found(self, authed_client, db, user_profile):
        response = authed_client.post(
            "/api/v1/workflows/nonexistent/execute/",
            json={},
        )
        assert response.status_code == 404

    def test_unauthenticated(self, anon_client):
        response = anon_client.post(
            "/api/v1/workflows/test/execute/",
            json={},
        )
        assert response.status_code in (401, 403)


class TestExecutionStatusView:
    def test_returns_status(self, authed_client, db, user_profile, workflow):
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="t1",
            status="completed",
            final_output={"message": "done"},
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        response = authed_client.get(f"/api/v1/executions/{execution.execution_id}/status/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["final_output"] == {"message": "done"}

    def test_not_found(self, authed_client, db, user_profile):
        response = authed_client.get("/api/v1/executions/00000000-0000-0000-0000-000000000000/status/")
        assert response.status_code == 404
