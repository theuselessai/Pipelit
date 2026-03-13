"""Tests for chat endpoints (send, history, delete)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure platform/ is importable
_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.node import BaseComponentConfig, WorkflowNode
from models.workflow import Workflow


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
def chat_workflow(db, user_profile):
    """Workflow with a trigger_chat node."""
    wf = Workflow(
        name="Chat Bot",
        slug="chat-bot",
        owner_id=user_profile.id,
        is_active=True,
    )
    db.add(wf)
    db.flush()

    cc = BaseComponentConfig(
        component_type="trigger_chat",
        trigger_config={},
        is_active=True,
        priority=0,
    )
    db.add(cc)
    db.flush()

    node = WorkflowNode(
        workflow_id=wf.id,
        node_id="chat_trigger_1",
        component_type="trigger_chat",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(wf)
    db.refresh(node)
    return wf


@pytest.fixture
def workflow_no_chat(db, user_profile):
    """Workflow without any chat trigger node."""
    wf = Workflow(
        name="No Chat",
        slug="no-chat",
        owner_id=user_profile.id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


# ── POST /{slug}/chat/ ───────────────────────────────────────────────────────


class TestSendChatMessage:
    """Tests for the send_chat_message endpoint."""

    @patch("api.executions.execute_workflow_job")
    @patch("api.executions.Queue")
    @patch("api.executions.redis")
    def test_happy_path(
        self, mock_redis, mock_queue_cls, mock_job, auth_client, chat_workflow, user_profile, db
    ):
        mock_conn = MagicMock()
        mock_redis.from_url.return_value = mock_conn
        mock_queue = MagicMock()
        mock_queue_cls.return_value = mock_queue

        resp = auth_client.post(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/",
            json={"text": "Hello!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["execution_id"]
        assert data["response"] == ""

        # Verify RQ queue was used
        mock_queue.enqueue.assert_called_once()

    @patch("api.executions.execute_workflow_job")
    @patch("api.executions.Queue")
    @patch("api.executions.redis")
    def test_thread_id_format(
        self, mock_redis, mock_queue_cls, mock_job, auth_client, chat_workflow, user_profile, db
    ):
        """thread_id must be '{profile.id}:{workflow.id}' — not a random UUID."""
        mock_conn = MagicMock()
        mock_redis.from_url.return_value = mock_conn
        mock_queue_cls.return_value = MagicMock()

        resp = auth_client.post(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/",
            json={"text": "Check thread ID"},
        )
        assert resp.status_code == 200

        from models.execution import WorkflowExecution

        execution = db.query(WorkflowExecution).first()
        expected_thread_id = f"{user_profile.id}:{chat_workflow.id}"
        assert execution.thread_id == expected_thread_id

    def test_no_chat_trigger_returns_404(self, auth_client, workflow_no_chat):
        resp = auth_client.post(
            f"/api/v1/workflows/{workflow_no_chat.slug}/chat/",
            json={"text": "Hello"},
        )
        assert resp.status_code == 404
        assert "chat trigger" in resp.json()["detail"].lower()

    def test_workflow_not_found_returns_404(self, auth_client):
        resp = auth_client.post(
            "/api/v1/workflows/nonexistent-slug/chat/",
            json={"text": "Hello"},
        )
        assert resp.status_code == 404

    def test_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/v1/workflows/any-slug/chat/",
            json={"text": "Hello"},
        )
        assert resp.status_code == 401

    @patch("api.executions.redis")
    def test_enqueue_failure_rolls_back_execution(
        self, mock_redis, auth_client, chat_workflow, db
    ):
        """If RQ enqueue fails, the execution record is deleted and 503 returned."""
        mock_redis.from_url.side_effect = ConnectionError("Redis down")

        resp = auth_client.post(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/",
            json={"text": "Hello"},
        )
        assert resp.status_code == 503
        assert "enqueue" in resp.json()["detail"].lower()

        # Execution record should have been rolled back
        from models.execution import WorkflowExecution

        assert db.query(WorkflowExecution).count() == 0


# ── GET /{slug}/chat/history ──────────────────────────────────────────────────


class TestGetChatHistory:
    """Tests for the get_chat_history endpoint."""

    @patch("api.executions._get_checkpointer")
    def test_empty_when_no_checkpoint(self, mock_get_cp, auth_client, chat_workflow, user_profile):
        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = None
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(f"/api/v1/workflows/{chat_workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []
        expected_thread_id = f"{user_profile.id}:{chat_workflow.id}"
        assert data["thread_id"] == expected_thread_id
        assert data["has_more"] is False

    @patch("api.executions._get_checkpointer")
    def test_returns_messages_from_checkpoint(self, mock_get_cp, auth_client, chat_workflow):
        human_msg = MagicMock()
        human_msg.type = "human"
        human_msg.content = "Hi there"
        human_msg.id = "msg1"
        human_msg.additional_kwargs = {}
        human_msg.response_metadata = {}

        ai_msg = MagicMock()
        ai_msg.type = "ai"
        ai_msg.content = "Hello! How can I help?"
        ai_msg.id = "msg2"
        ai_msg.additional_kwargs = {"timestamp": "2025-01-01T00:00:00Z"}
        ai_msg.response_metadata = {}

        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = {
            "channel_values": {
                "messages": [human_msg, ai_msg],
            }
        }

        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = checkpoint_tuple
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(f"/api/v1/workflows/{chat_workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["text"] == "Hi there"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["text"] == "Hello! How can I help?"

    @patch("api.executions._get_checkpointer")
    def test_limit_param(self, mock_get_cp, auth_client, chat_workflow):
        """limit=1 returns only the last message."""
        msgs = []
        for i in range(5):
            m = MagicMock()
            m.type = "human"
            m.content = f"Message {i}"
            m.id = f"msg{i}"
            m.additional_kwargs = {}
            m.response_metadata = {}
            msgs.append(m)

        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = {"channel_values": {"messages": msgs}}

        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = checkpoint_tuple
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/history?limit=2"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["has_more"] is True
        # Should be last 2 messages
        assert data["messages"][0]["text"] == "Message 3"
        assert data["messages"][1]["text"] == "Message 4"

    @patch("api.executions._get_checkpointer")
    def test_before_datetime_filter(self, mock_get_cp, auth_client, chat_workflow):
        old_msg = MagicMock()
        old_msg.type = "human"
        old_msg.content = "Old message"
        old_msg.id = "old"
        old_msg.additional_kwargs = {"timestamp": "2024-01-01T00:00:00Z"}
        old_msg.response_metadata = {}

        new_msg = MagicMock()
        new_msg.type = "human"
        new_msg.content = "New message"
        new_msg.id = "new"
        new_msg.additional_kwargs = {"timestamp": "2025-06-01T00:00:00Z"}
        new_msg.response_metadata = {}

        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = {"channel_values": {"messages": [old_msg, new_msg]}}

        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = checkpoint_tuple
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/history"
            "?before=2025-01-01T00:00:00Z"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "Old message"

    def test_workflow_not_found_returns_404(self, auth_client):
        resp = auth_client.get("/api/v1/workflows/nonexistent-slug/chat/history")
        assert resp.status_code == 404

    @patch("api.executions._get_checkpointer")
    def test_invalid_before_param_returns_400(self, mock_get_cp, auth_client, chat_workflow):
        """Malformed 'before' datetime returns 400, not silent ignore."""
        resp = auth_client.get(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/history?before=not-a-date"
        )
        assert resp.status_code == 400
        assert "before" in resp.json()["detail"].lower()

    @patch("api.executions._get_checkpointer")
    def test_checkpoint_exception_returns_empty(self, mock_get_cp, auth_client, chat_workflow):
        mock_cp = MagicMock()
        mock_cp.get_tuple.side_effect = RuntimeError("DB error")
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(f"/api/v1/workflows/{chat_workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []

    @patch("api.executions._get_checkpointer")
    def test_skips_system_prompt_fallback(self, mock_get_cp, auth_client, chat_workflow):
        sys_msg = MagicMock()
        sys_msg.type = "human"
        sys_msg.content = "System fallback"
        sys_msg.id = "system_prompt_fallback"
        sys_msg.additional_kwargs = {}
        sys_msg.response_metadata = {}

        user_msg = MagicMock()
        user_msg.type = "human"
        user_msg.content = "Real message"
        user_msg.id = "real1"
        user_msg.additional_kwargs = {}
        user_msg.response_metadata = {}

        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = {"channel_values": {"messages": [sys_msg, user_msg]}}

        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = checkpoint_tuple
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(f"/api/v1/workflows/{chat_workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "Real message"

    @patch("api.executions._get_checkpointer")
    def test_content_list_blocks(self, mock_get_cp, auth_client, chat_workflow):
        """AI messages with list content blocks are concatenated."""
        ai_msg = MagicMock()
        ai_msg.type = "ai"
        ai_msg.content = [{"text": "Part 1"}, {"text": " Part 2"}]
        ai_msg.id = "ai1"
        ai_msg.additional_kwargs = {}
        ai_msg.response_metadata = {}

        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = {"channel_values": {"messages": [ai_msg]}}

        mock_cp = MagicMock()
        mock_cp.get_tuple.return_value = checkpoint_tuple
        mock_get_cp.return_value = mock_cp

        resp = auth_client.get(f"/api/v1/workflows/{chat_workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "Part 1 Part 2"


# ── DELETE /{slug}/chat/history ───────────────────────────────────────────────


class TestDeleteChatHistory:
    """Tests for the delete_chat_history endpoint."""

    @patch("api.executions._get_checkpointer")
    def test_deletes_checkpoint_data(self, mock_get_cp, auth_client, chat_workflow, user_profile):
        mock_conn = MagicMock()
        mock_cp = MagicMock()
        mock_cp.conn = mock_conn
        mock_get_cp.return_value = mock_cp

        resp = auth_client.delete(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/history"
        )
        assert resp.status_code == 204

        expected_thread_id = f"{user_profile.id}:{chat_workflow.id}"
        # Verify both writes and checkpoints tables are cleaned
        assert mock_conn.execute.call_count == 2
        calls = mock_conn.execute.call_args_list
        assert calls[0][0] == ("DELETE FROM writes WHERE thread_id = ?", (expected_thread_id,))
        assert calls[1][0] == ("DELETE FROM checkpoints WHERE thread_id = ?", (expected_thread_id,))
        mock_conn.commit.assert_called_once()

    @patch("api.executions._get_checkpointer")
    def test_delete_failure_returns_500(self, mock_get_cp, auth_client, chat_workflow):
        """If checkpoint deletion fails, returns 500 with rollback."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("DB locked")
        mock_cp = MagicMock()
        mock_cp.conn = mock_conn
        mock_get_cp.return_value = mock_cp

        resp = auth_client.delete(
            f"/api/v1/workflows/{chat_workflow.slug}/chat/history"
        )
        assert resp.status_code == 500
        assert "delete" in resp.json()["detail"].lower()
        mock_conn.rollback.assert_called_once()

    def test_workflow_not_found_returns_404(self, auth_client):
        resp = auth_client.delete("/api/v1/workflows/nonexistent-slug/chat/history")
        assert resp.status_code == 404
