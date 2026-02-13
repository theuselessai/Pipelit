"""Tests for zombie execution detection and recovery."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.execution import WorkflowExecution
from services.execution_recovery import (
    recover_zombie_executions,
    _recover_one,
    _publish_zombie_event,
    _cleanup_redis,
    on_execution_job_failure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_execution(db, workflow, user_profile, *, status="running", started_at=None):
    """Create a WorkflowExecution with the given status and started_at."""
    ex = WorkflowExecution(
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        thread_id="test-thread",
        status=status,
        started_at=started_at,
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ex


def _nonclosing_session(db):
    """Return a mock SessionLocal that yields db but whose close() is a no-op."""
    mock_session = MagicMock(wraps=db)
    mock_session.close = MagicMock()  # no-op close so test session stays open
    return mock_session


def _patch_session(db):
    """Patch database.SessionLocal to return a non-closing wrapper around db."""
    return patch("database.SessionLocal", return_value=_nonclosing_session(db))


# ---------------------------------------------------------------------------
# Core recovery tests
# ---------------------------------------------------------------------------

class TestRecoverZombieExecutions:
    """Tests for the top-level recover_zombie_executions() function."""

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_stale_running_execution_recovered(self, mock_pub, mock_redis, db, workflow, user_profile):
        """A running execution older than the threshold is recovered."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=2000),
        )

        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=900)

        assert count == 1
        db.refresh(ex)
        assert ex.status == "failed"
        assert "zombie" in ex.error_message.lower()
        assert ex.completed_at is not None

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_recent_running_execution_not_recovered(self, mock_pub, mock_redis, db, workflow, user_profile):
        """A running execution younger than the threshold is left alone."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=60),
        )

        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=900)

        assert count == 0
        db.refresh(ex)
        assert ex.status == "running"

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_non_running_executions_ignored(self, mock_pub, mock_redis, db, workflow, user_profile):
        """Completed, failed, and pending executions are never touched."""
        old = _utcnow_naive() - timedelta(seconds=2000)
        for status in ("completed", "failed", "pending"):
            _make_execution(db, workflow, user_profile, status=status, started_at=old)

        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=900)

        assert count == 0

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_multiple_zombies_all_recovered(self, mock_pub, mock_redis, db, workflow, user_profile):
        """All stale running executions are recovered in one call."""
        old = _utcnow_naive() - timedelta(seconds=2000)
        execs = [
            _make_execution(db, workflow, user_profile, status="running", started_at=old)
            for _ in range(3)
        ]

        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=900)

        assert count == 3
        for ex in execs:
            db.refresh(ex)
            assert ex.status == "failed"

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_partial_failure_continues(self, mock_pub, mock_redis, db, workflow, user_profile):
        """If one recovery fails, the others still succeed."""
        old = _utcnow_naive() - timedelta(seconds=2000)
        ex1 = _make_execution(db, workflow, user_profile, status="running", started_at=old)
        ex2 = _make_execution(db, workflow, user_profile, status="running", started_at=old)

        call_count = 0
        original_recover_one = _recover_one

        def _flaky_recover(execution, sess):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            original_recover_one(execution, sess)

        with (
            _patch_session(db),
            patch("services.execution_recovery._recover_one", side_effect=_flaky_recover),
        ):
            count = recover_zombie_executions(threshold_seconds=900)

        # One succeeded, one failed
        assert count == 1

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_custom_threshold(self, mock_pub, mock_redis, db, workflow, user_profile):
        """A custom threshold_seconds parameter is respected."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=120),
        )

        # With 60s threshold, execution at 120s ago is stale
        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=60)
        assert count == 1

        # Reset
        ex.status = "running"
        ex.completed_at = None
        ex.error_message = ""
        ex.started_at = _utcnow_naive() - timedelta(seconds=120)
        db.commit()

        # With 300s threshold, same execution is not stale
        with _patch_session(db):
            count2 = recover_zombie_executions(threshold_seconds=300)
        assert count2 == 0

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_no_zombies_returns_zero(self, mock_pub, mock_redis, db, workflow, user_profile):
        """Returns 0 when there are no zombie executions."""
        with _patch_session(db):
            count = recover_zombie_executions(threshold_seconds=900)
        assert count == 0


