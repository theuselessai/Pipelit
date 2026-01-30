"""Tests for TelegramTriggerHandler."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.workflows.handlers.telegram import TelegramTriggerHandler
from apps.workflows.models import PendingTask, WorkflowExecution


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


@pytest.mark.django_db
class TestHandleMessage:
    def test_dispatches_and_sends_typing(self, user_profile, telegram_trigger):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with (
            patch("apps.workflows.handlers.django_rq") as mock_rq,
            patch("apps.workflows.handlers.telegram.output_delivery") as mock_delivery,
        ):
            mock_rq.get_queue.return_value.enqueue.return_value = None
            handler.handle_message("123456:ABC-DEF", update)

        mock_delivery.send_typing_action.assert_called_once_with("123456:ABC-DEF", 999)
        assert WorkflowExecution.objects.count() == 1

    def test_sends_fallback_when_no_match(self, user_profile):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with patch("apps.workflows.handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_message("123456:ABC-DEF", update)

        mock_delivery.send_telegram_message.assert_called_once()
        args = mock_delivery.send_telegram_message.call_args
        assert "No workflow configured" in args[0][2]

    def test_ignores_empty_update(self):
        handler = TelegramTriggerHandler()
        # Should not raise
        handler.handle_message("token", {})
        handler.handle_message("token", {"message": {}})

    def test_auto_provisions_user_profile(self, telegram_trigger):
        """A new Telegram user should get a UserProfile auto-created."""
        handler = TelegramTriggerHandler()
        update = _make_update(user_id=777888999)

        with (
            patch("apps.workflows.handlers.django_rq") as mock_rq,
            patch("apps.workflows.handlers.telegram.output_delivery"),
        ):
            mock_rq.get_queue.return_value.enqueue.return_value = None
            # Remove user_id filter from trigger so it matches
            telegram_trigger.config = {}
            telegram_trigger.save()
            handler.handle_message("123456:ABC-DEF", update)

        from apps.users.models import UserProfile
        assert UserProfile.objects.filter(telegram_user_id=777888999).exists()


@pytest.mark.django_db
class TestHandleConfirmation:
    def test_resumes_on_confirm(self, user_profile, workflow):
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            user_profile=user_profile,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        PendingTask.objects.create(
            task_id="aabbccdd",
            execution=execution,
            user_profile=user_profile,
            telegram_chat_id=999,
            node_id="confirm_node",
            prompt="Proceed?",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        handler = TelegramTriggerHandler()
        with patch("django_rq.get_queue") as mock_get_queue:
            mock_queue = mock_get_queue.return_value
            handler.handle_confirmation("123456:ABC-DEF", "aabbccdd", "confirm")

        mock_queue.enqueue.assert_called_once()
        assert not PendingTask.objects.filter(task_id="aabbccdd").exists()

    def test_cancels_execution(self, user_profile, workflow):
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            user_profile=user_profile,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        PendingTask.objects.create(
            task_id="aabbccdd",
            execution=execution,
            user_profile=user_profile,
            telegram_chat_id=999,
            node_id="confirm_node",
            prompt="Proceed?",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        handler = TelegramTriggerHandler()
        with patch("apps.workflows.handlers.telegram.output_delivery"):
            handler.handle_confirmation("123456:ABC-DEF", "aabbccdd", "cancel")

        execution.refresh_from_db()
        assert execution.status == "cancelled"
        assert not PendingTask.objects.filter(task_id="aabbccdd").exists()

    def test_expired_task(self, user_profile, workflow):
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            user_profile=user_profile,
            thread_id="abc123",
            status="interrupted",
            trigger_payload={"chat_id": 999},
        )
        PendingTask.objects.create(
            task_id="expired1",
            execution=execution,
            user_profile=user_profile,
            telegram_chat_id=999,
            node_id="n",
            prompt="Proceed?",
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        handler = TelegramTriggerHandler()
        with patch("apps.workflows.handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_confirmation("123456:ABC-DEF", "expired1", "confirm")

        mock_delivery.send_telegram_message.assert_called_once()
        assert "expired" in mock_delivery.send_telegram_message.call_args[0][2].lower()

    def test_missing_task(self):
        handler = TelegramTriggerHandler()
        # Should not raise
        handler.handle_confirmation("token", "nonexist", "confirm")


@pytest.mark.django_db
class TestHandleCommand:
    def test_start_command(self):
        handler = TelegramTriggerHandler()
        update = _make_update(text="/start")

        with patch("apps.workflows.handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_command("token", "start", update)

        mock_delivery.send_telegram_message.assert_called_once()
        assert "ready" in mock_delivery.send_telegram_message.call_args[0][2].lower()

    def test_pending_command_no_tasks(self, user_profile):
        handler = TelegramTriggerHandler()
        update = _make_update()

        with patch("apps.workflows.handlers.telegram.output_delivery") as mock_delivery:
            handler.handle_command("token", "pending", update)

        mock_delivery.send_telegram_message.assert_called_once()
        assert "No pending" in mock_delivery.send_telegram_message.call_args[0][2]
