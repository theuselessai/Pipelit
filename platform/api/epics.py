"""Epic CRUD API router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.epic import Epic, Task
from models.user import UserProfile
from schemas.epic import BatchDeleteEpicsIn, EpicCreate, EpicOut, EpicUpdate, TaskOut
from api.epic_helpers import serialize_epic, serialize_task, sync_epic_progress
from ws.broadcast import broadcast

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def list_epics(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    tags: str | None = None,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    q = db.query(Epic).filter(Epic.user_profile_id == profile.id)
    if status:
        q = q.filter(Epic.status == status)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            q = q.filter(or_(*[Epic.tags.contains(tag) for tag in tag_list]))
    total = q.count()
    epics = q.order_by(Epic.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [serialize_epic(e) for e in epics], "total": total}


@router.post("/", response_model=EpicOut, status_code=201)
def create_epic(
    payload: EpicCreate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    epic = Epic(
        title=payload.title,
        description=payload.description,
        tags=payload.tags,
        priority=payload.priority,
        budget_tokens=payload.budget_tokens,
        budget_usd=payload.budget_usd,
        workflow_id=payload.workflow_id,
        user_profile_id=profile.id,
    )
    db.add(epic)
    db.commit()
    db.refresh(epic)
    try:
        broadcast(f"epic:{epic.id}", "epic_created", serialize_epic(epic))
    except Exception:
        logger.exception("Failed to broadcast epic event")
    return serialize_epic(epic)


@router.get("/{epic_id}/", response_model=EpicOut)
def get_epic(
    epic_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    epic = (
        db.query(Epic)
        .filter(Epic.id == epic_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found.")
    return serialize_epic(epic)


@router.patch("/{epic_id}/", response_model=EpicOut)
def update_epic(
    epic_id: str,
    payload: EpicUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    epic = (
        db.query(Epic)
        .filter(Epic.id == epic_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(epic, field, value)

    # If status changed to cancelled, cascade-cancel pending/running tasks
    if payload.status == "cancelled":
        tasks = (
            db.query(Task)
            .filter(
                Task.epic_id == epic.id,
                Task.status.in_(["pending", "blocked", "running"]),
            )
            .all()
        )
        for task in tasks:
            task.status = "cancelled"
        sync_epic_progress(epic, db)

    db.commit()
    db.refresh(epic)
    try:
        broadcast(f"epic:{epic.id}", "epic_updated", serialize_epic(epic))
    except Exception:
        logger.exception("Failed to broadcast epic event")
    return serialize_epic(epic)


@router.delete("/{epic_id}/", status_code=204)
def delete_epic(
    epic_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    epic = (
        db.query(Epic)
        .filter(Epic.id == epic_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found.")
    db.delete(epic)
    db.commit()
    try:
        broadcast(f"epic:{epic_id}", "epic_deleted", {"id": epic_id})
    except Exception:
        logger.exception("Failed to broadcast epic event")


@router.post("/batch-delete/", status_code=204)
def batch_delete_epics(
    payload: BatchDeleteEpicsIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.epic_ids:
        return
    # Only delete tasks belonging to the user's epics
    user_epic_ids = db.query(Epic.id).filter(
        Epic.id.in_(payload.epic_ids), Epic.user_profile_id == profile.id
    )
    db.query(Task).filter(Task.epic_id.in_(user_epic_ids)).delete(
        synchronize_session=False
    )
    db.query(Epic).filter(
        Epic.id.in_(payload.epic_ids), Epic.user_profile_id == profile.id
    ).delete(synchronize_session=False)
    db.commit()


@router.get("/{epic_id}/tasks/")
def list_epic_tasks(
    epic_id: str,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    # Verify epic exists and belongs to user
    epic = (
        db.query(Epic)
        .filter(Epic.id == epic_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found.")

    q = db.query(Task).filter(Task.epic_id == epic_id)
    total = q.count()
    tasks = q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [serialize_task(t) for t in tasks], "total": total}
