"""Tests for dispatch_event (handlers/__init__.py)."""

from unittest.mock import patch

import pytest

from apps.workflows.handlers import dispatch_event
from apps.workflows.models import WorkflowExecution


@pytest.mark.django_db
class TestDispatchEvent:
    def test_returns_none_when_no_match(self, user_profile):
        result = dispatch_event("telegram_chat", {"text": "hello"}, user_profile)
        assert result is None

    def test_creates_execution_on_match(self, user_profile, telegram_trigger):
        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_rq.get_queue.return_value.enqueue.return_value = None

            result = dispatch_event(
                "telegram_chat",
                {"text": "hello", "chat_id": 123},
                user_profile,
            )

        assert result is not None
        assert isinstance(result, WorkflowExecution)
        assert result.status == "pending"
        assert result.trigger_payload["text"] == "hello"
        assert result.user_profile == user_profile
        assert result.workflow == telegram_trigger.workflow

    def test_enqueues_rq_job(self, user_profile, telegram_trigger):
        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_queue = mock_rq.get_queue.return_value

            dispatch_event(
                "telegram_chat",
                {"text": "hello"},
                user_profile,
            )

        mock_rq.get_queue.assert_called_once_with("workflows")
        mock_queue.enqueue.assert_called_once()
        args = mock_queue.enqueue.call_args[0]
        assert args[0].__name__ == "execute_workflow_job"

    def test_webhook_dispatch(self, user_profile, webhook_trigger):
        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_rq.get_queue.return_value.enqueue.return_value = None

            result = dispatch_event(
                "webhook",
                {"path": "test-hook", "body": {"key": "val"}},
                user_profile,
            )

        assert result is not None
        assert result.trigger_node == webhook_trigger

    def test_manual_dispatch(self, user_profile, manual_trigger):
        with patch("apps.workflows.handlers.django_rq") as mock_rq:
            mock_rq.get_queue.return_value.enqueue.return_value = None

            result = dispatch_event(
                "manual",
                {"text": "run it"},
                user_profile,
            )

        assert result is not None
        assert result.trigger_node == manual_trigger
