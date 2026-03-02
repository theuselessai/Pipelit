"""Tests for the activity-based timeout watchdog."""

from __future__ import annotations

import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from services.activity_watchdog import ActivityWatchdog, DEFAULT_INACTIVITY_TIMEOUT, DEFAULT_MAX_WALL_TIME


class TestActivityWatchdogBasics:
    """Core watchdog behavior."""

    def test_defaults(self):
        wd = ActivityWatchdog()
        assert wd._inactivity_timeout == DEFAULT_INACTIVITY_TIMEOUT
        assert wd._max_wall_time == DEFAULT_MAX_WALL_TIME
        assert not wd.active

    def test_custom_values(self):
        wd = ActivityWatchdog(inactivity_timeout=120, max_wall_time=3600)
        assert wd._inactivity_timeout == 120
        assert wd._max_wall_time == 3600

    def test_start_activates(self):
        wd = ActivityWatchdog()
        with patch("services.activity_watchdog._can_use_alarm", return_value=False):
            wd._can_alarm = False
            wd.start()
            assert wd.active
            assert wd._start_time is not None

    def test_stop_deactivates(self):
        wd = ActivityWatchdog()
        wd._can_alarm = False
        wd.start()
        wd.stop()
        assert not wd.active
        assert wd._start_time is None

    def test_ping_noop_before_start(self):
        """Ping before start() should be a no-op."""
        wd = ActivityWatchdog()
        wd._can_alarm = False
        wd.ping()  # should not raise

    def test_ping_noop_after_stop(self):
        """Ping after stop() should be a no-op."""
        wd = ActivityWatchdog()
        wd._can_alarm = False
        wd.start()
        wd.stop()
        wd.ping()  # should not raise


class TestAlarmReset:
    """Test that ping resets the alarm via signal.alarm."""

    def test_start_sets_alarm(self):
        wd = ActivityWatchdog(inactivity_timeout=300, max_wall_time=7200)
        wd._can_alarm = True
        with patch.object(signal, "alarm") as mock_alarm:
            wd.start()
            mock_alarm.assert_called_once_with(300)

    def test_ping_resets_alarm(self):
        wd = ActivityWatchdog(inactivity_timeout=300, max_wall_time=7200)
        wd._can_alarm = True
        wd._start_time = time.monotonic()
        wd._active = True
        with patch.object(signal, "alarm") as mock_alarm:
            wd.ping()
            mock_alarm.assert_called_once_with(300)

    def test_ping_uses_remaining_when_less_than_inactivity(self):
        """When remaining wall time < inactivity_timeout, use remaining."""
        wd = ActivityWatchdog(inactivity_timeout=600, max_wall_time=100)
        wd._can_alarm = True
        wd._active = True
        # Simulate 50s elapsed of 100s max
        wd._start_time = time.monotonic() - 50
        with patch.object(signal, "alarm") as mock_alarm:
            wd.ping()
            # remaining = 100 - 50 = 50, which is < 600
            args = mock_alarm.call_args[0]
            assert args[0] <= 51  # allow 1s tolerance


class TestMaxWallTime:
    """Test max_wall_time ceiling stops extension."""

    def test_ping_does_not_extend_past_max_wall_time(self):
        """After max_wall_time, ping should NOT call signal.alarm."""
        wd = ActivityWatchdog(inactivity_timeout=300, max_wall_time=60)
        wd._can_alarm = True
        wd._active = True
        # Simulate 70s elapsed (past 60s ceiling)
        wd._start_time = time.monotonic() - 70
        with patch.object(signal, "alarm") as mock_alarm:
            wd.ping()
            mock_alarm.assert_not_called()


class TestGracefulFallback:
    """Test fallback when signal.alarm is unavailable."""

    def test_no_alarm_attribute(self):
        """When signal.alarm doesn't exist, watchdog still works (no-op)."""
        wd = ActivityWatchdog()
        wd._can_alarm = False
        wd.start()
        wd.ping()
        wd.stop()
        # No exceptions raised

    def test_alarm_oserror_handled(self):
        """When signal.alarm raises OSError, it's handled gracefully."""
        wd = ActivityWatchdog(inactivity_timeout=300)
        wd._can_alarm = True
        wd._active = True
        wd._start_time = time.monotonic()
        with patch.object(signal, "alarm", side_effect=OSError("not supported")):
            wd.ping()  # should not raise


class TestMiddlewareIntegration:
    """Test that middleware pings the watchdog on tool/model calls."""

    def test_wrap_tool_call_pings_watchdog(self):
        from components._agent_shared import PipelitAgentMiddleware

        mock_watchdog = MagicMock()
        mw = PipelitAgentMiddleware(
            tool_metadata={},
            agent_node_id="agent_1",
            workflow_slug="test-wf",
            watchdog=mock_watchdog,
        )

        mock_request = MagicMock()
        mock_request.tool_call = {"name": "test_tool"}
        mock_request.state = {}
        mock_handler = MagicMock(return_value="result")

        with patch("components._agent_shared._publish_tool_status"):
            result = mw.wrap_tool_call(mock_request, mock_handler)

        assert result == "result"
        # Should ping on entry and after handler returns
        assert mock_watchdog.ping.call_count == 2

    def test_wrap_tool_call_pings_on_exception(self):
        from components._agent_shared import PipelitAgentMiddleware

        mock_watchdog = MagicMock()
        mw = PipelitAgentMiddleware(
            tool_metadata={},
            agent_node_id="agent_1",
            workflow_slug="test-wf",
            watchdog=mock_watchdog,
        )

        mock_request = MagicMock()
        mock_request.tool_call = {"name": "test_tool"}
        mock_request.state = {}
        mock_handler = MagicMock(side_effect=RuntimeError("tool failed"))

        with patch("components._agent_shared._publish_tool_status"):
            with pytest.raises(RuntimeError, match="tool failed"):
                mw.wrap_tool_call(mock_request, mock_handler)

        # Should ping on entry and after exception
        assert mock_watchdog.ping.call_count == 2

    def test_wrap_model_call_pings_watchdog(self):
        from components._agent_shared import PipelitAgentMiddleware

        mock_watchdog = MagicMock()
        mw = PipelitAgentMiddleware(
            tool_metadata={},
            agent_node_id="agent_1",
            workflow_slug="test-wf",
            watchdog=mock_watchdog,
        )

        mock_request = MagicMock()
        mock_request.messages = []
        mock_request.state = {}
        mock_response = MagicMock()
        mock_response.result = []
        mock_handler = MagicMock(return_value=mock_response)

        result = mw.wrap_model_call(mock_request, mock_handler)

        assert result == mock_response
        # Should ping on entry and after handler returns
        assert mock_watchdog.ping.call_count == 2

    def test_no_watchdog_no_pings(self):
        """When watchdog is None, no errors and no pings."""
        from components._agent_shared import PipelitAgentMiddleware

        mw = PipelitAgentMiddleware(
            tool_metadata={},
            agent_node_id="agent_1",
            workflow_slug="test-wf",
            watchdog=None,
        )

        mock_request = MagicMock()
        mock_request.messages = []
        mock_request.state = {}
        mock_response = MagicMock()
        mock_response.result = []
        mock_handler = MagicMock(return_value=mock_response)

        result = mw.wrap_model_call(mock_request, mock_handler)
        assert result == mock_response
