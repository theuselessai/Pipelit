"""Tests for the inbound gateway webhook endpoint (POST /api/v1/inbound)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from database import get_db
from main import app
from models.execution import PendingTask, WorkflowExecution
from models.node import BaseComponentConfig, WorkflowNode
from models.user import UserProfile
from models.workflow import Workflow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GATEWAY_TOKEN = "test-gateway-inbound-token"


@pytest.fixture(autouse=True)
def _set_gateway_token(monkeypatch):
    """Set the gateway inbound token for all tests."""
    monkeypatch.setattr(settings, "GATEWAY_INBOUND_TOKEN", GATEWAY_TOKEN)


@pytest.fixture
def client(db):
    """FastAPI TestClient wired to the test DB."""

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def gateway_headers():
    """Auth headers for gateway inbound requests."""
    return {"Authorization": f"Bearer {GATEWAY_TOKEN}"}


@pytest.fixture
def trigger_node(db, workflow):
    """Create a trigger_telegram node for the test workflow."""
    cc = BaseComponentConfig(
        component_type="trigger_telegram",
        trigger_config={},
        is_active=True,
        priority=10,
    )
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="tg_trigger_1",
        component_type="trigger_telegram",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@pytest.fixture
def chat_trigger_node(db, workflow):
    """Create a trigger_chat node for the test workflow."""
    cc = BaseComponentConfig(
        component_type="trigger_chat",
        trigger_config={},
        is_active=True,
        priority=10,
    )
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="chat_trigger_1",
        component_type="trigger_chat",
        component_config_id=cc.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_payload(
    workflow_slug: str = "test-workflow",
    trigger_node_id: str = "tg_trigger_1",
    text: str = "Hello world",
    chat_id: str = "12345",
    user_id: str = "99001",
    username: str = "testuser_gw",
    credential_id: str = "cred-abc",
    attachments: list | None = None,
    from_user: dict | None = ...,
) -> dict:
    """Build a valid GatewayInboundMessage payload."""
    if from_user is ...:
        from_user = {"id": user_id, "username": username}
    source: dict = {
        "protocol": "telegram",
        "chat_id": chat_id,
        "message_id": "msg-001",
    }
    if from_user is not None:
        source["from"] = from_user
    payload = {
        "route": {
            "workflow_slug": workflow_slug,
            "trigger_node_id": trigger_node_id,
        },
        "credential_id": credential_id,
        "source": source,
        "text": text,
        "attachments": attachments or [],
        "timestamp": "2026-03-10T12:00:00Z",
    }
    return payload


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestInboundEndpoint:
    """POST /api/v1/inbound"""

    @patch("api.inbound.dispatch_event")
    def test_valid_payload_returns_202(self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers):
        """Valid payload -> 202 with execution_id."""
        exec_id = str(uuid.uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_dispatch.return_value = mock_execution

        payload = _make_payload()
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202
        data = resp.json()
        assert data["execution_id"] == exec_id
        assert data["status"] == "pending"

        # Verify dispatch_event was called correctly
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        assert call_args[0][0] == "gateway_inbound"
        event_data = call_args[0][1]
        assert event_data["text"] == "Hello world"
        assert event_data["chat_id"] == "12345"
        assert event_data["credential_id"] == "cred-abc"

    def test_invalid_gateway_token_returns_401(self, client, db, workflow, trigger_node):
        """Invalid gateway token -> 401."""
        payload = _make_payload()
        resp = client.post(
            "/api/v1/inbound",
            json=payload,
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert resp.status_code == 401

    def test_missing_workflow_slug_in_route_returns_422(self, client, db, workflow, trigger_node, gateway_headers):
        """Missing workflow_slug in route -> 422."""
        payload = _make_payload()
        payload["route"] = {"trigger_node_id": "tg_trigger_1"}  # no workflow_slug
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 422

    def test_workflow_not_found_returns_404(self, client, db, workflow, trigger_node, gateway_headers):
        """Non-existent workflow -> 404."""
        payload = _make_payload(workflow_slug="nonexistent-workflow")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_inactive_workflow_returns_422(self, client, db, workflow, trigger_node, gateway_headers):
        """Inactive workflow -> 422."""
        workflow.is_active = False
        db.commit()

        payload = _make_payload()
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 422
        assert "inactive" in resp.json()["detail"].lower()

    def test_trigger_node_not_found_returns_404(self, client, db, workflow, trigger_node, gateway_headers):
        """Non-existent trigger node -> 404."""
        payload = _make_payload(trigger_node_id="nonexistent_node")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 404
        assert "trigger node" in resp.json()["detail"].lower()

    @patch("api.inbound.get_gateway_client")
    def test_confirm_command_handles_pending_task(self, mock_gw_client, client, db, workflow, trigger_node, user_profile, gateway_headers):
        """/confirm_xxx text -> confirmation handled."""
        # Create a pending execution
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            trigger_node_id=trigger_node.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            status="interrupted",
        )
        db.add(execution)
        db.flush()

        task_id = "aabbccdd"
        pending = PendingTask(
            task_id=task_id,
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="cred-abc",
            node_id="some_node",
            prompt="Do you approve?",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(pending)
        db.commit()

        mock_client_instance = MagicMock()
        mock_gw_client.return_value = mock_client_instance

        payload = _make_payload(text=f"/confirm_{task_id}")
        with patch("api.inbound.redis") as mock_redis, \
             patch("api.inbound.Queue") as mock_queue_cls:
            mock_queue = MagicMock()
            mock_queue_cls.return_value = mock_queue
            mock_redis.from_url.return_value = MagicMock()

            resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"

        # Verify send_message was called with confirmation text
        mock_client_instance.send_message.assert_called_once()

    @patch("api.inbound.get_gateway_client")
    def test_cancel_command_handles_pending_task(self, mock_gw_client, client, db, workflow, trigger_node, user_profile, gateway_headers):
        """/cancel_xxx text -> cancellation handled."""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            trigger_node_id=trigger_node.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            status="interrupted",
        )
        db.add(execution)
        db.flush()

        task_id = "ccddaabb"
        pending = PendingTask(
            task_id=task_id,
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="cred-abc",
            node_id="some_node",
            prompt="Do you approve?",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(pending)
        db.commit()

        mock_client_instance = MagicMock()
        mock_gw_client.return_value = mock_client_instance

        payload = _make_payload(text=f"/cancel_{task_id}")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"

        # Verify execution was marked as cancelled
        db.refresh(execution)
        assert execution.status == "cancelled"

        # Verify send_message was called
        mock_client_instance.send_message.assert_called_once()

    @patch("api.inbound.dispatch_event")
    def test_payload_with_attachments_appends_to_text(self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers):
        """Attachments are appended to text as file tags."""
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid.uuid4())
        mock_dispatch.return_value = mock_execution

        attachments = [
            {
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
                "download_url": "https://gw.example.com/files/abc",
            },
            {
                "filename": "photo.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 2048,
                "download_url": "https://gw.example.com/files/def",
            },
        ]

        payload = _make_payload(text="Check these files", attachments=attachments)
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        # Verify text includes attachment tags
        event_data = mock_dispatch.call_args[0][1]
        assert "report.pdf" in event_data["text"]
        assert "https://gw.example.com/files/abc" in event_data["text"]
        assert "photo.jpg" in event_data["text"]
        assert event_data["files"][0]["filename"] == "report.pdf"
        assert event_data["files"][1]["url"] == "https://gw.example.com/files/def"

    @patch("api.inbound.dispatch_event")
    def test_source_from_none_uses_anonymous_profile(self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers):
        """source.from is None -> anonymous profile used."""
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid.uuid4())
        mock_dispatch.return_value = mock_execution

        payload = _make_payload(from_user=None)
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        # Verify dispatch_event was called with an anonymous profile
        call_args = mock_dispatch.call_args
        profile = call_args[0][2]
        assert profile.username == "gateway_anonymous"

    @patch("api.inbound.dispatch_event")
    def test_dispatch_returns_none_gives_500(self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers):
        """dispatch_event returns None -> 500."""
        mock_dispatch.return_value = None

        payload = _make_payload()
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 500
        assert "failed" in resp.json()["detail"].lower()

    @patch("api.inbound.dispatch_event")
    def test_user_profile_created_from_source_from(self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers):
        """New user from source.from -> UserProfile created with external_user_id."""
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid.uuid4())
        mock_dispatch.return_value = mock_execution

        payload = _make_payload(user_id="77788899", username="newuser")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        # Verify UserProfile was created
        profile = db.query(UserProfile).filter(UserProfile.external_user_id == 77788899).first()
        assert profile is not None
        assert profile.username == "newuser"

    @patch("api.inbound.dispatch_event")
    def test_existing_user_profile_reused(self, mock_dispatch, client, db, workflow, trigger_node, user_profile, gateway_headers):
        """Existing user (by external_user_id) -> reused, not created."""
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid.uuid4())
        mock_dispatch.return_value = mock_execution

        # user_profile fixture has external_user_id=111222333
        payload = _make_payload(user_id="111222333", username="testuser")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        # Should not have created a second profile
        count = db.query(UserProfile).filter(UserProfile.external_user_id == 111222333).count()
        assert count == 1

    @patch("api.inbound.get_gateway_client")
    def test_confirm_expired_task(self, mock_gw_client, client, db, workflow, trigger_node, user_profile, gateway_headers):
        """/confirm_xxx on expired task -> still returns 200 with expired status."""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            trigger_node_id=trigger_node.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread",
            status="interrupted",
        )
        db.add(execution)
        db.flush()

        task_id = "expiredaa"
        pending = PendingTask(
            task_id=task_id,
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="cred-abc",
            node_id="some_node",
            prompt="Do you approve?",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # expired
        )
        db.add(pending)
        db.commit()

        mock_client_instance = MagicMock()
        mock_gw_client.return_value = mock_client_instance

        payload = _make_payload(text=f"/confirm_{task_id}")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

    @patch("api.inbound.get_gateway_client")
    def test_confirm_nonexistent_task(self, mock_gw_client, client, db, workflow, trigger_node, gateway_headers):
        """/confirm_xxx where task doesn't exist -> 200 with not_found status."""
        mock_client_instance = MagicMock()
        mock_gw_client.return_value = mock_client_instance

        payload = _make_payload(text="/confirm_notfound")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"
