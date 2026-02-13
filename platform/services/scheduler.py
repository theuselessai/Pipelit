"""Scheduler service — self-rescheduling wrapper using RQ's enqueue_in()."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from database import SessionLocal
from models.execution import WorkflowExecution
from models.scheduled_job import ScheduledJob

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def execute_scheduled_job(job_id: str, current_repeat: int = 0, current_retry: int = 0) -> None:
    """Self-rescheduling wrapper. Called by RQ worker.

    Reads ScheduledJob from DB, dispatches workflow execution,
    handles success/failure, and enqueues the next run.
    """
    db = SessionLocal()
    try:
        job = db.get(ScheduledJob, job_id)
        if not job or job.status != "active":
            return

        # Overlap protection: skip if a previous execution is still running
        running_execs = db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == job.workflow_id,
            WorkflowExecution.status.in_(["pending", "running"]),
        ).all()
        for ex in running_execs:
            payload = ex.trigger_payload or {}
            if payload.get("scheduled_job_id") == job.id:
                logger.info(
                    "Skipping scheduled job %s — execution %s still running",
                    job.id, ex.execution_id,
                )
                _enqueue_next(job, current_repeat, current_retry, job.interval_seconds)
                db.commit()
                return

        try:
            _dispatch_scheduled_trigger(job, db)
            # SUCCESS path
            job.run_count += 1
            job.current_retry = 0
            job.last_run_at = _utcnow()
            job.last_error = ""
            next_n = current_repeat + 1

            if job.total_repeats > 0 and next_n >= job.total_repeats:
                job.status = "done"
                job.next_run_at = None
            else:
                job.current_repeat = next_n
                _enqueue_next(job, next_n, 0, job.interval_seconds)

        except Exception as e:
            # FAIL path
            next_rc = current_retry + 1
            job.error_count += 1
            job.last_error = str(e)
            job.last_run_at = _utcnow()

            if next_rc > job.max_retries:
                job.status = "dead"
                job.next_run_at = None
            else:
                job.current_retry = next_rc
                backoff = _backoff(job.interval_seconds, next_rc)
                _enqueue_next(job, current_repeat, next_rc, backoff)

        db.commit()
    except Exception:
        logger.exception("Fatal error in execute_scheduled_job(%s)", job_id)
        db.rollback()
    finally:
        db.close()


def _backoff(interval: int, retry_count: int) -> int:
    """Exponential backoff capped at 10x interval."""
    return min(interval * (2 ** (retry_count - 1)), interval * 10)


def _enqueue_next(job: ScheduledJob, n: int, rc: int, delay_seconds: int) -> None:
    """Enqueue the next run of the scheduled job.

    Uses a deterministic job_id so that startup recovery cannot
    create duplicate enqueues if the job is already queued in Redis.
    """
    from tasks import execute_scheduled_job_task

    import redis
    from rq import Queue
    from config import settings

    conn = redis.from_url(settings.REDIS_URL)
    q = Queue("workflows", connection=conn)
    rq_job_id = f"sched-{job.id}-n{n}-rc{rc}"
    q.enqueue_in(
        timedelta(seconds=delay_seconds),
        execute_scheduled_job_task,
        job.id, n, rc,
        job_id=rq_job_id,
        job_timeout=job.timeout_seconds,
    )
    job.next_run_at = _utcnow() + timedelta(seconds=delay_seconds)


def _dispatch_scheduled_trigger(job: ScheduledJob, db) -> None:
    """Fire the workflow trigger."""
    from handlers import dispatch_event
    from models.user import UserProfile

    user = db.get(UserProfile, job.user_profile_id)
    if not user:
        raise ValueError(f"User {job.user_profile_id} not found for scheduled job {job.id}")

    event_data = {
        "scheduled_job_id": job.id,
        "scheduled_job_name": job.name,
        "repeat_number": job.current_repeat,
        "payload": job.trigger_payload or {},
    }
    result = dispatch_event(
        "schedule", event_data, user, db,
        workflow_id=job.workflow_id,
        trigger_node_id=job.trigger_node_id,
    )
    if result is None:
        raise ValueError(f"No matching trigger found for scheduled job {job.id}")


def start_scheduled_job(job: ScheduledJob) -> None:
    """Kick off the first run of a scheduled job (called on create/resume).

    Caller must commit the DB session after calling this.
    """
    _enqueue_next(job, job.current_repeat, job.current_retry, job.interval_seconds)


def pause_scheduled_job(job: ScheduledJob) -> None:
    """Pause — set status to paused. The wrapper checks status before running.

    Caller must commit the DB session after calling this.
    """
    job.status = "paused"
    job.next_run_at = None


def resume_scheduled_job(job: ScheduledJob) -> None:
    """Resume — set status back to active and enqueue next run.

    Caller must commit the DB session after calling this.
    """
    job.status = "active"
    start_scheduled_job(job)


def recover_scheduled_jobs() -> int:
    """Re-enqueue active jobs missed during downtime.

    Returns the number of jobs recovered.
    """
    db = SessionLocal()
    try:
        now = _utcnow()
        stale = db.query(ScheduledJob).filter(
            ScheduledJob.status == "active",
            ScheduledJob.next_run_at < now,
        ).all()
        for job in stale:
            logger.info("Recovering stale scheduled job %s (%s)", job.id, job.name)
            start_scheduled_job(job)
        db.commit()
        return len(stale)
    except Exception:
        logger.exception("Error recovering scheduled jobs")
        db.rollback()
        return 0
    finally:
        db.close()
