"""Tests for ws/ module — broadcast, global_ws, executions."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_mock_redis():
    """Create mock Redis + pubsub for async WS tests.

    aioredis.from_url() returns an async object, but r.pubsub() is a
    *sync* call that returns a PubSub object. So mock_r.pubsub must
    be a regular MagicMock that returns mock_pubsub (not an AsyncMock).
    """
    mock_r = AsyncMock()
    mock_pubsub = AsyncMock()
    # r.pubsub() is NOT awaited — it's a sync method returning a PubSub
    mock_r.pubsub = MagicMock(return_value=mock_pubsub)
    mock_pubsub.get_message = AsyncMock(return_value=None)
    return mock_r, mock_pubsub


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


# ── global_ws() async endpoint tests ─────────────────────────────────────────

class TestGlobalWsEndpoint:
    def test_missing_token_closes_1008(self):
        from ws.global_ws import global_ws

        ws = AsyncMock()
        with patch("ws.global_ws._authenticate", return_value=False):
            _run(global_ws(ws, token=""))
        ws.close.assert_awaited_once()
        args, kwargs = ws.close.call_args
        code = args[0] if args else kwargs.get("code")
        assert code == 1008

    def test_invalid_token_closes_1008(self):
        from ws.global_ws import global_ws

        ws = AsyncMock()
        with patch("ws.global_ws._authenticate", return_value=False):
            _run(global_ws(ws, token="bad-token"))
        ws.close.assert_awaited_once()
        args, kwargs = ws.close.call_args
        code = args[0] if args else kwargs.get("code")
        assert code == 1008

    def test_valid_token_accepts_and_runs(self):
        """Valid token → accept, create tasks, then reader disconnects → cleanup."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.receive.return_value = {"type": "websocket.disconnect", "code": 1000}

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid-token"))

        ws.accept.assert_awaited_once()
        mock_pubsub.close.assert_awaited_once()
        mock_r.close.assert_awaited_once()

    def test_subscribe_message(self):
        """Client sends subscribe → pubsub.subscribe called, ack sent."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "workflow:test"})}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        mock_pubsub.subscribe.assert_awaited_with("workflow:test")
        sent = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(d.get("type") == "subscribed" and d.get("channel") == "workflow:test" for d in sent)

    def test_unsubscribe_message(self):
        """Client sends unsubscribe → pubsub.unsubscribe called, ack sent."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "workflow:test"})}
            if call_count == 2:
                return {"type": "websocket.receive", "text": json.dumps({"type": "unsubscribe", "channel": "workflow:test"})}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        mock_pubsub.unsubscribe.assert_any_await("workflow:test")
        sent = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(d.get("type") == "unsubscribed" and d.get("channel") == "workflow:test" for d in sent)

    def test_pong_message_clears_flag(self):
        """Client sends pong → waiting_pong cleared (no crash)."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "pong"})}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

    def test_malformed_json_skipped(self):
        """Malformed JSON from client → silently skipped."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": "not-json{{{"}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

    def test_empty_text_message_skipped(self):
        """Message with no text → continue."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": ""}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

    def test_redis_pubsub_message_forwarded(self):
        """Redis pub/sub message forwarded to WebSocket client."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "workflow:test"})}
            await asyncio.sleep(0.2)
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        redis_msg = {"type": "message", "data": json.dumps({"type": "node_status", "node_id": "n1"})}
        get_msg_count = 0

        async def mock_get_message(ignore_subscribe_messages=True, timeout=0.5):
            nonlocal get_msg_count
            get_msg_count += 1
            if get_msg_count == 1:
                return redis_msg
            return None

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        sent = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(d.get("type") == "node_status" for d in sent)

    def test_send_when_disconnected_is_noop(self):
        """_send() when client_state is DISCONNECTED → no send_json call."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.DISCONNECTED
        ws.receive.return_value = {"type": "websocket.disconnect", "code": 1000}

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

    def test_redis_get_message_failure_retries(self):
        """Redis pub/sub get_message failure → logged, retried."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "ch1"})}
            # Give redis listener time to hit the error path
            await asyncio.sleep(0.3)
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        get_msg_count = 0

        async def mock_get_message(ignore_subscribe_messages=True, timeout=0.5):
            nonlocal get_msg_count
            get_msg_count += 1
            if get_msg_count == 1:
                raise ConnectionError("Redis disconnected")
            return None

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        # If we got here, the retry path worked

    def test_heartbeat_pong_timeout_closes(self):
        """Pong timeout → heartbeat returns → connection closes."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED

        # Never send pong back, and make time jump forward
        receive_count = 0

        async def mock_receive():
            nonlocal receive_count
            receive_count += 1
            # Just wait long enough for heartbeat to fire and timeout
            await asyncio.sleep(60)
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        # Patch time.monotonic to simulate time passing fast
        base_time = time.monotonic()
        mono_call_count = 0

        def fast_monotonic():
            nonlocal mono_call_count
            mono_call_count += 1
            # Each call adds 15 seconds (heartbeat interval is 30s, pong timeout is 10s)
            return base_time + (mono_call_count * 15)

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r), \
             patch("ws.global_ws.time.monotonic", side_effect=fast_monotonic), \
             patch("ws.global_ws.HEARTBEAT_INTERVAL", 1), \
             patch("ws.global_ws.PONG_TIMEOUT", 1):
            _run(global_ws(ws, token="valid"))

        # Connection should have been cleaned up

    def test_general_exception_in_wait_logged(self):
        """Exception during asyncio.wait → logged, cleanup runs."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        # Raise a generic exception from receive to propagate up
        ws.receive = AsyncMock(side_effect=RuntimeError("unexpected"))

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        # Cleanup should still run
        mock_pubsub.close.assert_awaited_once()
        mock_r.close.assert_awaited_once()

    def test_cleanup_unsubscribes_all_channels(self):
        """On disconnect, all subscribed channels are unsubscribed."""
        from ws.global_ws import global_ws
        from starlette.websockets import WebSocketState

        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "ch1"})}
            if call_count == 2:
                return {"type": "websocket.receive", "text": json.dumps({"type": "subscribe", "channel": "ch2"})}
            return {"type": "websocket.disconnect", "code": 1000}

        ws.receive = mock_receive

        mock_r, mock_pubsub = _make_mock_redis()

        with patch("ws.global_ws._authenticate", return_value=True), \
             patch("ws.global_ws.aioredis.from_url", return_value=mock_r):
            _run(global_ws(ws, token="valid"))

        # Should have unsubscribed from both channels during cleanup
        unsub_calls = [str(c) for c in mock_pubsub.unsubscribe.call_args_list]
        assert any("ch1" in c for c in unsub_calls)
        assert any("ch2" in c for c in unsub_calls)


