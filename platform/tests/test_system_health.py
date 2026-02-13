"""Tests for the system_health component — check_system_health tool."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_node():
    config = SimpleNamespace(
        component_type="system_health",
        extra_config={},
        system_prompt="",
    )
    return SimpleNamespace(
        node_id="system_health_1",
        workflow_id=1,
        component_type="system_health",
        component_config=config,
    )


def _get_tool():
    from components.system_health import system_health_factory
    tools = system_health_factory(_make_node())
    assert isinstance(tools, list)
    assert len(tools) == 1
    return tools[0]


def _now():
    return datetime.now(timezone.utc)


def _make_redis_mock(ping_ok=True):
    """Create a mock Redis connection with sensible defaults."""
    mock_conn = MagicMock()
    if ping_ok:
        mock_conn.ping.return_value = True
        mock_conn.info.side_effect = lambda section="all": {
            "memory": {"used_memory_human": "5M", "used_memory_peak_human": "10M"},
            "clients": {"connected_clients": 3},
        }.get(section, {})
    else:
        mock_conn.ping.side_effect = ConnectionError("Connection refused")
    return mock_conn


def _make_db_mock(stuck=None, failed_groups=None, problem_jobs=None):
    """Create a mock DB session.

    The component calls db.query(...).filter(...).all() for stuck executions,
    db.query(...).filter(...).group_by(...).all() for failed, and
    db.query(...).filter(... | ...).all() for scheduled jobs. We use
    side_effect to return different results for each successive .filter() call.
    """
    mock_db = MagicMock()
    stuck = stuck or []
    failed_groups = failed_groups or []
    problem_jobs = problem_jobs or []

    call_results = [stuck, failed_groups, problem_jobs]
    call_idx = [0]

    def filter_side(*args, **kwargs):
        m = MagicMock()
        idx = min(call_idx[0], len(call_results) - 1)
        call_idx[0] += 1
        m.all.return_value = call_results[idx]
        m.group_by.return_value.all.return_value = call_results[idx]
        return m

    mock_db.query.return_value.filter.side_effect = filter_side
    return mock_db


def _make_worker(name="worker-1", state="idle"):
    w = MagicMock()
    w.name = name
    w.get_state.return_value = state
    w.queues = [SimpleNamespace(name="default")]
    return w


def _invoke_tool(
    redis_ok=True,
    workers=None,
    queue_len=0,
    stuck=None,
    failed_groups=None,
    problem_jobs=None,
):
    """Invoke check_system_health with fully mocked dependencies."""
    mock_conn = _make_redis_mock(ping_ok=redis_ok)
    mock_db = _make_db_mock(stuck=stuck, failed_groups=failed_groups, problem_jobs=problem_jobs)

    if workers is None:
        workers = [_make_worker()]

    mock_redis_mod = MagicMock()
    mock_redis_mod.from_url.return_value = mock_conn

    mock_queue = MagicMock()
    mock_queue.__len__ = MagicMock(return_value=queue_len)

    with patch.dict("sys.modules", {}):
        pass  # no-op, just for clarity

    # Patch at import targets so lazy imports pick up mocks
    with patch("redis.from_url", mock_redis_mod.from_url), \
         patch("rq.Worker.all", return_value=workers), \
         patch("rq.Queue", return_value=mock_queue), \
         patch("database.SessionLocal", return_value=mock_db):
        tool = _get_tool()
        raw = tool.invoke({})

    return json.loads(raw)


# ── Factory tests ──────────────────────────────────────────────────────────────


class TestSystemHealthFactory:
    def test_returns_list_with_one_tool(self):
        from components.system_health import system_health_factory
        tools = system_health_factory(_make_node())
        assert isinstance(tools, list)
        assert len(tools) == 1

    def test_tool_name(self):
        tool = _get_tool()
        assert tool.name == "check_system_health"


# ── Healthy system ─────────────────────────────────────────────────────────────


class TestHealthySystem:
    def test_healthy_result(self):
        result = _invoke_tool()
        assert result["summary"] == "healthy"
        assert result["checks"]["redis"]["status"] == "ok"
        assert result["checks"]["workers"]["count"] == 1
        assert result["checks"]["stuck_executions"]["count"] == 0
        assert result["issues"] == []


# ── Redis failure ──────────────────────────────────────────────────────────────


class TestRedisFailure:
    def test_redis_down_is_critical(self):
        result = _invoke_tool(redis_ok=False)
        assert result["summary"] == "critical"
        assert result["checks"]["redis"]["status"] == "error"
        assert any(i["check"] == "redis" for i in result["issues"])


# ── No workers ─────────────────────────────────────────────────────────────────


class TestNoWorkers:
    def test_zero_workers_is_critical(self):
        result = _invoke_tool(workers=[])
        assert result["summary"] == "critical"
        assert result["checks"]["workers"]["count"] == 0
        assert any(i["check"] == "workers" for i in result["issues"])


# ── Stuck executions ───────────────────────────────────────────────────────────


class TestStuckExecutions:
    def test_stuck_execution_is_critical(self):
        stuck_exec = SimpleNamespace(
            execution_id="abc-123",
            workflow_id=1,
            started_at=_now() - timedelta(hours=1),
        )
        result = _invoke_tool(stuck=[stuck_exec])
        assert result["summary"] == "critical"
        assert result["checks"]["stuck_executions"]["count"] == 1
        assert any(i["check"] == "stuck_executions" for i in result["issues"])


# ── Failed executions ──────────────────────────────────────────────────────────


class TestFailedExecutions:
    def test_many_failures_is_degraded(self):
        failed_row = SimpleNamespace(error_message="Timeout", count=10)
        result = _invoke_tool(failed_groups=[failed_row])
        assert result["summary"] == "degraded"
        assert result["checks"]["failed_executions"]["total_24h"] == 10

    def test_few_failures_is_healthy(self):
        failed_row = SimpleNamespace(error_message="Timeout", count=2)
        result = _invoke_tool(failed_groups=[failed_row])
        assert result["summary"] == "healthy"


# ── Dead scheduled jobs ────────────────────────────────────────────────────────


class TestDeadScheduledJobs:
    def test_dead_job_is_degraded(self):
        dead_job = SimpleNamespace(
            id=42, name="test-schedule", status="dead",
            error_count=3, last_error="Connection lost",
        )
        result = _invoke_tool(problem_jobs=[dead_job])
        assert result["summary"] == "degraded"
        assert result["checks"]["scheduled_jobs"]["dead_count"] == 1
        assert any(i["check"] == "scheduled_jobs" for i in result["issues"])


# ── Output format ──────────────────────────────────────────────────────────────


class TestOutputFormat:
    def test_returns_valid_json_with_required_keys(self):
        result = _invoke_tool()
        assert "timestamp" in result
        assert "summary" in result
        assert "checks" in result
        assert "issues" in result
        assert result["summary"] in ("healthy", "degraded", "critical")

    def test_has_all_check_sections(self):
        result = _invoke_tool()
        for section in ("redis", "workers", "queues", "stuck_executions", "failed_executions", "scheduled_jobs"):
            assert section in result["checks"], f"Missing check section: {section}"
