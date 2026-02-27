"""Workspace CRUD + reset-rootfs endpoints."""

from __future__ import annotations

import logging
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from config import get_pipelit_dir
from database import get_db
from models.user import UserProfile
from models.workspace import Workspace
from schemas.workspace import WorkspaceIn, WorkspaceOut, WorkspaceUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def list_workspaces(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    total = db.query(Workspace).count()
    items = db.query(Workspace).order_by(Workspace.id).offset(offset).limit(limit).all()
    return {"items": [WorkspaceOut.model_validate(w).model_dump() for w in items], "total": total}


@router.post("/", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    payload: WorkspaceIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    # Check for duplicate name
    existing = db.query(Workspace).filter(Workspace.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Workspace with this name already exists.")

    # Auto-derive path if not provided
    path = payload.path or str(get_pipelit_dir() / "workspaces" / payload.name)

    ws = Workspace(
        name=payload.name,
        path=path,
        allow_network=payload.allow_network,
        user_profile_id=profile.id,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)

    # Create workspace directory and persistent temp dir
    os.makedirs(ws.path, exist_ok=True)
    os.makedirs(os.path.join(ws.path, ".tmp"), exist_ok=True)

    return ws


@router.get("/{workspace_id}/", response_model=WorkspaceOut)
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return ws


@router.patch("/{workspace_id}/", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    if payload.name is not None:
        # Check for duplicate name
        dup = db.query(Workspace).filter(Workspace.name == payload.name, Workspace.id != workspace_id).first()
        if dup:
            raise HTTPException(status_code=409, detail="Workspace with this name already exists.")
        ws.name = payload.name
    if payload.allow_network is not None:
        ws.allow_network = payload.allow_network

    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}/", status_code=204)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if ws.name == "default":
        raise HTTPException(status_code=403, detail="Cannot delete the default workspace.")
    db.delete(ws)
    db.commit()


class BatchDeleteWorkspacesIn(BaseModel):
    ids: list[int]


@router.post("/batch-delete/", status_code=204)
def batch_delete_workspaces(
    payload: BatchDeleteWorkspacesIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    workspaces = db.query(Workspace).filter(Workspace.id.in_(payload.ids)).all()
    for ws in workspaces:
        if ws.name == "default":
            continue  # skip default workspace
        db.delete(ws)
    db.commit()


@router.post("/{workspace_id}/reset-rootfs/", status_code=200)
def reset_rootfs(
    workspace_id: int,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    rootfs_path = os.path.join(ws.path, ".rootfs")
    shutil.rmtree(rootfs_path, ignore_errors=True)
    logger.info("Reset rootfs for workspace %s at %s", ws.name, rootfs_path)
    return {"ok": True, "message": f"Rootfs cleared for workspace '{ws.name}'. Will be re-created on next execution."}
