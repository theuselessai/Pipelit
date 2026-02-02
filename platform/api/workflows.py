"""Workflow CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.user import UserProfile
from models.workflow import Workflow, WorkflowCollaborator
from schemas.workflow import WorkflowDetailOut, WorkflowIn, WorkflowOut, WorkflowUpdate
from api._helpers import get_workflow, serialize_workflow, serialize_workflow_detail
from ws.broadcast import broadcast

router = APIRouter()


@router.get("/", response_model=list[WorkflowOut])
def list_workflows(
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    workflows = (
        db.query(Workflow)
        .filter(
            Workflow.deleted_at.is_(None),
            or_(
                Workflow.owner_id == profile.id,
                Workflow.id.in_(
                    db.query(WorkflowCollaborator.workflow_id)
                    .filter(WorkflowCollaborator.user_profile_id == profile.id)
                ),
            ),
        )
        .all()
    )
    return [serialize_workflow(wf, db) for wf in workflows]


@router.post("/", response_model=WorkflowOut, status_code=201)
def create_workflow(
    payload: WorkflowIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = Workflow(owner_id=profile.id, **payload.model_dump())
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return serialize_workflow(wf, db)


@router.get("/{slug}/", response_model=WorkflowDetailOut)
def get_workflow_detail(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    return serialize_workflow_detail(wf, db)


@router.patch("/{slug}/", response_model=WorkflowOut)
def update_workflow(
    slug: str,
    payload: WorkflowUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    for attr, value in payload.model_dump(exclude_unset=True).items():
        setattr(wf, attr, value)
    db.commit()
    db.refresh(wf)
    result = serialize_workflow(wf, db)
    broadcast(f"workflow:{slug}", "workflow_updated", result)
    return result


@router.post("/{slug}/validate/")
def validate_workflow(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    from validation.edges import EdgeValidator
    errors = EdgeValidator.validate_workflow_edges(wf.id, db)
    errors += EdgeValidator.validate_required_inputs(wf.id, db)
    return {"valid": len(errors) == 0, "errors": errors}


@router.delete("/{slug}/", status_code=204)
def delete_workflow(
    slug: str,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    wf = get_workflow(slug, profile, db)
    wf.soft_delete()
    db.commit()
