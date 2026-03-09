"""Tests for TelegramTriggerHandler."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from handlers.telegram import TelegramTriggerHandler
from models.execution import PendingTask, WorkflowExecution
from models.user import UserProfile


def _make_update(user_id=111222333, chat_id=999, message_id=1, text="hello",
                  document=None, caption=None):
    """Build a minimal Telegram update dict."""
    msg = {
        "message_id": message_id,
        "from": {
            "id": user_id,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
        },
        "chat": {"id": chat_id},
    }
    if text is not None:
        msg["text"] = text
    if caption is not None:
        msg["caption"] = caption
    if document is not None:
        msg["document"] = document
    return {"message": msg}


class TestHandleMessage:
    def test_dispatches_and_sends_typing(self, db, user_profile, telegram_trigger):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with (
            patch("handlers.redis") as mock_redis,
            patch("handlers.Queue") as mock_queue_cls,
            patch("handlers.telegram.output_delivery") as mock_delivery,
        ):
            mock_queue_cls.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update, db)

        mock_delivery.send_typing_action.assert_called_once_with("123456:ABC-DEF", 999)
        assert db.query(WorkflowExecution).count() == 1

    def test_sends_fallback_when_no_match(self, db, user_profile):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with patch("handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_message("123456:ABC-DEF", update, db)

        mock_delivery.send_telegram_message.assert_called_once()
        args = mock_delivery.send_telegram_message.call_args
        assert "No workflow configured" in args[0][2]

    def test_ignores_empty_update(self, db):
        handler = TelegramTriggerHandler()
        handler.handle_message("token", {}, db)
        handler.handle_message("token", {"message": {}}, db)

    def test_auto_provisions_user_profile(self, db, telegram_trigger):
        """A new Telegram user should get a UserProfile auto-created."""
        handler = TelegramTriggerHandler()
        update = _make_update(user_id=777888999)

        # Remove allowed_user_ids filter so any user matches
        from models.credential import TelegramCredential
        tg_cred = db.query(TelegramCredential).first()
        if tg_cred:
            tg_cred.allowed_user_ids = ""
            db.commit()

        with (
            patch("handlers.redis") as mock_redis,
            patch("handlers.Queue") as mock_queue_cls,
            patch("handlers.telegram.output_delivery"),
        ):
            mock_queue_cls.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update, db)

        assert db.query(UserProfile).filter(UserProfile.external_user_id == 777888999).first() is not None

    def test_document_message_includes_files(self, db, user_profile, telegram_trigger):
        """A document message should populate the files array in event_data."""
        handler = TelegramTriggerHandler()
        update = _make_update(
            text=None,
            caption="my notes",
            document={
                "file_id": "BQACAgIAAxk",
                "file_unique_id": "AgADBQAC",
                "file_name": "notes.txt",
                "mime_type": "text/plain",
                "file_size": 1234,
            },
        )

        with (
            patch("handlers.redis"),
            patch("handlers.Queue") as mock_queue_cls,
            patch("handlers.telegram.output_delivery"),
        ):
            mock_queue_cls.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update, db)

        exec_row = db.query(WorkflowExecution).first()
        assert exec_row is not None
        payload = exec_row.trigger_payload
        assert payload["text"].startswith("my notes\n")
        assert "file_id: BQACAgIAAxk" in payload["text"]
        assert "notes.txt" in payload["text"]
        assert len(payload["files"]) == 1
        assert payload["files"][0]["file_id"] == "BQACAgIAAxk"
        assert payload["files"][0]["file_name"] == "notes.txt"
        assert payload["files"][0]["mime_type"] == "text/plain"
        assert payload["files"][0]["file_size"] == 1234

    def test_document_without_caption_generates_text(self, db, user_profile, telegram_trigger):
        """A document without caption should generate text with file_id."""
        handler = TelegramTriggerHandler()
        update = _make_update(
            text=None,
            document={
                "file_id": "BQACAgIAAxk",
                "file_unique_id": "AgADBQAC",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 5678,
            },
        )

        with (
            patch("handlers.redis"),
            patch("handlers.Queue") as mock_queue_cls,
            patch("handlers.telegram.output_delivery"),
        ):
            mock_queue_cls.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update, db)

        exec_row = db.query(WorkflowExecution).first()
        assert exec_row is not None
        text = exec_row.trigger_payload["text"]
        assert "report.pdf" in text
        assert "file_id: BQACAgIAAxk" in text
        assert "application/pdf" in text
        assert len(exec_row.trigger_payload["files"]) == 1

    def test_text_message_has_empty_files(self, db, user_profile, telegram_trigger):
        """A plain text message should have an empty files array."""
        handler = TelegramTriggerHandler()
        update = _make_update(text="just text")

        with (
            patch("handlers.redis"),
            patch("handlers.Queue") as mock_queue_cls,
            patch("handlers.telegram.output_delivery"),
        ):
            mock_queue_cls.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update, db)

        exec_row = db.query(WorkflowExecution).first()
        assert exec_row is not None
        assert exec_row.trigger_payload["files"] == []


class TestHandleConfirmation:
    def test_resumes_on_confirm(self, db, user_profile, workflow):
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        pending = PendingTask(
            task_id="aabbccdd",
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="999",
            node_id="confirm_node",
            prompt="Proceed?",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(pending)
        db.commit()

        handler = TelegramTriggerHandler()
        with patch("redis.from_url") as mock_from_url, \
             patch("rq.Queue") as mock_queue_cls:
            mock_queue = mock_queue_cls.return_value
            handler.handle_confirmation("123456:ABC-DEF", "aabbccdd", "confirm", db)

        mock_queue.enqueue.assert_called_once()
        assert db.query(PendingTask).filter(PendingTask.task_id == "aabbccdd").first() is None

    def test_cancels_execution(self, db, user_profile, workflow):
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        pending = PendingTask(
            task_id="aabbccdd",
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="999",
            node_id="confirm_node",
            prompt="Proceed?",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(pending)
        db.commit()

        handler = TelegramTriggerHandler()
        with patch("handlers.telegram.output_delivery"):
            handler.handle_confirmation("123456:ABC-DEF", "aabbccdd", "cancel", db)

        db.refresh(execution)
        assert execution.status == "cancelled"
        assert db.query(PendingTask).filter(PendingTask.task_id == "aabbccdd").first() is None

    def test_expired_task(self, db, user_profile, workflow):
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        pending = PendingTask(
            task_id="expired1",
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="999",
            node_id="n",
            prompt="Proceed?",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(pending)
        db.commit()

        handler = TelegramTriggerHandler()
        with patch("handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_confirmation("123456:ABC-DEF", "expired1", "confirm", db)

        mock_delivery.send_telegram_message.assert_called_once()
        assert "expired" in mock_delivery.send_telegram_message.call_args[0][2].lower()

    def test_missing_task(self, db):
        handler = TelegramTriggerHandler()
        handler.handle_confirmation("token", "nonexist", "confirm", db)


class TestHandleCommand:
    def test_start_command(self, db):
        handler = TelegramTriggerHandler()
        update = _make_update(text="/start")

        with patch("handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_command("token", "start", update, db)

        mock_delivery.send_telegram_message.assert_called_once()
        assert "ready" in mock_delivery.send_telegram_message.call_args[0][2].lower()

    def test_pending_command_no_tasks(self, db, user_profile):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with patch("handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_command("token", "pending", update, db)

        mock_delivery.send_telegram_message.assert_called_once()
        assert "No pending" in mock_delivery.send_telegram_message.call_args[0][2]


class TestPendingTaskGeneralization:
    """Test PendingTask with generalized chat_id and credential_id columns."""

    def test_create_pending_task_with_chat_id_and_credential_id(self, db, user_profile, workflow):
        """PendingTask should accept chat_id (String) and credential_id (String)."""
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_profile_id=user_profile.id,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": "12345"},
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        pending = PendingTask(
            task_id="test1234",
            execution_id=execution.execution_id,
            user_profile_id=user_profile.id,
            chat_id="12345",
            credential_id="tg_mybot",
            node_id="confirm_node",
            prompt="Proceed?",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)

        # Verify the task was created with the new columns
        assert pending.chat_id == "12345"
        assert pending.credential_id == "tg_mybot"
        assert pending.task_id == "test1234"

        # Verify we can query by chat_id
        found = db.query(PendingTask).filter(PendingTask.chat_id == "12345").first()
        assert found is not None
        assert found.credential_id == "tg_mybot"
