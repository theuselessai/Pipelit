"""Tests for ws/ module — broadcast, global_ws, executions."""

from __future__ import annotations

import json
import time
from datetime import datetime, date
from unittest.mock import MagicMock, patch

import pytest


# ── broadcast.py ──────────────────────────────────────────────────────────────

class TestBroadcastJsonDefault:
    def test_datetime_serialization(self):
        from ws.broadcast import _json_default
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert _json_default(dt) == "2024-01-15T10:30:00"

    def test_date_serialization(self):
        from ws.broadcast import _json_default
        d = date(2024, 6, 15)
        assert _json_default(d) == "2024-06-15"

    def test_unsupported_type(self):
        from ws.broadcast import _json_default
        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_default(set())


class TestBroadcast:
    @patch("ws.broadcast.redis_lib.from_url")
    def test_broadcast_with_data(self, mock_from_url):
        from ws.broadcast import broadcast

        mock_r = MagicMock()
        mock_from_url.return_value = mock_r

        broadcast("workflow:my-wf", "node_updated", {"node_id": "n1"})

        mock_r.publish.assert_called_once()
        channel, payload_str = mock_r.publish.call_args[0]
        assert channel == "workflow:my-wf"
        payload = json.loads(payload_str)
        assert payload["type"] == "node_updated"
        assert payload["channel"] == "workflow:my-wf"
        assert payload["data"]["node_id"] == "n1"
        assert "timestamp" in payload
        mock_r.close.assert_called_once()

    @patch("ws.broadcast.redis_lib.from_url")
    def test_broadcast_without_data(self, mock_from_url):
        from ws.broadcast import broadcast

        mock_r = MagicMock()
        mock_from_url.return_value = mock_r

        broadcast("execution:e1", "execution_started")

        payload = json.loads(mock_r.publish.call_args[0][1])
        assert "data" not in payload

    @patch("ws.broadcast.redis_lib.from_url")
    def test_broadcast_with_datetime_data(self, mock_from_url):
        from ws.broadcast import broadcast

        mock_r = MagicMock()
        mock_from_url.return_value = mock_r

        broadcast("ch", "evt", {"started_at": datetime(2024, 1, 1)})

        payload = json.loads(mock_r.publish.call_args[0][1])
        assert payload["data"]["started_at"] == "2024-01-01T00:00:00"


# ── global_ws.py ──────────────────────────────────────────────────────────────

class TestGlobalWsAuthenticate:
    def test_valid_token(self):
        from ws.global_ws import _authenticate
        mock_db = MagicMock()
        mock_key = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_key

        with patch("ws.global_ws.SessionLocal", return_value=mock_db):
            assert _authenticate("valid-token") is True
        mock_db.close.assert_called_once()

    def test_invalid_token(self):
        from ws.global_ws import _authenticate
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("ws.global_ws.SessionLocal", return_value=mock_db):
            assert _authenticate("bad-token") is False
        mock_db.close.assert_called_once()