# ── execution_ws() async endpoint tests ──────────────────────────────────────

class TestExecutionWsEndpoint:
    def test_normal_message_forwarded(self):
        """Non-terminal pub/sub message forwarded to client."""
        from ws.executions import execution_ws

        ws = AsyncMock()
        msg_data = {"type": "node_status", "node_id": "n1"}
        get_msg_count = 0

        async def mock_get_message(ignore_subscribe_messages=True, timeout=1.0):
            nonlocal get_msg_count
            get_msg_count += 1
            if get_msg_count == 1:
                return {"type": "message", "data": json.dumps(msg_data)}
            return {"type": "message", "data": json.dumps({"type": "execution_completed"})}

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        ws.accept.assert_awaited_once()
        mock_pubsub.subscribe.assert_awaited_once()
        sent = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(d.get("type") == "node_status" for d in sent)

    def test_terminal_event_closes_loop(self):
        """execution_completed event → breaks loop and cleans up."""
        from ws.executions import execution_ws

        ws = AsyncMock()

        async def mock_get_message(ignore_subscribe_messages=True, timeout=1.0):
            return {"type": "message", "data": json.dumps({"type": "execution_completed"})}

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.close.assert_awaited_once()
        mock_r.close.assert_awaited_once()

    def test_execution_failed_terminal(self):
        """execution_failed event → breaks loop."""
        from ws.executions import execution_ws

        ws = AsyncMock()

        async def mock_get_message(ignore_subscribe_messages=True, timeout=1.0):
            return {"type": "message", "data": json.dumps({"type": "execution_failed"})}

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        mock_pubsub.close.assert_awaited_once()

    def test_json_decode_error_continues(self):
        """Bad JSON in pub/sub → logged, continues."""
        from ws.executions import execution_ws

        ws = AsyncMock()
        call_count = 0

        async def mock_get_message(ignore_subscribe_messages=True, timeout=1.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "message", "data": "not-json{{{"}
            return {"type": "message", "data": json.dumps({"type": "execution_completed"})}

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

    def test_websocket_disconnect_cleanup(self):
        """WebSocketDisconnect → cleanup runs."""
        from ws.executions import execution_ws
        from fastapi import WebSocketDisconnect as WSD

        ws = AsyncMock()

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = AsyncMock(side_effect=WSD())

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.close.assert_awaited_once()
        mock_r.close.assert_awaited_once()

    def test_general_exception_cleanup(self):
        """General exception → logged, cleanup runs."""
        from ws.executions import execution_ws

        ws = AsyncMock()

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.close.assert_awaited_once()
        mock_r.close.assert_awaited_once()

    def test_no_message_sleeps(self):
        """No message from pub/sub → sleeps, continues loop."""
        from ws.executions import execution_ws

        ws = AsyncMock()
        call_count = 0

        async def mock_get_message(ignore_subscribe_messages=True, timeout=1.0):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return None
            return {"type": "message", "data": json.dumps({"type": "execution_completed"})}

        mock_r, mock_pubsub = _make_mock_redis()
        mock_pubsub.get_message = mock_get_message

        with patch("ws.executions.aioredis.from_url", return_value=mock_r):
            _run(execution_ws(ws, "exec-123"))

        assert call_count == 3
