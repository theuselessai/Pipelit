"""Tests for Telegram polling service — routing, offset, backoff, recovery."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from services.telegram_poller import (
    _backoff,
    _route_update,
    poll_telegram_credential,
    recover_telegram_polling,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message_update(update_id=100, text="hello", user_id=111, chat_id=999):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "first_name": "Test", "username": "testuser"},
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def _make_callback_update(update_id=101, data="confirm_abc123"):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb1",
            "from": {"id": 111, "first_name": "Test"},
            "data": data,
        },
    }


# ---------------------------------------------------------------------------
# Backoff Tests
# ---------------------------------------------------------------------------

class TestBackoff:
    def test_zero_errors(self):
        assert _backoff(0) == 0

    def test_first_error(self):
        assert _backoff(1) == 5

    def test_second_error(self):
        assert _backoff(2) == 10

    def test_third_error(self):
        assert _backoff(3) == 20

    def test_cap_at_60(self):
        assert _backoff(10) == 60


# ---------------------------------------------------------------------------
# Route Update Tests
# ---------------------------------------------------------------------------

class TestRouteUpdate:
    def test_regular_message_calls_handle_message(self, db):
        update = _make_message_update(text="hello world")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_message.assert_called_once_with("bot_token", update, db)

    def test_command_calls_handle_message(self, db):
        """Commands like /start go to handle_message, NOT intercepted at system level."""
        update = _make_message_update(text="/start")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_message.assert_called_once_with("bot_token", update, db)

    def test_help_command_calls_handle_message(self, db):
        update = _make_message_update(text="/help")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_message.assert_called_once_with("bot_token", update, db)

    def test_confirm_command_calls_handle_confirmation(self, db):
        update = _make_message_update(text="/confirm_task123")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_confirmation.assert_called_once_with("bot_token", "task123", "confirm", db)
        mock_handler.handle_message.assert_not_called()

    def test_cancel_command_calls_handle_confirmation(self, db):
        update = _make_message_update(text="/cancel_task456")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_confirmation.assert_called_once_with("bot_token", "task456", "cancel", db)
        mock_handler.handle_message.assert_not_called()

    def test_callback_query_confirm(self, db):
        update = _make_callback_update(data="confirm_xyz")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_confirmation.assert_called_once_with("bot_token", "xyz", "confirm", db)

    def test_callback_query_cancel(self, db):
        update = _make_callback_update(data="cancel_xyz")
        with patch("services.telegram_poller.telegram_handler") as mock_handler:
            _route_update("bot_token", update, db)
        mock_handler.handle_confirmation.assert_called_once_with("bot_token", "xyz", "cancel", db)


# ---------------------------------------------------------------------------
# Poll Telegram Credential Tests
# ---------------------------------------------------------------------------

class TestPollTelegramCredential:
    def test_stops_when_no_active_nodes(self, db, telegram_credential, telegram_trigger):
        """Poller should stop when all trigger nodes are inactive."""
        # Set trigger to inactive
        cc = telegram_trigger.component_config
        cc.is_active = False
        db.commit()

        mock_redis = MagicMock()
        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id)

        mock_enqueue.assert_not_called()

    def test_stops_when_credential_not_found(self, db):
        """Poller should stop when credential doesn't exist."""
        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(99999)

        mock_enqueue.assert_not_called()

    def test_successful_poll_reschedules(self, db, telegram_credential, telegram_trigger):
        """Successful poll with updates should process and reschedule."""
        updates = [_make_message_update(update_id=100), _make_message_update(update_id=101, text="second")]
        api_response = {"ok": True, "result": updates}

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # offset = 0

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", return_value=mock_resp),
            patch("services.telegram_poller._route_update") as mock_route,
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id)

        assert mock_route.call_count == 2
        # Should reschedule with error_count=0
        mock_enqueue.assert_called_once_with(telegram_credential.id, 0)

    def test_offset_advances_after_each_update(self, db, telegram_credential, telegram_trigger):
        """Redis offset should advance to update_id + 1 after each update."""
        updates = [
            _make_message_update(update_id=50),
            _make_message_update(update_id=51),
        ]
        api_response = {"ok": True, "result": updates}

        mock_redis = MagicMock()
        mock_redis.get.return_value = b"50"

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", return_value=mock_resp),
            patch("services.telegram_poller._route_update"),
            patch("services.telegram_poller._enqueue_poll"),
        ):
            poll_telegram_credential(telegram_credential.id)

        # Check offset was set for each update
        set_calls = [c for c in mock_redis.set.call_args_list]
        assert len(set_calls) == 2
        # First update: 50 + 1 = 51
        assert set_calls[0] == call(f"tg_poll_offset:{telegram_credential.id}", "51", ex=30 * 24 * 3600)
        # Second update: 51 + 1 = 52
        assert set_calls[1] == call(f"tg_poll_offset:{telegram_credential.id}", "52", ex=30 * 24 * 3600)

    def test_offset_advances_on_processing_failure(self, db, telegram_credential, telegram_trigger):
        """Offset should advance even if processing a single update fails."""
        updates = [_make_message_update(update_id=100)]
        api_response = {"ok": True, "result": updates}

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", return_value=mock_resp),
            patch("services.telegram_poller._route_update", side_effect=RuntimeError("boom")),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id)

        # Offset should still be set
        mock_redis.set.assert_called_once()
        # Should still reschedule with error_count=0 (it's per-update error, not poll error)
        mock_enqueue.assert_called_once_with(telegram_credential.id, 0)

    def test_api_error_triggers_backoff(self, db, telegram_credential, telegram_trigger):
        """HTTP error from Telegram should trigger backoff reschedule."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", side_effect=ConnectionError("timeout")),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id, error_count=2)

        # Should reschedule with incremented error count
        mock_enqueue.assert_called_once_with(telegram_credential.id, 3)

    def test_telegram_api_not_ok_triggers_backoff(self, db, telegram_credential, telegram_trigger):
        """Telegram returning ok=false should trigger backoff."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "description": "Unauthorized"}
        mock_resp.raise_for_status.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", return_value=mock_resp),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id, error_count=0)

        mock_enqueue.assert_called_once_with(telegram_credential.id, 1)

    def test_empty_results_reschedules(self, db, telegram_credential, telegram_trigger):
        """No new updates should still reschedule (long poll returned empty)."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": []}
        mock_resp.raise_for_status.return_value = None

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller.redis.from_url", return_value=mock_redis),
            patch("services.telegram_poller.requests.post", return_value=mock_resp),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            poll_telegram_credential(telegram_credential.id)

        mock_enqueue.assert_called_once_with(telegram_credential.id, 0)


# ---------------------------------------------------------------------------
# Recovery Tests
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_recovers_active_credentials(self, db, telegram_credential, telegram_trigger):
        """Recovery should enqueue polling for active telegram triggers."""
        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            count = recover_telegram_polling()

        assert count == 1
        mock_enqueue.assert_called_once_with(telegram_credential.id, 0)

    def test_skips_inactive_credentials(self, db, telegram_credential, telegram_trigger):
        """Recovery should not enqueue for inactive triggers."""
        cc = telegram_trigger.component_config
        cc.is_active = False
        db.commit()

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            count = recover_telegram_polling()

        assert count == 0
        mock_enqueue.assert_not_called()

    def test_deduplicates_credentials(self, db, workflow, telegram_credential):
        """Multiple trigger nodes with the same credential should only produce one poll job."""
        from models.node import BaseComponentConfig, WorkflowNode

        # Create two telegram trigger nodes pointing to same credential
        for i in range(2):
            cc = BaseComponentConfig(
                component_type="trigger_telegram",
                credential_id=telegram_credential.id,
                trigger_config={},
                is_active=True,
                priority=0,
            )
            db.add(cc)
            db.flush()
            node = WorkflowNode(
                workflow_id=workflow.id,
                node_id=f"tg_trigger_{i}",
                component_type="trigger_telegram",
                component_config_id=cc.id,
            )
            db.add(node)
        db.commit()

        with (
            patch("services.telegram_poller.SessionLocal", return_value=db),
            patch("services.telegram_poller._enqueue_poll") as mock_enqueue,
        ):
            count = recover_telegram_polling()

        assert count == 1
        mock_enqueue.assert_called_once_with(telegram_credential.id, 0)
