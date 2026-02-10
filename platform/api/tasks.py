"""Task CRUD API router."""

from __future__ import annotations

import logging

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.epic import Epic, Task
from models.user import UserProfile
from schemas.epic import BatchDeleteTasksIn, TaskCreate, TaskOut, TaskUpdate
from api.epic_helpers import remove_from_depends_on, serialize_task, sync_epic_progress
from ws.broadcast import broadcast

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def list_tasks(
    limit: int = 50,
    offset: int = 0,
    epic_id: str | None = None,
    status: str | None = None,
    tags: str | None = None,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    q = db.query(Task).join(Epic).filter(Epic.user_profile_id == profile.id)
    if epic_id:
        q = q.filter(Task.epic_id == epic_id)
    if status:
        q = q.filter(Task.status == status)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            q = q.filter(or_(*[Task.tags.contains(tag) for tag in tag_list]))
    total = q.count()
    tasks = q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [serialize_task(t) for t in tasks], "total": total}


@router.post("/", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    # Verify epic exists and belongs to user
    epic = (
        db.query(Epic)
        .filter(Epic.id == payload.epic_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found.")

    # Determine initial status — blocked if depends_on has unfinished deps
    initial_status = "pending"
    if payload.depends_on:
        completed_deps = (
            db.query(Task)
            .filter(Task.id.in_(payload.depends_on), Task.status == "completed")
            .count()
        )
        if completed_deps < len(payload.depends_on):
            initial_status = "blocked"

    task = Task(
        epic_id=payload.epic_id,
        title=payload.title,
        description=payload.description,
        tags=payload.tags,
        depends_on=payload.depends_on,
        priority=payload.priority if payload.priority is not None else 2,
        workflow_slug=payload.workflow_slug,
        estimated_tokens=payload.estimated_tokens,
        max_retries=payload.max_retries,
        requirements=payload.requirements,
        status=initial_status,
    )
    db.add(task)
    db.flush()

    sync_epic_progress(epic, db)

    db.commit()
    db.refresh(task)
    try:
        broadcast(f"epic:{task.epic_id}", "task_created", serialize_task(task))
    except Exception:
        logger.exception("Failed to broadcast task event")
    return serialize_task(task)


@router.get("/{task_id}/", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .join(Epic)
        .filter(Task.id == task_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return serialize_task(task)


@router.patch("/{task_id}/", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .join(Epic)
        .filter(Task.id == task_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # Flush so count queries in sync_epic_progress see the updated status
    db.flush()

    # Sync epic progress counters
    epic = db.query(Epic).filter(Epic.id == task.epic_id).first()
    if epic:
        sync_epic_progress(epic, db)

    db.commit()
    db.refresh(task)
    try:
        broadcast(f"epic:{task.epic_id}", "task_updated", serialize_task(task))
    except Exception:
        logger.exception("Failed to broadcast task event")
    return serialize_task(task)


@router.delete("/{task_id}/", status_code=204)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .join(Epic)
        .filter(Task.id == task_id, Epic.user_profile_id == profile.id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    epic_id = task.epic_id
    remove_from_depends_on([task.id], db)
    db.delete(task)
    db.flush()

    # Sync epic progress counters
    epic = db.query(Epic).filter(Epic.id == epic_id).first()
    if epic:
        sync_epic_progress(epic, db)

    db.commit()
    try:
        broadcast(f"epic:{epic_id}", "task_deleted", {"id": task_id})
    except Exception:
        logger.exception("Failed to broadcast task event")


@router.post("/batch-delete/", status_code=204)
def batch_delete_tasks(
    payload: BatchDeleteTasksIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.task_ids:
        return

    # Find affected epic IDs and task IDs before deleting
    affected_tasks = (
        db.query(Task)
        .join(Epic)
        .filter(Task.id.in_(payload.task_ids), Epic.user_profile_id == profile.id)
        .all()
    )
    epic_to_task_ids: dict[str, list[str]] = defaultdict(list)
    for t in affected_tasks:
        epic_to_task_ids[t.epic_id].append(t.id)
    affected_epic_ids = set(epic_to_task_ids.keys())
    deleted_task_ids = [t.id for t in affected_tasks]

    remove_from_depends_on(deleted_task_ids, db)

    db.query(Task).filter(
        Task.id.in_(payload.task_ids),
        Task.epic_id.in_(
            db.query(Epic.id).filter(Epic.user_profile_id == profile.id)
        ),
    ).delete(synchronize_session=False)

    # Sync progress for affected epics
    for epic_id in affected_epic_ids:
        epic = db.query(Epic).filter(Epic.id == epic_id).first()
        if epic:
            sync_epic_progress(epic, db)

    db.commit()

    for epic_id, task_ids in epic_to_task_ids.items():
        try:
            broadcast(f"epic:{epic_id}", "tasks_deleted", {"task_ids": task_ids})
        except Exception:
            logger.exception("Failed to broadcast task event")
