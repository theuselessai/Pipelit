"""Tests for the scheduler feature — state machine, backoff, API CRUD, recovery."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.scheduled_job import ScheduledJob
from services.scheduler import _backoff, execute_scheduled_job, recover_scheduled_jobs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def scheduled_job(db, workflow, user_profile):
    job = ScheduledJob(
        name="Test Schedule",
        description="A test scheduled job",
        workflow_id=workflow.id,
        user_profile_id=user_profile.id,
        interval_seconds=300,
        total_repeats=5,
        max_retries=3,
        timeout_seconds=600,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Backoff Tests
# ---------------------------------------------------------------------------

class TestBackoff:
    def test_backoff_retry_1(self):
        assert _backoff(300, 1) == 300

    def test_backoff_retry_2(self):
        assert _backoff(300, 2) == 600

    def test_backoff_retry_3(self):
        assert _backoff(300, 3) == 1200

    def test_backoff_capped_at_10x(self):
        # 300 * 2^9 = 153600, but cap is 300 * 10 = 3000
        assert _backoff(300, 10) == 3000

    def test_backoff_small_interval(self):
        assert _backoff(10, 1) == 10
        assert _backoff(10, 2) == 20
        assert _backoff(10, 5) == 100  # cap


# ---------------------------------------------------------------------------
# State Machine Tests
# ---------------------------------------------------------------------------

class TestStateMachine:
    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler._dispatch_scheduled_trigger")
    @patch("services.scheduler.SessionLocal")
    def test_success_advances_repeat(self, mock_session_cls, mock_dispatch, mock_enqueue, db, scheduled_job):
        """SUCCESS → next repeat (n+1, rc=0)."""
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=0, current_retry=0)

        assert scheduled_job.run_count == 1
        assert scheduled_job.current_retry == 0
        assert scheduled_job.current_repeat == 1
        mock_enqueue.assert_called_once_with(scheduled_job, 1, 0, 300)
        mock_session.commit.assert_called_once()

    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler._dispatch_scheduled_trigger")
    @patch("services.scheduler.SessionLocal")
    def test_success_final_repeat_marks_done(self, mock_session_cls, mock_dispatch, mock_enqueue, db, scheduled_job):
        """SUCCESS on last repeat → status='done'."""
        scheduled_job.total_repeats = 5
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=4, current_retry=0)

        assert scheduled_job.status == "done"
        assert scheduled_job.run_count == 1
        mock_enqueue.assert_not_called()

    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler._dispatch_scheduled_trigger", side_effect=Exception("trigger failed"))
    @patch("services.scheduler.SessionLocal")
    def test_failure_retries(self, mock_session_cls, mock_dispatch, mock_enqueue, db, scheduled_job):
        """FAIL → retry with backoff (same n, rc+1)."""
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=2, current_retry=0)

        assert scheduled_job.error_count == 1
        assert scheduled_job.current_retry == 1
        assert scheduled_job.last_error == "trigger failed"
        mock_enqueue.assert_called_once_with(scheduled_job, 2, 1, _backoff(300, 1))

    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler._dispatch_scheduled_trigger", side_effect=Exception("trigger failed"))
    @patch("services.scheduler.SessionLocal")
    def test_failure_exhausts_retries_marks_dead(self, mock_session_cls, mock_dispatch, mock_enqueue, db, scheduled_job):
        """FAIL with rc+1 > max_retries → status='dead'."""
        scheduled_job.max_retries = 3
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=2, current_retry=3)

        assert scheduled_job.status == "dead"
        mock_enqueue.assert_not_called()

    @patch("services.scheduler._dispatch_scheduled_trigger")
    @patch("services.scheduler.SessionLocal")
    def test_paused_job_skipped(self, mock_session_cls, mock_dispatch, db, scheduled_job):
        """Paused job → wrapper returns early, no dispatch."""
        scheduled_job.status = "paused"
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=0, current_retry=0)

        mock_dispatch.assert_not_called()

    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler._dispatch_scheduled_trigger")
    @patch("services.scheduler.SessionLocal")
    def test_infinite_repeat_never_done(self, mock_session_cls, mock_dispatch, mock_enqueue, db, scheduled_job):
        """total_repeats=0 (infinite) → never reaches 'done' status."""
        scheduled_job.total_repeats = 0
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, current_repeat=999, current_retry=0)

        assert scheduled_job.status == "active"
        assert scheduled_job.current_repeat == 1000
        mock_enqueue.assert_called_once()

    @patch("services.scheduler._dispatch_scheduled_trigger")
    @patch("services.scheduler.SessionLocal")
    def test_deleted_job_skipped(self, mock_session_cls, mock_dispatch):
        """Job not found in DB → wrapper returns silently."""
        mock_session = MagicMock()
        mock_session.get.return_value = None
        mock_session_cls.return_value = mock_session

        execute_scheduled_job("nonexistent-id")
        mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Pause / Resume Tests
# ---------------------------------------------------------------------------

class TestPauseResume:
    def test_pause(self, db, scheduled_job):
        from services.scheduler import pause_scheduled_job
        pause_scheduled_job(scheduled_job)
        assert scheduled_job.status == "paused"
        assert scheduled_job.next_run_at is None

    @patch("services.scheduler._enqueue_next")
    def test_resume(self, mock_enqueue, db, scheduled_job):
        from services.scheduler import pause_scheduled_job, resume_scheduled_job
        pause_scheduled_job(scheduled_job)
        resume_scheduled_job(scheduled_job)
        assert scheduled_job.status == "active"
        mock_enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Startup Recovery Tests
# ---------------------------------------------------------------------------

class TestRecovery:
    @patch("services.scheduler.start_scheduled_job")
    @patch("services.scheduler.SessionLocal")
    def test_recover_stale_jobs(self, mock_session_cls, mock_start):
        """Active jobs with next_run_at in the past are recovered."""
        stale_job = MagicMock()
        stale_job.status = "active"
        stale_job.next_run_at = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_session = MagicMock()
        mock_query = mock_session.query.return_value
        mock_query.filter.return_value.all.return_value = [stale_job]
        mock_session_cls.return_value = mock_session

        count = recover_scheduled_jobs()

        assert count == 1
        mock_start.assert_called_once_with(stale_job)
        mock_session.commit.assert_called_once()

    @patch("services.scheduler.start_scheduled_job")
    @patch("services.scheduler.SessionLocal")
    def test_no_stale_jobs(self, mock_session_cls, mock_start):
        mock_session = MagicMock()
        mock_query = mock_session.query.return_value
        mock_query.filter.return_value.all.return_value = []
        mock_session_cls.return_value = mock_session

        count = recover_scheduled_jobs()

        assert count == 0
        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestScheduleAPI:
    @patch("services.scheduler.start_scheduled_job")
    def test_create_schedule(self, mock_start, auth_client, workflow):
        resp = auth_client.post("/api/v1/schedules/", json={
            "name": "My Schedule",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
            "total_repeats": 10,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Schedule"
        assert data["status"] == "active"
        assert data["interval_seconds"] == 60
        assert data["total_repeats"] == 10

    @patch("services.scheduler.start_scheduled_job")
    def test_list_schedules(self, mock_start, auth_client, workflow):
        # Create one
        auth_client.post("/api/v1/schedules/", json={
            "name": "Sched1",
            "workflow_id": workflow.id,
            "interval_seconds": 120,
        })
        resp = auth_client.get("/api/v1/schedules/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    @patch("services.scheduler.start_scheduled_job")
    def test_get_schedule(self, mock_start, auth_client, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "GetTest",
            "workflow_id": workflow.id,
            "interval_seconds": 300,
        })
        job_id = create_resp.json()["id"]
        resp = auth_client.get(f"/api/v1/schedules/{job_id}/")
        assert resp.status_code == 200
        assert resp.json()["name"] == "GetTest"

    @patch("services.scheduler.start_scheduled_job")
    def test_update_schedule(self, mock_start, auth_client, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "UpdateTest",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        resp = auth_client.patch(f"/api/v1/schedules/{job_id}/", json={
            "name": "Updated Name",
            "interval_seconds": 120,
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["interval_seconds"] == 120

    @patch("services.scheduler.start_scheduled_job")
    def test_delete_schedule(self, mock_start, auth_client, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "DeleteTest",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        resp = auth_client.delete(f"/api/v1/schedules/{job_id}/")
        assert resp.status_code == 204

        # Confirm deleted
        resp = auth_client.get(f"/api/v1/schedules/{job_id}/")
        assert resp.status_code == 404

    @patch("services.scheduler.start_scheduled_job")
    @patch("services.scheduler.pause_scheduled_job")
    def test_pause_schedule(self, mock_pause, mock_start, auth_client, db, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "PauseTest",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        resp = auth_client.post(f"/api/v1/schedules/{job_id}/pause/")
        assert resp.status_code == 200

    @patch("services.scheduler.start_scheduled_job")
    def test_pause_non_active_fails(self, mock_start, auth_client, db, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "PauseFail",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        # Set to paused manually
        job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
        job.status = "paused"
        db.commit()
        resp = auth_client.post(f"/api/v1/schedules/{job_id}/pause/")
        assert resp.status_code == 400

    @patch("services.scheduler.start_scheduled_job")
    @patch("services.scheduler.resume_scheduled_job")
    def test_resume_schedule(self, mock_resume, mock_start, auth_client, db, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "ResumeTest",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        # Set to paused first
        job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
        job.status = "paused"
        db.commit()
        resp = auth_client.post(f"/api/v1/schedules/{job_id}/resume/")
        assert resp.status_code == 200

    @patch("services.scheduler.start_scheduled_job")
    def test_resume_non_paused_fails(self, mock_start, auth_client, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "ResumeFail",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        resp = auth_client.post(f"/api/v1/schedules/{job_id}/resume/")
        assert resp.status_code == 400

    @patch("services.scheduler.start_scheduled_job")
    def test_batch_delete(self, mock_start, auth_client, workflow):
        ids = []
        for i in range(3):
            create_resp = auth_client.post("/api/v1/schedules/", json={
                "name": f"Batch{i}",
                "workflow_id": workflow.id,
                "interval_seconds": 60,
            })
            ids.append(create_resp.json()["id"])

        resp = auth_client.post("/api/v1/schedules/batch-delete/", json={
            "schedule_ids": ids,
        })
        assert resp.status_code == 204

    def test_create_invalid_interval(self, auth_client, workflow):
        resp = auth_client.post("/api/v1/schedules/", json={
            "name": "Bad",
            "workflow_id": workflow.id,
            "interval_seconds": 0,
        })
        assert resp.status_code == 422

    def test_create_nonexistent_workflow(self, auth_client):
        resp = auth_client.post("/api/v1/schedules/", json={
            "name": "Bad",
            "workflow_id": 99999,
            "interval_seconds": 60,
        })
        assert resp.status_code == 404

    @patch("services.scheduler.start_scheduled_job")
    def test_list_filter_by_status(self, mock_start, auth_client, db, workflow):
        create_resp = auth_client.post("/api/v1/schedules/", json={
            "name": "FilterTest",
            "workflow_id": workflow.id,
            "interval_seconds": 60,
        })
        job_id = create_resp.json()["id"]
        job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
        job.status = "paused"
        db.commit()

        resp = auth_client.get("/api/v1/schedules/?status=paused")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
        assert all(j["status"] == "paused" for j in resp.json()["items"])


# ---------------------------------------------------------------------------
# ScheduledJobUpdate Validator Tests
# ---------------------------------------------------------------------------

class TestScheduledJobCreateValidators:
    def test_interval_seconds_zero_rejected(self):
        from schemas.schedule import ScheduledJobCreate
        with pytest.raises(Exception, match="interval_seconds must be >= 1"):
            ScheduledJobCreate(name="t", workflow_id=1, interval_seconds=0)

    def test_total_repeats_negative_rejected(self):
        from schemas.schedule import ScheduledJobCreate
        with pytest.raises(Exception, match="total_repeats must be >= 0"):
            ScheduledJobCreate(name="t", workflow_id=1, interval_seconds=60, total_repeats=-1)

    def test_max_retries_negative_rejected(self):
        from schemas.schedule import ScheduledJobCreate
        with pytest.raises(Exception, match="max_retries must be >= 0"):
            ScheduledJobCreate(name="t", workflow_id=1, interval_seconds=60, max_retries=-1)

    def test_timeout_seconds_zero_rejected(self):
        from schemas.schedule import ScheduledJobCreate
        with pytest.raises(Exception, match="timeout_seconds must be >= 1"):
            ScheduledJobCreate(name="t", workflow_id=1, interval_seconds=60, timeout_seconds=0)


class TestScheduledJobUpdateValidators:
    def test_interval_seconds_zero_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="interval_seconds must be >= 1"):
            ScheduledJobUpdate(interval_seconds=0)

    def test_interval_seconds_negative_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="interval_seconds must be >= 1"):
            ScheduledJobUpdate(interval_seconds=-5)

    def test_interval_seconds_valid(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(interval_seconds=60)
        assert obj.interval_seconds == 60

    def test_interval_seconds_none_ok(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(interval_seconds=None)
        assert obj.interval_seconds is None

    def test_total_repeats_negative_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="total_repeats must be >= 0"):
            ScheduledJobUpdate(total_repeats=-1)

    def test_total_repeats_valid(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(total_repeats=10)
        assert obj.total_repeats == 10

    def test_total_repeats_none_ok(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(total_repeats=None)
        assert obj.total_repeats is None

    def test_max_retries_negative_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="max_retries must be >= 0"):
            ScheduledJobUpdate(max_retries=-1)

    def test_max_retries_valid(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(max_retries=5)
        assert obj.max_retries == 5

    def test_max_retries_none_ok(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(max_retries=None)
        assert obj.max_retries is None

    def test_timeout_seconds_zero_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="timeout_seconds must be >= 1"):
            ScheduledJobUpdate(timeout_seconds=0)

    def test_timeout_seconds_negative_rejected(self):
        from schemas.schedule import ScheduledJobUpdate
        with pytest.raises(Exception, match="timeout_seconds must be >= 1"):
            ScheduledJobUpdate(timeout_seconds=-10)

    def test_timeout_seconds_valid(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(timeout_seconds=300)
        assert obj.timeout_seconds == 300

    def test_timeout_seconds_none_ok(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate(timeout_seconds=None)
        assert obj.timeout_seconds is None

    def test_empty_update_ok(self):
        from schemas.schedule import ScheduledJobUpdate
        obj = ScheduledJobUpdate()
        assert obj.interval_seconds is None
        assert obj.total_repeats is None


# ---------------------------------------------------------------------------
# Scheduler dispatch and recovery edge cases
# ---------------------------------------------------------------------------

class TestSchedulerDispatch:
    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler.SessionLocal")
    def test_dispatch_happy_path(self, mock_session_cls, mock_enqueue, db, scheduled_job):
        """_dispatch_scheduled_trigger fires the workflow trigger."""
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job

        mock_user = MagicMock()
        mock_user.id = scheduled_job.user_profile_id

        # Mock dispatch_event to return a result
        with patch("services.scheduler._dispatch_scheduled_trigger") as mock_dispatch:
            mock_dispatch.return_value = None  # no exception
            mock_session_cls.return_value = mock_session

            execute_scheduled_job(scheduled_job.id, 0, 0)

            mock_dispatch.assert_called_once_with(scheduled_job, mock_session)

    @patch("services.scheduler.SessionLocal")
    def test_fatal_exception_logged(self, mock_session_cls):
        """Fatal exception during execute_scheduled_job → logged, rolled back."""
        mock_session = MagicMock()
        mock_session.get.side_effect = RuntimeError("DB down")
        mock_session_cls.return_value = mock_session

        # Should not raise
        execute_scheduled_job("job-1")

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    @patch("services.scheduler._enqueue_next")
    @patch("services.scheduler.SessionLocal")
    def test_overlap_protection_skips(self, mock_session_cls, mock_enqueue, db, scheduled_job):
        """Running execution with same scheduled_job_id → skip."""
        mock_session = MagicMock()
        mock_session.get.return_value = scheduled_job

        running_exec = MagicMock()
        running_exec.trigger_payload = {"scheduled_job_id": scheduled_job.id}
        mock_session.query.return_value.filter.return_value.all.return_value = [running_exec]
        mock_session_cls.return_value = mock_session

        execute_scheduled_job(scheduled_job.id, 0, 0)

        # Should enqueue next (reschedule) but NOT dispatch
        mock_enqueue.assert_called_once()
        mock_session.commit.assert_called()

    @patch("services.scheduler.start_scheduled_job")
    @patch("services.scheduler.SessionLocal")
    def test_recovery_exception_returns_zero(self, mock_session_cls, mock_start):
        """Exception in recover_scheduled_jobs → returns 0."""
        mock_session = MagicMock()
        mock_session.query.side_effect = RuntimeError("DB down")
        mock_session_cls.return_value = mock_session

        count = recover_scheduled_jobs()
        assert count == 0
        mock_session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# _dispatch_scheduled_trigger Tests
# ---------------------------------------------------------------------------

class TestDispatchScheduledTrigger:
    def test_dispatch_calls_dispatch_event(self, db, scheduled_job, user_profile):
        from services.scheduler import _dispatch_scheduled_trigger

        mock_dispatch = MagicMock(return_value="result")
        with patch("handlers.dispatch_event", mock_dispatch):
            _dispatch_scheduled_trigger(scheduled_job, db)

        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        assert call_args[0][0] == "schedule"
        assert call_args[0][1]["scheduled_job_id"] == scheduled_job.id

    def test_dispatch_user_not_found_raises(self, db, scheduled_job):
        from services.scheduler import _dispatch_scheduled_trigger

        # Set a nonexistent user id
        scheduled_job.user_profile_id = 99999

        with pytest.raises(ValueError, match="User.*not found"):
            _dispatch_scheduled_trigger(scheduled_job, db)

    def test_dispatch_no_trigger_found_raises(self, db, scheduled_job, user_profile):
        from services.scheduler import _dispatch_scheduled_trigger

        mock_dispatch = MagicMock(return_value=None)
        with patch("handlers.dispatch_event", mock_dispatch):
            with pytest.raises(ValueError, match="No matching trigger"):
                _dispatch_scheduled_trigger(scheduled_job, db)


# ---------------------------------------------------------------------------
# _enqueue_next Tests
# ---------------------------------------------------------------------------

class TestEnqueueNext:
    def test_enqueue_next_sets_next_run_at(self, db, scheduled_job):
        from services.scheduler import _enqueue_next

        mock_conn = MagicMock()
        mock_queue = MagicMock()

        with patch("redis.from_url", return_value=mock_conn), \
             patch("rq.Queue", return_value=mock_queue):
            _enqueue_next(scheduled_job, 0, 0, 300)

        assert scheduled_job.next_run_at is not None
        mock_queue.enqueue_in.assert_called_once()
        call_kwargs = mock_queue.enqueue_in.call_args[1]
        assert call_kwargs["job_id"] == f"sched-{scheduled_job.id}-n0-rc0"
        assert call_kwargs["job_timeout"] == scheduled_job.timeout_seconds
