"""Scheduler tools component — LangChain tools for managing scheduled jobs."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from components import register

logger = logging.getLogger(__name__)


@register("scheduler_tools")
def scheduler_tools_factory(node):
    """Return a list of LangChain tools for schedule management."""
    from database import SessionLocal
    from models.workflow import Workflow

    db = SessionLocal()
    try:
        workflow = db.query(Workflow).filter(Workflow.id == node.workflow_id).first()
        if not workflow:
            raise ValueError(f"scheduler_tools: workflow {node.workflow_id} not found")
        user_profile_id = workflow.owner_id
        if not user_profile_id:
            raise ValueError(f"scheduler_tools: workflow {node.workflow_id} has no owner_id")
    finally:
        db.close()

    @tool
    def create_schedule(
        name: str,
        workflow_id: int,
        interval_seconds: int,
        description: str = "",
        trigger_node_id: str | None = None,
        total_repeats: int = 0,
        max_retries: int = 3,
        timeout_seconds: int = 600,
    ) -> str:
        """Create a scheduled job that runs a workflow on a recurring interval.

        Args:
            name: Human-readable schedule name.
            workflow_id: ID of the workflow to execute.
            interval_seconds: Seconds between successful runs.
            description: Optional description.
            trigger_node_id: Specific trigger node_id to target (optional).
            total_repeats: Total runs before stopping (0 = infinite).
            max_retries: Max retries per run on failure (default 3).
            timeout_seconds: Per-execution timeout (default 600).

        Returns:
            JSON with success, schedule_id, name, status.
        """
        from database import SessionLocal
        from models.scheduled_job import ScheduledJob
        from models.workflow import Workflow
        from services.scheduler import start_scheduled_job

        if interval_seconds < 1:
            return json.dumps({"success": False, "error": "interval_seconds must be >= 1"})

        db = SessionLocal()
        try:
            wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not wf:
                return json.dumps({"success": False, "error": f"Workflow {workflow_id} not found"})

            job = ScheduledJob(
                name=name,
                description=description,
                workflow_id=workflow_id,
                trigger_node_id=trigger_node_id,
                user_profile_id=user_profile_id,
                interval_seconds=interval_seconds,
                total_repeats=total_repeats,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            db.add(job)
            db.flush()

            try:
                start_scheduled_job(job)
            except Exception as e:
                logger.warning("Failed to enqueue first run: %s", e)

            db.commit()
            db.refresh(job)
            return json.dumps({
                "success": True,
                "schedule_id": job.id,
                "name": job.name,
                "status": job.status,
            })
        except Exception as e:
            db.rollback()
            logger.exception("Error creating schedule")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def pause_schedule(schedule_id: str) -> str:
        """Pause a running scheduled job. It will stop rescheduling until resumed.

        Args:
            schedule_id: The schedule UUID.

        Returns:
            JSON with success and new status.
        """
        from database import SessionLocal
        from models.scheduled_job import ScheduledJob
        from services.scheduler import pause_scheduled_job

        db = SessionLocal()
        try:
            job = db.get(ScheduledJob, schedule_id)
            if not job:
                return json.dumps({"success": False, "error": "Schedule not found"})
            if job.status != "active":
                return json.dumps({"success": False, "error": f"Cannot pause job with status '{job.status}'"})
            pause_scheduled_job(job)
            db.commit()
            return json.dumps({"success": True, "schedule_id": job.id, "status": job.status})
        except Exception as e:
            db.rollback()
            logger.exception("Error pausing schedule")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def resume_schedule(schedule_id: str) -> str:
        """Resume a paused scheduled job.

        Args:
            schedule_id: The schedule UUID.

        Returns:
            JSON with success and new status.
        """
        from database import SessionLocal
        from models.scheduled_job import ScheduledJob
        from services.scheduler import resume_scheduled_job

        db = SessionLocal()
        try:
            job = db.get(ScheduledJob, schedule_id)
            if not job:
                return json.dumps({"success": False, "error": "Schedule not found"})
            if job.status != "paused":
                return json.dumps({"success": False, "error": f"Cannot resume job with status '{job.status}'"})
            resume_scheduled_job(job)
            db.commit()
            return json.dumps({"success": True, "schedule_id": job.id, "status": job.status})
        except Exception as e:
            db.rollback()
            logger.exception("Error resuming schedule")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def stop_schedule(schedule_id: str) -> str:
        """Permanently delete a scheduled job.

        Args:
            schedule_id: The schedule UUID.

        Returns:
            JSON with success.
        """
        from database import SessionLocal
        from models.scheduled_job import ScheduledJob

        db = SessionLocal()
        try:
            job = db.get(ScheduledJob, schedule_id)
            if not job:
                return json.dumps({"success": False, "error": "Schedule not found"})
            db.delete(job)
            db.commit()
            return json.dumps({"success": True, "schedule_id": schedule_id, "deleted": True})
        except Exception as e:
            db.rollback()
            logger.exception("Error deleting schedule")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    @tool
    def list_schedules(
        status: str | None = None,
        workflow_id: int | None = None,
        limit: int = 10,
    ) -> str:
        """List scheduled jobs with optional filters.

        Args:
            status: Filter by status (active, paused, stopped, dead, done).
            workflow_id: Filter by workflow ID.
            limit: Max results (default 10).

        Returns:
            JSON with results list.
        """
        from database import SessionLocal
        from models.scheduled_job import ScheduledJob

        limit = max(1, min(limit, 100))
        db = SessionLocal()
        try:
            q = db.query(ScheduledJob)
            if status:
                q = q.filter(ScheduledJob.status == status)
            if workflow_id is not None:
                q = q.filter(ScheduledJob.workflow_id == workflow_id)

            jobs = q.order_by(ScheduledJob.created_at.desc()).limit(limit).all()
            results = [
                {
                    "schedule_id": j.id,
                    "name": j.name,
                    "status": j.status,
                    "workflow_id": j.workflow_id,
                    "interval_seconds": j.interval_seconds,
                    "run_count": j.run_count,
                    "error_count": j.error_count,
                }
                for j in jobs
            ]
            return json.dumps({"success": True, "results": results})
        except Exception as e:
            logger.exception("Error listing schedules")
            return json.dumps({"success": False, "error": str(e)})
        finally:
            db.close()

    return [create_schedule, pause_schedule, resume_schedule, stop_schedule, list_schedules]
