"""Workflow CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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


class ValidateDslIn(BaseModel):
    yaml_str: str


@router.post("/validate-dsl/")
def validate_dsl_endpoint(
    payload: ValidateDslIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    from services.dsl_compiler import validate_dsl
    return validate_dsl(payload.yaml_str, db)


@router.get("/node-types/")
def list_node_types():
    from schemas import node_type_defs  # noqa: F401 — triggers registration
    from schemas.node_types import NODE_TYPE_REGISTRY
    return {ct: spec.model_dump() for ct, spec in NODE_TYPE_REGISTRY.items()}


@router.get("/")
def list_workflows(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    base = (
        db.query(Workflow)
        .filter(
            or_(
                Workflow.owner_id == profile.id,
                Workflow.id.in_(
                    db.query(WorkflowCollaborator.workflow_id)
                    .filter(WorkflowCollaborator.user_profile_id == profile.id)
                ),
            ),
        )
    )
    total = base.count()
    workflows = base.offset(offset).limit(limit).all()
    return {"items": [serialize_workflow(wf, db) for wf in workflows], "total": total}


@router.post("/", response_model=WorkflowOut, status_code=201)
def create_workflow(
    payload: WorkflowIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    # Deduplicate slug: if "deep" exists (including soft-deleted), try "deep-1", "deep-2", etc.
    base_slug = payload.slug
    slug = base_slug
    counter = 1
    while db.query(Workflow.id).filter(Workflow.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    data = payload.model_dump()
    data["slug"] = slug
    wf = Workflow(owner_id=profile.id, **data)
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
    db.delete(wf)
    db.commit()


class BatchDeleteWorkflowsIn(BaseModel):
    slugs: list[str]


@router.post("/batch-delete/", status_code=204)
def batch_delete_workflows(
    payload: BatchDeleteWorkflowsIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.slugs:
        return
    workflows = (
        db.query(Workflow)
        .filter(
            Workflow.slug.in_(payload.slugs),
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
    for wf in workflows:
        db.delete(wf)
    db.commit()
