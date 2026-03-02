"""Activity-based timeout watchdog for agent nodes.

RQ's SimpleWorker uses signal.alarm(timeout) → SIGALRM to kill jobs.
Calling signal.alarm(N) from within the job resets the countdown.

This watchdog extends the timeout while the agent is actively working
(LLM calls, tool calls) and enforces a hard ceiling (max_wall_time)
to prevent runaway agents.
"""

from __future__ import annotations

import logging
import signal
import time

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_INACTIVITY_TIMEOUT = 600  # 10 minutes — local bwrap tests can take >5min
DEFAULT_MAX_WALL_TIME = 7200  # 2 hours — ceiling for complex multi-step agents


class ActivityWatchdog:
    """Resets RQ's SIGALRM timer on each activity ping.

    Usage::

        watchdog = ActivityWatchdog(inactivity_timeout=600, max_wall_time=7200)
        watchdog.start()
        try:
            # ... agent work ...
            watchdog.ping()  # called by middleware on each LLM/tool call
        finally:
            watchdog.stop()
    """

    def __init__(
        self,
        inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT,
        max_wall_time: int = DEFAULT_MAX_WALL_TIME,
    ):
        self._inactivity_timeout = inactivity_timeout
        self._max_wall_time = max_wall_time
        self._start_time: float | None = None
        self._active = False
        self._can_alarm = _can_use_alarm()

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        """Record start time and set the initial SIGALRM."""
        self._start_time = time.monotonic()
        self._active = True
        self._set_alarm(self._inactivity_timeout)
        logger.info(
            "ActivityWatchdog started: inactivity=%ds, max_wall=%ds",
            self._inactivity_timeout,
            self._max_wall_time,
        )

    def ping(self) -> None:
        """Reset the SIGALRM countdown if still within max_wall_time."""
        if not self._active or self._start_time is None:
            return

        elapsed = time.monotonic() - self._start_time
        remaining = self._max_wall_time - elapsed

        if remaining <= 0:
            # Past the ceiling — let the current alarm fire naturally
            logger.warning(
                "ActivityWatchdog: max_wall_time exceeded (%.0fs elapsed), "
                "not extending timeout",
                elapsed,
            )
            return

        timeout = min(self._inactivity_timeout, remaining)
        self._set_alarm(int(timeout))

    def stop(self) -> None:
        """Deactivate the watchdog. Does NOT cancel any pending alarm
        (RQ manages that)."""
        self._active = False
        self._start_time = None

    def _set_alarm(self, seconds: int) -> None:
        """Set SIGALRM, with graceful fallback if unavailable."""
        if not self._can_alarm:
            return
        try:
            signal.alarm(max(1, seconds))
        except (OSError, ValueError):
            logger.debug("ActivityWatchdog: signal.alarm() failed", exc_info=True)


def _can_use_alarm() -> bool:
    """Check if signal.alarm is available (main thread on Unix)."""
    if not hasattr(signal, "alarm"):
        return False
    try:
        import threading
        return threading.current_thread() is threading.main_thread()
    except Exception:
        return False
