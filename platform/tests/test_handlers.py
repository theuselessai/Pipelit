"""Tests for handlers/ — dispatch_event, manual, webhook, telegram."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── dispatch_event ───────────────────────────────────────────────────────────

class TestDispatchEvent:
    @patch("handlers.Queue")
    @patch("handlers.redis.from_url")
    @patch("handlers.trigger_resolver")
    def test_dispatch_matches(self, mock_resolver, mock_redis, mock_queue_cls):
        from handlers import dispatch_event

        mock_wf = MagicMock(id=1, slug="test-wf")
        mock_trigger_node = MagicMock(id=10)
        mock_resolver.resolve.return_value = (mock_wf, mock_trigger_node)

        mock_db = MagicMock()
        mock_profile = MagicMock(id=5)

        result = dispatch_event("manual", {"text": "hi"}, mock_profile, mock_db)
        assert result is not None
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("handlers.trigger_resolver")
    def test_dispatch_no_match(self, mock_resolver):
        from handlers import dispatch_event

        mock_resolver.resolve.return_value = None
        mock_db = MagicMock()
        mock_profile = MagicMock(id=5)

        result = dispatch_event("manual", {"text": "hi"}, mock_profile, mock_db)
        assert result is None


# ── TriggerResolver ──────────────────────────────────────────────────────────

class TestTriggerResolver:
    def test_resolve_unknown_event_type(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        mock_db = MagicMock()
        result = resolver.resolve("nonexistent_event", {}, mock_db)
        assert result is None

    def test_resolve_manual_event(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        mock_db = MagicMock()

        # No trigger nodes found
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []
        # No default workflow either
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = resolver.resolve("manual", {}, mock_db)
        assert result is None

    def test_matches_manual_always_true(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={})
        assert resolver._matches(config, "manual", {}) is True

    def test_matches_error_always_true(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={})
        assert resolver._matches(config, "error", {}) is True

    def test_match_telegram_allowed_users(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        # No user restriction
        assert resolver._match_telegram({}, {"user_id": 123}) is True
        # Allowed users - match
        assert resolver._match_telegram({"allowed_user_ids": [123]}, {"user_id": 123}) is True
        # Allowed users - no match
        assert resolver._match_telegram({"allowed_user_ids": [456]}, {"user_id": 123}) is False

    def test_match_telegram_pattern(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        assert resolver._match_telegram({"pattern": r"hello"}, {"text": "hello world"}) is True
        assert resolver._match_telegram({"pattern": r"^goodbye"}, {"text": "hello world"}) is False

    def test_match_telegram_command(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        assert resolver._match_telegram({"command": "start"}, {"text": "/start"}) is True
        assert resolver._match_telegram({"command": "help"}, {"text": "/start"}) is False

    def test_matches_workflow_source(self):
        from triggers.resolver import TriggerResolver

        resolver = TriggerResolver()
        config = MagicMock(trigger_config={"source_workflow": "wf-1"})
        assert resolver._matches(config, "workflow", {"source_workflow": "wf-1"}) is True
        assert resolver._matches(config, "workflow", {"source_workflow": "wf-2"}) is False

        config2 = MagicMock(trigger_config={})
        assert resolver._matches(config2, "workflow", {}) is True


# ── TelegramTriggerHandler ───────────────────────────────────────────────────

class TestTelegramHandler:
    @patch("handlers.telegram.dispatch_event")
    @patch("handlers.telegram.output_delivery")
    def test_handle_message(self, mock_delivery, mock_dispatch):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()

        # Mock _is_user_allowed
        cred_query = mock_db.query.return_value.filter.return_value.first
        cred_query.return_value = None  # no credential → allowed

        # Mock _get_or_create_profile
        mock_profile = MagicMock(id=1)
        # Need to handle multiple query calls differently
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,  # _is_user_allowed: no TelegramCredential → allowed
            mock_profile,  # _get_or_create_profile: found existing profile
        ]

        mock_dispatch.return_value = MagicMock()  # execution

        update = {
            "message": {
                "from": {"id": 123, "first_name": "Test"},
                "chat": {"id": 456},
                "message_id": 789,
                "text": "hello",
            }
        }

        handler.handle_message("bot:token", update, mock_db)
        mock_delivery.send_typing_action.assert_called_once()

    @patch("handlers.telegram.dispatch_event", return_value=None)
    @patch("handlers.telegram.output_delivery")
    def test_handle_message_no_workflow(self, mock_delivery, mock_dispatch):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        mock_profile = MagicMock(id=1)
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,  # _is_user_allowed
            mock_profile,  # _get_or_create_profile
        ]

        update = {
            "message": {
                "from": {"id": 123},
                "chat": {"id": 456},
                "message_id": 789,
                "text": "hello",
            }
        }

        handler.handle_message("bot:token", update, mock_db)
        # Should send "no workflow" message
        mock_delivery.send_telegram_message.assert_called_once()
        assert "No workflow" in mock_delivery.send_telegram_message.call_args[0][2]

    def test_handle_message_empty(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        handler.handle_message("bot:token", {}, mock_db)
        # Should return early — no crash

    def test_handle_message_no_user(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        update = {"message": {"chat": {"id": 456}, "text": "hi"}}
        handler.handle_message("bot:token", update, mock_db)
        # Missing user_id → return early

    @patch("handlers.telegram.output_delivery")
    def test_handle_command_start(self, mock_delivery):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        update = {"message": {"chat": {"id": 456}}}
        handler.handle_command("bot:token", "start", update, mock_db)
        mock_delivery.send_telegram_message.assert_called_once()
        assert "ready" in mock_delivery.send_telegram_message.call_args[0][2]

    def test_handle_command_no_chat(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        handler.handle_command("bot:token", "start", {"message": {}}, mock_db)
        # No chat_id → return early

    def test_is_user_allowed_no_cred(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert handler._is_user_allowed("bot:token", 123, mock_db) is True

    def test_is_user_allowed_no_restriction(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        cred = MagicMock()
        cred.allowed_user_ids = ""
        mock_db.query.return_value.filter.return_value.first.return_value = cred
        assert handler._is_user_allowed("bot:token", 123, mock_db) is True

    def test_is_user_allowed_with_restriction(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        cred = MagicMock()
        cred.allowed_user_ids = "123,456"
        mock_db.query.return_value.filter.return_value.first.return_value = cred
        assert handler._is_user_allowed("bot:token", 123, mock_db) is True
        assert handler._is_user_allowed("bot:token", 789, mock_db) is False

    @patch("handlers.telegram.output_delivery")
    def test_handle_pending_tasks_empty(self, mock_delivery):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        handler._show_pending_tasks("bot:token", 456, {"from": {"id": 123}}, mock_db)
        mock_delivery.send_telegram_message.assert_called_once()
        assert "No pending" in mock_delivery.send_telegram_message.call_args[0][2]

    @patch("handlers.telegram.output_delivery")
    def test_show_pending_no_user(self, mock_delivery):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        handler._show_pending_tasks("bot:token", 456, {}, mock_db)
        mock_delivery.send_telegram_message.assert_not_called()

    @patch("rq.Queue")
    @patch("redis.from_url")
    @patch("handlers.telegram.output_delivery")
    def test_handle_confirmation(self, mock_delivery, mock_redis, mock_queue):
        from handlers.telegram import TelegramTriggerHandler
        from datetime import datetime, timezone, timedelta

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()

        pending = MagicMock()
        pending.task_id = "task-1"
        pending.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        pending.telegram_chat_id = 456
        pending.execution = MagicMock(execution_id="exec-1")
        mock_db.query.return_value.filter.return_value.first.return_value = pending

        handler.handle_confirmation("bot:token", "task-1", "approve", mock_db)
        mock_db.delete.assert_called_once_with(pending)

    @patch("handlers.telegram.output_delivery")
    def test_handle_confirmation_expired(self, mock_delivery):
        from handlers.telegram import TelegramTriggerHandler
        from datetime import datetime, timezone, timedelta

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()

        pending = MagicMock()
        pending.task_id = "task-1"
        pending.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        pending.telegram_chat_id = 456
        mock_db.query.return_value.filter.return_value.first.return_value = pending

        handler.handle_confirmation("bot:token", "task-1", "approve", mock_db)
        mock_delivery.send_telegram_message.assert_called_once()
        assert "expired" in mock_delivery.send_telegram_message.call_args[0][2]

    def test_handle_confirmation_not_found(self):
        from handlers.telegram import TelegramTriggerHandler

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        handler.handle_confirmation("bot:token", "task-1", "approve", mock_db)
        # Should return early with no crash

    @patch("handlers.telegram.output_delivery")
    def test_handle_confirmation_cancel(self, mock_delivery):
        from handlers.telegram import TelegramTriggerHandler
        from datetime import datetime, timezone, timedelta

        handler = TelegramTriggerHandler()
        mock_db = MagicMock()

        pending = MagicMock()
        pending.task_id = "task-1"
        pending.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        pending.telegram_chat_id = 456
        pending.execution = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = pending

        handler.handle_confirmation("bot:token", "task-1", "cancel", mock_db)
        assert pending.execution.status == "cancelled"
        mock_delivery.send_telegram_message.assert_called_once()
        assert "cancelled" in mock_delivery.send_telegram_message.call_args[0][2]


