"""Detect and recover zombie executions stuck in 'running' state.

A zombie execution is one whose RQ worker crashed (OOM, host reboot, etc.)
leaving the DB row in ``status='running'`` with no worker to finish it.

Two entry points:

- ``recover_zombie_executions()`` — called on server startup (mirrors
  ``recover_scheduled_jobs()`` in ``services/scheduler.py``)
- ``recover_zombie_executions_job()`` in ``tasks/__init__.py`` — periodic
  RQ watchdog (mirrors ``cleanup_stuck_child_waits_job()``)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import redis as redis_lib
from sqlalchemy.orm import Session

from config import settings

logger = logging.getLogger(__name__)


def recover_zombie_executions(threshold_seconds: int | None = None) -> int:
    """Find and recover all zombie executions.

    An execution is considered a zombie when:
    - ``status == 'running'``
    - ``started_at`` is older than *threshold_seconds* ago

    Each zombie is marked ``failed`` with an explanatory error message,
    a WebSocket event is published, and its Redis keys are cleaned up.

    Returns the number of executions recovered.
    """
    from database import SessionLocal
    from models.execution import WorkflowExecution

    if threshold_seconds is None:
        threshold_seconds = settings.ZOMBIE_EXECUTION_THRESHOLD_SECONDS

    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - _timedelta(threshold_seconds)
        zombies = (
            db.query(WorkflowExecution)
            .filter(
                WorkflowExecution.status == "running",
                WorkflowExecution.started_at < cutoff,
            )
            .all()
        )
        if not zombies:
            return 0

        recovered = 0
        for execution in zombies:
            try:
                _recover_one(execution, db)
                recovered += 1
            except Exception:
                logger.exception(
                    "Failed to recover zombie execution %s", execution.execution_id,
                )
        return recovered
    except Exception:
        logger.exception("Error in recover_zombie_executions")
        return 0
    finally:
        db.close()


def _recover_one(execution, db: Session) -> None:
    """Mark a single zombie execution as failed and clean up."""
    from models.workflow import Workflow

    execution_id = execution.execution_id
    logger.warning("Recovering zombie execution %s", execution_id)

    execution.status = "failed"
    execution.error_message = (
        "Execution recovered as failed: worker presumed crashed "
        "(exceeded zombie threshold)"
    )
    execution.completed_at = datetime.now(timezone.utc)
    db.commit()

    # Look up workflow slug for the WS event (best-effort)
    workflow_slug = None
    try:
        wf = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
        if wf:
            workflow_slug = wf.slug
    except Exception:
        pass

    _publish_zombie_event(execution_id, workflow_slug)
    _cleanup_redis(execution_id)


def _publish_zombie_event(execution_id: str, workflow_slug: str | None) -> None:
    """Publish an ``execution_failed`` event via Redis pub/sub (best-effort)."""
    try:
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            payload = {
                "type": "execution_failed",
                "execution_id": execution_id,
                "timestamp": time.time(),
                "data": {"error": "Execution recovered as failed (zombie)"},
            }
            raw = json.dumps(payload)
            r.publish(f"execution:{execution_id}", raw)
            if workflow_slug:
                payload["channel"] = f"workflow:{workflow_slug}"
                r.publish(f"workflow:{workflow_slug}", json.dumps(payload))
        finally:
            r.close()
    except Exception:
        logger.warning(
            "Failed to publish zombie event for execution %s (non-fatal)",
            execution_id,
            exc_info=True,
        )


def _cleanup_redis(execution_id: str) -> None:
    """Delete ``execution:{id}:*`` keys from Redis (best-effort)."""
    try:
        r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            keys = r.keys(f"execution:{execution_id}:*")
            if keys:
                r.delete(*keys)
        finally:
            r.close()
    except Exception:
        logger.warning(
            "Failed to clean up Redis keys for execution %s (non-fatal)",
            execution_id,
            exc_info=True,
        )


def _timedelta(seconds: int):
    """Helper to avoid import at module top level for tests."""
    from datetime import timedelta
    return timedelta(seconds=seconds)
