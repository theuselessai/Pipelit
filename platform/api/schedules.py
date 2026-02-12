"""Scheduled Jobs CRUD API router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.scheduled_job import ScheduledJob
from models.user import UserProfile
from models.workflow import Workflow
from schemas.schedule import (
    BatchDeleteSchedulesIn,
    ScheduledJobCreate,
    ScheduledJobOut,
    ScheduledJobUpdate,
)
from services.scheduler import pause_scheduled_job, resume_scheduled_job, start_scheduled_job

logger = logging.getLogger(__name__)

router = APIRouter()


def _serialize(job: ScheduledJob) -> dict:
    return ScheduledJobOut.model_validate(job).model_dump()


@router.get("/")
def list_schedules(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    workflow_id: int | None = None,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    q = db.query(ScheduledJob)
    if status:
        q = q.filter(ScheduledJob.status == status)
    if workflow_id is not None:
        q = q.filter(ScheduledJob.workflow_id == workflow_id)
    total = q.count()
    jobs = q.order_by(ScheduledJob.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [_serialize(j) for j in jobs], "total": total}


@router.post("/", response_model=ScheduledJobOut, status_code=201)
def create_schedule(
    payload: ScheduledJobCreate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    # Validate workflow exists
    wf = db.query(Workflow).filter(Workflow.id == payload.workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    job = ScheduledJob(
        name=payload.name,
        description=payload.description,
        workflow_id=payload.workflow_id,
        trigger_node_id=payload.trigger_node_id,
        user_profile_id=profile.id,
        interval_seconds=payload.interval_seconds,
        total_repeats=payload.total_repeats,
        max_retries=payload.max_retries,
        timeout_seconds=payload.timeout_seconds,
        trigger_payload=payload.trigger_payload,
    )
    db.add(job)
    db.flush()

    try:
        start_scheduled_job(job)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to enqueue first run for scheduled job %s", job.id)
        raise HTTPException(status_code=500, detail="Failed to start scheduled job.")

    db.refresh(job)
    return _serialize(job)


@router.get("/{job_id}/", response_model=ScheduledJobOut)
def get_schedule(
    job_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    return _serialize(job)


@router.patch("/{job_id}/", response_model=ScheduledJobOut)
def update_schedule(
    job_id: str,
    payload: ScheduledJobUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    db.commit()
    db.refresh(job)
    return _serialize(job)


@router.delete("/{job_id}/", status_code=204)
def delete_schedule(
    job_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    db.delete(job)
    db.commit()


@router.post("/{job_id}/pause/", response_model=ScheduledJobOut)
def pause_schedule(
    job_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    if job.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot pause job with status '{job.status}'.")
    pause_scheduled_job(job)
    db.commit()
    db.refresh(job)
    return _serialize(job)


@router.post("/{job_id}/resume/", response_model=ScheduledJobOut)
def resume_schedule(
    job_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume job with status '{job.status}'.")
    resume_scheduled_job(job)
    db.commit()
    db.refresh(job)
    return _serialize(job)


@router.post("/batch-delete/", status_code=204)
def batch_delete_schedules(
    payload: BatchDeleteSchedulesIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.schedule_ids:
        return
    db.query(ScheduledJob).filter(
        ScheduledJob.id.in_(payload.schedule_ids)
    ).delete(synchronize_session=False)
    db.commit()
