"""Integration tests for the full gateway message flow.

Covers:
1. Inbound webhook → execution dispatch → delivery outbound
2. Confirmation flow: interrupt → /confirm → resume
3. File handling: attachments → file tags in event_data + correct files schema
"""

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
from services.delivery import OutputDelivery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GATEWAY_TOKEN = "test-gateway-integration-token"


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


def _make_payload(
    workflow_slug: str = "test-workflow",
    trigger_node_id: str = "tg_trigger_1",
    text: str = "Hello world",
    chat_id: str = "12345",
    user_id: str = "99001",
    username: str = "testuser_gw",
    credential_id: str = "cred-abc",
    attachments: list | None = None,
) -> dict:
    """Build a valid GatewayInboundMessage payload."""
    return {
        "route": {
            "workflow_slug": workflow_slug,
            "trigger_node_id": trigger_node_id,
        },
        "credential_id": credential_id,
        "source": {
            "protocol": "telegram",
            "chat_id": chat_id,
            "message_id": "msg-001",
            "from": {"id": user_id, "username": username},
        },
        "text": text,
        "attachments": attachments or [],
        "timestamp": "2026-03-10T12:00:00Z",
    }


# ---------------------------------------------------------------------------
# Test 1 — Full flow: inbound → dispatch → delivery outbound
# ---------------------------------------------------------------------------