# ---------------------------------------------------------------------------
# _recover_one tests
# ---------------------------------------------------------------------------

class TestRecoverOne:
    """Tests for the per-execution recovery helper."""

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_sets_status_and_fields(self, mock_pub, mock_redis, db, workflow, user_profile):
        """_recover_one sets status, error_message, and completed_at."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=2000),
        )
        _recover_one(ex, db)

        db.refresh(ex)
        assert ex.status == "failed"
        assert "zombie" in ex.error_message.lower()
        assert ex.completed_at is not None

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_publishes_ws_event(self, mock_pub, mock_redis, db, workflow, user_profile):
        """_recover_one publishes a WS event with the workflow slug."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=2000),
        )
        _recover_one(ex, db)

        mock_pub.assert_called_once_with(ex.execution_id, workflow.slug)

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_cleans_up_redis(self, mock_pub, mock_redis, db, workflow, user_profile):
        """_recover_one calls _cleanup_redis for the execution."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=2000),
        )
        _recover_one(ex, db)

        mock_redis.assert_called_once_with(ex.execution_id)


# ---------------------------------------------------------------------------
# _publish_zombie_event tests
# ---------------------------------------------------------------------------

class TestPublishZombieEvent:
    """Tests for best-effort WS event publishing."""

    @patch("services.execution_recovery.redis_lib")
    def test_publishes_to_execution_channel(self, mock_redis_mod):
        """Event is published to execution:<id> channel."""
        mock_r = MagicMock()
        mock_redis_mod.from_url.return_value = mock_r

        _publish_zombie_event("exec-123", None)

        mock_r.publish.assert_called_once()
        channel = mock_r.publish.call_args[0][0]
        assert channel == "execution:exec-123"

    @patch("services.execution_recovery.redis_lib")
    def test_publishes_to_workflow_channel(self, mock_redis_mod):
        """Event is also published to workflow:<slug> when slug is provided."""
        mock_r = MagicMock()
        mock_redis_mod.from_url.return_value = mock_r

        _publish_zombie_event("exec-123", "my-workflow")

        assert mock_r.publish.call_count == 2
        channels = [c[0][0] for c in mock_r.publish.call_args_list]
        assert "execution:exec-123" in channels
        assert "workflow:my-workflow" in channels

    @patch("services.execution_recovery.redis_lib")
    def test_redis_failure_does_not_raise(self, mock_redis_mod):
        """Redis errors are swallowed (best-effort)."""
        mock_redis_mod.from_url.side_effect = ConnectionError("Redis down")

        # Should not raise
        _publish_zombie_event("exec-123", "slug")


# ---------------------------------------------------------------------------
# _cleanup_redis tests
# ---------------------------------------------------------------------------

class TestCleanupRedis:
    """Tests for best-effort Redis key cleanup."""

    @patch("services.execution_recovery.redis_lib")
    def test_deletes_matching_keys(self, mock_redis_mod):
        """All execution:*:* keys are deleted."""
        mock_r = MagicMock()
        mock_redis_mod.from_url.return_value = mock_r
        mock_r.keys.return_value = [
            "execution:abc:state",
            "execution:abc:topo",
            "execution:abc:inflight",
        ]

        _cleanup_redis("abc")

        mock_r.delete.assert_called_once_with(
            "execution:abc:state",
            "execution:abc:topo",
            "execution:abc:inflight",
        )

    @patch("services.execution_recovery.redis_lib")
    def test_no_keys_no_delete(self, mock_redis_mod):
        """No delete call when there are no matching keys."""
        mock_r = MagicMock()
        mock_redis_mod.from_url.return_value = mock_r
        mock_r.keys.return_value = []

        _cleanup_redis("abc")

        mock_r.delete.assert_not_called()

    @patch("services.execution_recovery.redis_lib")
    def test_redis_failure_does_not_raise(self, mock_redis_mod):
        """Redis errors are swallowed (best-effort)."""
        mock_redis_mod.from_url.side_effect = ConnectionError("Redis down")

        # Should not raise
        _cleanup_redis("abc")


# ---------------------------------------------------------------------------
# RQ task wrapper test
# ---------------------------------------------------------------------------

class TestRQTaskWrapper:
    """Test that the tasks module wrapper delegates correctly."""

    @patch("services.execution_recovery.recover_zombie_executions", return_value=5)
    def test_task_wrapper_delegates(self, mock_recover):
        from tasks import recover_zombie_executions_job
        result = recover_zombie_executions_job()
        assert result == 5
        mock_recover.assert_called_once()


# ---------------------------------------------------------------------------
# on_execution_job_failure callback tests
# ---------------------------------------------------------------------------

def _make_mock_job(execution_id: str):
    """Create a mock RQ job with the given execution_id as first arg."""
    job = MagicMock()
    job.args = (execution_id,)
    return job


class TestOnExecutionJobFailure:
    """Tests for the RQ on_failure callback."""

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_marks_running_execution_as_failed(self, mock_pub, mock_redis, db, workflow, user_profile):
        """A running execution is marked failed when the RQ job fails."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=30),
        )
        job = _make_mock_job(ex.execution_id)

        with _patch_session(db):
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("OOM killed"), None)

        db.refresh(ex)
        assert ex.status == "failed"
        assert "RuntimeError" in ex.error_message
        assert "OOM killed" in ex.error_message
        assert ex.completed_at is not None

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_publishes_ws_event(self, mock_pub, mock_redis, db, workflow, user_profile):
        """The callback publishes a WS event for the failed execution."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=30),
        )
        job = _make_mock_job(ex.execution_id)

        with _patch_session(db):
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("timeout"), None)

        mock_pub.assert_called_once_with(
            ex.execution_id, workflow.slug,
            error="RQ job failed: RuntimeError: timeout",
        )

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_cleans_up_redis_keys(self, mock_pub, mock_redis, db, workflow, user_profile):
        """The callback cleans up Redis keys for the execution."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="running",
            started_at=_utcnow_naive() - timedelta(seconds=30),
        )
        job = _make_mock_job(ex.execution_id)

        with _patch_session(db):
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("err"), None)

        mock_redis.assert_called_once_with(ex.execution_id)

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_non_running_execution_not_modified(self, mock_pub, mock_redis, db, workflow, user_profile):
        """An already-completed execution is not modified (idempotent)."""
        ex = _make_execution(
            db, workflow, user_profile,
            status="completed",
            started_at=_utcnow_naive() - timedelta(seconds=30),
        )
        job = _make_mock_job(ex.execution_id)

        with _patch_session(db):
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("err"), None)

        db.refresh(ex)
        assert ex.status == "completed"
        mock_pub.assert_not_called()
        mock_redis.assert_not_called()

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_missing_execution_does_not_crash(self, mock_pub, mock_redis, db, workflow, user_profile):
        """A missing execution_id does not raise."""
        job = _make_mock_job("nonexistent-id")

        with _patch_session(db):
            # Should not raise
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("err"), None)

        mock_pub.assert_not_called()
        mock_redis.assert_not_called()

    @patch("services.execution_recovery._cleanup_redis")
    @patch("services.execution_recovery._publish_zombie_event")
    def test_callback_exception_does_not_propagate(self, mock_pub, mock_redis, db, workflow, user_profile):
        """If the callback itself errors, it does not propagate."""
        job = _make_mock_job("some-id")

        # Force SessionLocal to raise
        with patch("database.SessionLocal", side_effect=Exception("DB connection pool exhausted")):
            # Should not raise
            on_execution_job_failure(job, None, RuntimeError, RuntimeError("err"), None)
