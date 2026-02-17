"""Test that cancelling an execution clears stale LangGraph checkpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.execution import WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode


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
def running_execution(db, workflow, user_profile):
    exe = WorkflowExecution(
        execution_id="exec-cancel-cp",
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        thread_id="t1",
        status="running",
    )
    db.add(exe)
    db.commit()
    db.refresh(exe)
    return exe


@patch("services.orchestrator._clear_stale_checkpoints")
@patch("services.execution_recovery._cleanup_redis")
@patch("ws.broadcast.broadcast")
def test_cancel_calls_clear_stale_checkpoints(
    _mock_broadcast, _mock_redis, mock_clear_cp, auth_client, running_execution, db
):
    resp = auth_client.post(f"/api/v1/executions/{running_execution.execution_id}/cancel/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    mock_clear_cp.assert_called_once_with(running_execution.execution_id, db)


@patch("services.orchestrator._clear_stale_checkpoints")
@patch("services.execution_recovery._cleanup_redis")
@patch("ws.broadcast.broadcast")
def test_cancel_completed_does_not_clear_checkpoints(
    _mock_broadcast, _mock_redis, mock_clear_cp, auth_client, running_execution, db
):
    running_execution.status = "completed"
    db.commit()
    resp = auth_client.post(f"/api/v1/executions/{running_execution.execution_id}/cancel/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    mock_clear_cp.assert_not_called()
