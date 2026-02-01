"""Tests for TelegramTriggerHandler."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from handlers.telegram import TelegramTriggerHandler
from models.execution import PendingTask, WorkflowExecution
from models.user import UserProfile


def _make_update(user_id=111222333, chat_id=999, message_id=1, text="hello"):
    """Build a minimal Telegram update dict."""
    return {
        "message": {
            "message_id": message_id,
            "from": {
                "id": user_id,
                "first_name": "Test",
                "last_name": "User",
                "username": "testuser",
            },
            "chat": {"id": chat_id},
            "text": text,
        }
    }


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

        assert db.query(UserProfile).filter(UserProfile.telegram_user_id == 777888999).first() is not None


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
            telegram_chat_id=999,
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
            telegram_chat_id=999,
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
            telegram_chat_id=999,
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
