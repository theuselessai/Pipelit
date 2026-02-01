"""Tests for dispatch_event (handlers/__init__.py)."""

from unittest.mock import patch

import pytest

from handlers import dispatch_event
from models.execution import WorkflowExecution


class TestDispatchEvent:
    def test_returns_none_when_no_match(self, db, user_profile):
        result = dispatch_event("telegram_chat", {"text": "hello"}, user_profile, db)
        assert result is None

    def test_creates_execution_on_match(self, db, user_profile, telegram_trigger):
        with patch("handlers.redis") as mock_redis:
            mock_conn = mock_redis.from_url.return_value
            mock_queue_cls = patch("handlers.Queue").start()
            mock_queue = mock_queue_cls.return_value
            mock_queue.enqueue.return_value = None

            result = dispatch_event(
                "telegram_chat",
                {"text": "hello", "chat_id": 123},
                user_profile,
                db,
            )

            patch.stopall()

        assert result is not None
        assert isinstance(result, WorkflowExecution)
        assert result.status == "pending"
        assert result.trigger_payload["text"] == "hello"
        assert result.user_profile_id == user_profile.id

    def test_webhook_dispatch(self, db, user_profile, webhook_trigger):
        with patch("handlers.redis") as mock_redis, \
             patch("handlers.Queue") as mock_queue_cls:
            mock_queue = mock_queue_cls.return_value
            mock_queue.enqueue.return_value = None

            result = dispatch_event(
                "webhook",
                {"path": "test-hook", "body": {"key": "val"}},
                user_profile,
                db,
            )

        assert result is not None
        assert result.trigger_node_id == webhook_trigger.id

    def test_manual_dispatch(self, db, user_profile, manual_trigger):
        with patch("handlers.redis") as mock_redis, \
             patch("handlers.Queue") as mock_queue_cls:
            mock_queue = mock_queue_cls.return_value
            mock_queue.enqueue.return_value = None

            result = dispatch_event(
                "manual",
                {"text": "run it"},
                user_profile,
                db,
            )

        assert result is not None
        assert result.trigger_node_id == manual_trigger.id
