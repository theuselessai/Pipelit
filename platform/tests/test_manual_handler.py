"""Tests for handlers/manual.py — manual execution and status endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from models.execution import WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode
from models.workflow import Workflow


class TestManualExecuteView:
    @patch("rq.Queue")
    @patch("redis.from_url")
    def test_execute_with_trigger_node_id(self, mock_redis, mock_queue, db, workflow, manual_trigger):
        from handlers.manual import manual_execute_view, ManualExecuteIn

        payload = ManualExecuteIn(text="hello", trigger_node_id="manual_trigger_1")
        result = manual_execute_view(workflow.slug, payload, db, MagicMock(id=1))
        assert "execution_id" in result
        assert result["status"] == "pending"

    @patch("handlers.manual.dispatch_event")
    def test_execute_fallback_dispatch(self, mock_dispatch, db, workflow, manual_trigger):
        from handlers.manual import manual_execute_view, ManualExecuteIn

        mock_execution = MagicMock()
        mock_execution.execution_id = uuid.uuid4()
        mock_execution.status = "pending"
        mock_dispatch.return_value = mock_execution

        payload = ManualExecuteIn(text="hello")
        result = manual_execute_view(workflow.slug, payload, db, MagicMock(id=1))
        assert "execution_id" in result

    def test_execute_workflow_not_found(self, db):
        from fastapi import HTTPException
        from handlers.manual import manual_execute_view, ManualExecuteIn

        payload = ManualExecuteIn(text="hello")
        with pytest.raises(HTTPException) as exc_info:
            manual_execute_view("nonexistent-slug", payload, db, MagicMock(id=1))
        assert exc_info.value.status_code == 404

    @patch("rq.Queue")
    @patch("redis.from_url")
    def test_execute_trigger_node_not_found(self, mock_redis, mock_queue, db, workflow):
        from fastapi import HTTPException
        from handlers.manual import manual_execute_view, ManualExecuteIn

        payload = ManualExecuteIn(text="hello", trigger_node_id="nonexistent_trigger")
        with pytest.raises(HTTPException) as exc_info:
            manual_execute_view(workflow.slug, payload, db, MagicMock(id=1))
        assert exc_info.value.status_code == 404

    @patch("handlers.manual.dispatch_event", return_value=None)
    def test_execute_no_trigger_configured(self, mock_dispatch, db, workflow):
        from fastapi import HTTPException
        from handlers.manual import manual_execute_view, ManualExecuteIn

        payload = ManualExecuteIn(text="hello")
        with pytest.raises(HTTPException) as exc_info:
            manual_execute_view(workflow.slug, payload, db, MagicMock(id=1))
        assert exc_info.value.status_code == 404
        assert "No trigger" in exc_info.value.detail


class TestExecutionStatusView:
    def test_status_found(self, db, workflow, user_profile):
        from handlers.manual import execution_status_view

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            trigger_payload={},
            status="running",
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        result = execution_status_view(str(execution.execution_id), db, user_profile)
        assert result["execution_id"] == str(execution.execution_id)
        assert result["status"] == "running"
        assert result["workflow"] == workflow.slug

    def test_status_not_found(self, db, user_profile):
        from fastapi import HTTPException
        from handlers.manual import execution_status_view

        with pytest.raises(HTTPException) as exc_info:
            execution_status_view("nonexistent-id", db, user_profile)
        assert exc_info.value.status_code == 404

    def test_status_completed(self, db, workflow, user_profile):
        from handlers.manual import execution_status_view

        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            trigger_payload={},
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            final_output={"output": "done"},
            error_message="",
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        result = execution_status_view(str(execution.execution_id), db, user_profile)
        assert result["status"] == "completed"
        assert result["final_output"] == {"output": "done"}
        assert result["started_at"] is not None
        assert result["completed_at"] is not None