class TestFullFlow:
    """Inbound webhook triggers dispatch_event, delivery calls gateway send_message."""

    @patch("api.inbound.dispatch_event")
    def test_inbound_dispatches_and_delivery_sends_via_gateway(
        self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers
    ):
        """POST /inbound → dispatch_event called → OutputDelivery.deliver()
        calls get_gateway_client().send_message() with correct args."""

        # -- Setup: mock dispatch_event to return a realistic execution --
        exec_id = str(uuid.uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_dispatch.return_value = mock_execution

        payload = _make_payload()
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        # -- Verify inbound returned 202 --
        assert resp.status_code == 202
        data = resp.json()
        assert data["execution_id"] == exec_id
        assert data["status"] == "pending"

        # -- Verify dispatch_event called with correct event_data --
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        assert call_args[0][0] == "gateway_inbound"
        event_data = call_args[0][1]
        assert event_data["text"] == "Hello world"
        assert event_data["chat_id"] == "12345"
        assert event_data["credential_id"] == "cred-abc"

        # -- Verify OutputDelivery.deliver() calls gateway send_message --
        # Simulate what the orchestrator does after execution completes:
        # it calls OutputDelivery.deliver(execution, db)
        fake_execution = MagicMock()
        fake_execution.execution_id = exec_id
        fake_execution.trigger_payload = {
            "credential_id": "cred-abc",
            "chat_id": "12345",
        }
        fake_execution.final_output = {"message": "Task completed successfully"}

        with patch("services.delivery.get_gateway_client") as mock_gw:
            mock_gw_instance = MagicMock()
            mock_gw.return_value = mock_gw_instance

            delivery = OutputDelivery()
            delivery.deliver(fake_execution, db)

            mock_gw_instance.send_message.assert_called_once_with(
                "cred-abc", "12345", "Task completed successfully", file_ids=[]
            )

    @patch("api.inbound.dispatch_event")
    def test_delivery_skips_when_no_credential_id(
        self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers
    ):
        """OutputDelivery.deliver() skips send when trigger_payload lacks credential_id."""
        exec_id = str(uuid.uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_dispatch.return_value = mock_execution

        payload = _make_payload()
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)
        assert resp.status_code == 202

        # Simulate execution without credential_id in trigger_payload
        fake_execution = MagicMock()
        fake_execution.trigger_payload = {"chat_id": "12345"}  # no credential_id
        fake_execution.final_output = {"message": "done"}

        with patch("services.delivery.get_gateway_client") as mock_gw:
            delivery = OutputDelivery()
            delivery.deliver(fake_execution, db)

            # send_message should NOT be called
            mock_gw.return_value.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — Confirmation flow: interrupt → /confirm → resume
# ---------------------------------------------------------------------------


class TestConfirmationFlow:
    """PendingTask exists → POST /confirm_{task_id} → execution resumes."""

    @patch("api.inbound.get_gateway_client")
    def test_confirm_resumes_execution(
        self, mock_gw_client, client, db, workflow, trigger_node, user_profile, gateway_headers
    ):
        """/confirm_{task_id} → PendingTask deleted, RQ job enqueued, gateway notified."""
        # -- Setup: interrupted execution + PendingTask --
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            trigger_node_id=trigger_node.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread-confirm",
            status="interrupted",
        )
        db.add(execution)
        db.flush()

        task_id = "aabb1122"
        pending = PendingTask(
            task_id=task_id,
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="cred-abc",
            node_id="agent_node_1",
            prompt="Do you approve this action?",
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

        # -- Verify response --
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["task_id"] == task_id

        # -- Verify PendingTask deleted from DB --
        remaining = db.query(PendingTask).filter(PendingTask.task_id == task_id).first()
        assert remaining is None

        # -- Verify gateway send_message called with confirmation text --
        mock_client_instance.send_message.assert_called_once()
        send_call = mock_client_instance.send_message.call_args
        assert send_call[1]["credential_id"] == "cred-abc" or send_call[0][0] == "cred-abc"
        # Check text includes "confirmed" or "Resuming"
        call_text = send_call[1].get("text") or send_call[0][2]
        assert "confirm" in call_text.lower() or "resum" in call_text.lower()

        # -- Verify RQ queue.enqueue called with resume_workflow_job --
        mock_queue.enqueue.assert_called_once()
        enqueue_args = mock_queue.enqueue.call_args[0]
        assert str(execution.execution_id) in [str(a) for a in enqueue_args]

    @patch("api.inbound.get_gateway_client")
    def test_cancel_stops_execution(
        self, mock_gw_client, client, db, workflow, trigger_node, user_profile, gateway_headers
    ):
        """/cancel_{task_id} → execution cancelled, PendingTask deleted, gateway notified."""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            trigger_node_id=trigger_node.id,
            user_profile_id=user_profile.id,
            thread_id="test-thread-cancel",
            status="interrupted",
        )
        db.add(execution)
        db.flush()

        task_id = "ccdd3344"
        pending = PendingTask(
            task_id=task_id,
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="cred-abc",
            node_id="agent_node_1",
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
        assert resp.json()["status"] == "cancelled"

        # Execution marked as cancelled
        db.refresh(execution)
        assert execution.status == "cancelled"

        # PendingTask deleted
        assert db.query(PendingTask).filter(PendingTask.task_id == task_id).first() is None

        # Gateway notified
        mock_client_instance.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 — File handling: attachments → file tags + files schema
# ---------------------------------------------------------------------------


class TestFileHandling:
    """Attachments in payload produce file tags in event_data and correct files schema."""

    @patch("api.inbound.dispatch_event")
    def test_attachments_produce_file_tags_and_files_schema(
        self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers
    ):
        """Two attachments → text contains [Attached file: ...] tags,
        event_data["files"] has correct schema with url field."""
        exec_id = str(uuid.uuid4())
        mock_execution = MagicMock()
        mock_execution.execution_id = exec_id
        mock_dispatch.return_value = mock_execution

        attachments = [
            {
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
                "download_url": "https://gw.example.com/files/abc",
            },
            {
                "filename": "screenshot.png",
                "mime_type": "image/png",
                "size_bytes": 4096,
                "download_url": "https://gw.example.com/files/xyz",
            },
        ]

        payload = _make_payload(text="Please review these files", attachments=attachments)
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        # -- Verify dispatch_event was called --
        mock_dispatch.assert_called_once()
        event_data = mock_dispatch.call_args[0][1]

        # -- Verify text contains file tags for each attachment --
        assert "[Attached file: report.pdf" in event_data["text"]
        assert "https://gw.example.com/files/abc" in event_data["text"]
        assert "[Attached file: screenshot.png" in event_data["text"]
        assert "https://gw.example.com/files/xyz" in event_data["text"]

        # -- Verify files schema: list of dicts with correct keys --
        files = event_data["files"]
        assert len(files) == 2

        # First file
        assert files[0]["filename"] == "report.pdf"
        assert files[0]["mime_type"] == "application/pdf"
        assert files[0]["size_bytes"] == 1024
        assert files[0]["url"] == "https://gw.example.com/files/abc"
        # Must use "url" not "file_id"
        assert "file_id" not in files[0]

        # Second file
        assert files[1]["filename"] == "screenshot.png"
        assert files[1]["mime_type"] == "image/png"
        assert files[1]["size_bytes"] == 4096
        assert files[1]["url"] == "https://gw.example.com/files/xyz"
        assert "file_id" not in files[1]

    @patch("api.inbound.dispatch_event")
    def test_no_attachments_produces_empty_files(
        self, mock_dispatch, client, db, workflow, trigger_node, gateway_headers
    ):
        """No attachments → event_data["files"] is empty list, text unchanged."""
        mock_execution = MagicMock()
        mock_execution.execution_id = str(uuid.uuid4())
        mock_dispatch.return_value = mock_execution

        payload = _make_payload(text="Just a text message")
        resp = client.post("/api/v1/inbound", json=payload, headers=gateway_headers)

        assert resp.status_code == 202

        event_data = mock_dispatch.call_args[0][1]
        assert event_data["text"] == "Just a text message"
        assert event_data["files"] == []
