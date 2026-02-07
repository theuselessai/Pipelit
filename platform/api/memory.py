"""Memory API endpoints — facts, episodes, procedures, users, checkpoints."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.memory import MemoryEpisode, MemoryFact, MemoryProcedure, MemoryUser
from models.user import UserProfile
from schemas.memory import CheckpointOut, EpisodeOut, FactOut, ProcedureOut, UserOut

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Facts ─────────────────────────────────────────────────────────────────────


@router.get("/facts/")
def list_facts(
    scope: str | None = Query(None),
    fact_type: str | None = Query(None),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryFact)
    if scope:
        stmt = stmt.where(MemoryFact.scope == scope)
    if fact_type:
        stmt = stmt.where(MemoryFact.fact_type == fact_type)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar() or 0
    stmt = stmt.order_by(MemoryFact.updated_at.desc()).offset(offset).limit(limit)
    items = list(db.execute(stmt).scalars().all())
    return {"items": [FactOut.model_validate(i) for i in items], "total": total}


class BatchDeleteFactsIn(BaseModel):
    ids: list[str]


@router.post("/facts/batch-delete/", status_code=204)
def batch_delete_facts(
    payload: BatchDeleteFactsIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    db.query(MemoryFact).filter(MemoryFact.id.in_(payload.ids)).delete(synchronize_session=False)
    db.commit()


# ── Episodes ──────────────────────────────────────────────────────────────────


@router.get("/episodes/")
def list_episodes(
    agent_id: str | None = Query(None),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryEpisode)
    if agent_id:
        stmt = stmt.where(MemoryEpisode.agent_id == agent_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar() or 0
    stmt = stmt.order_by(MemoryEpisode.started_at.desc()).offset(offset).limit(limit)
    items = list(db.execute(stmt).scalars().all())
    return {"items": [EpisodeOut.model_validate(i) for i in items], "total": total}


class BatchDeleteEpisodesIn(BaseModel):
    ids: list[str]


@router.post("/episodes/batch-delete/", status_code=204)
def batch_delete_episodes(
    payload: BatchDeleteEpisodesIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    db.query(MemoryEpisode).filter(MemoryEpisode.id.in_(payload.ids)).delete(synchronize_session=False)
    db.commit()


# ── Procedures ────────────────────────────────────────────────────────────────


@router.get("/procedures/")
def list_procedures(
    agent_id: str | None = Query(None),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryProcedure)
    if agent_id:
        stmt = stmt.where(MemoryProcedure.agent_id == agent_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar() or 0
    stmt = stmt.order_by(MemoryProcedure.created_at.desc()).offset(offset).limit(limit)
    items = list(db.execute(stmt).scalars().all())
    return {"items": [ProcedureOut.model_validate(i) for i in items], "total": total}


class BatchDeleteProceduresIn(BaseModel):
    ids: list[str]


@router.post("/procedures/batch-delete/", status_code=204)
def batch_delete_procedures(
    payload: BatchDeleteProceduresIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    db.query(MemoryProcedure).filter(MemoryProcedure.id.in_(payload.ids)).delete(synchronize_session=False)
    db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/users/")
def list_users(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryUser)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar() or 0
    stmt = stmt.order_by(MemoryUser.last_seen_at.desc()).offset(offset).limit(limit)
    items = list(db.execute(stmt).scalars().all())
    return {"items": [UserOut.model_validate(i) for i in items], "total": total}


class BatchDeleteUsersIn(BaseModel):
    ids: list[str]


@router.post("/users/batch-delete/", status_code=204)
def batch_delete_users(
    payload: BatchDeleteUsersIn,
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    if not payload.ids:
        return
    db.query(MemoryUser).filter(MemoryUser.id.in_(payload.ids)).delete(synchronize_session=False)
    db.commit()


# ── Checkpoints ───────────────────────────────────────────────────────────────


@router.get("/checkpoints/")
def list_checkpoints(
    thread_id: str | None = Query(None),
    limit: int = 50,
    offset: int = 0,
    profile: UserProfile = Depends(get_current_user),
):
    from components.agent import _get_checkpointer

    checkpointer = _get_checkpointer()
    conn = checkpointer.conn
    cursor = conn.cursor()

    # Count total
    if thread_id:
        cursor.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM checkpoints")
    total = cursor.fetchone()[0]

    # Fetch page
    query = """
        SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
               type, length(checkpoint) as blob_size, metadata
        FROM checkpoints
    """
    params: list = []
    if thread_id:
        query += " WHERE thread_id = ?"
        params.append(thread_id)
    query += " ORDER BY checkpoint_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()

    items = []
    for row in rows:
        step = None
        source = None
        metadata_raw = row[6]
        if metadata_raw:
            try:
                meta = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
                step = meta.get("step")
                source = meta.get("source")
            except (json.JSONDecodeError, TypeError):
                pass
        items.append(CheckpointOut(
            thread_id=row[0],
            checkpoint_ns=row[1] or "",
            checkpoint_id=row[2],
            parent_checkpoint_id=row[3],
            step=step,
            source=source,
            blob_size=row[5] or 0,
        ))

    return {"items": [i.model_dump() for i in items], "total": total}


class BatchDeleteCheckpointsIn(BaseModel):
    thread_ids: list[str] | None = None
    checkpoint_ids: list[str] | None = None


@router.post("/checkpoints/batch-delete/", status_code=204)
def batch_delete_checkpoints(
    payload: BatchDeleteCheckpointsIn,
    profile: UserProfile = Depends(get_current_user),
):
    from components.agent import _get_checkpointer

    checkpointer = _get_checkpointer()
    conn = checkpointer.conn

    if payload.thread_ids:
        placeholders = ",".join("?" for _ in payload.thread_ids)
        conn.execute(f"DELETE FROM writes WHERE thread_id IN ({placeholders})", payload.thread_ids)
        conn.execute(f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})", payload.thread_ids)
        conn.commit()

    if payload.checkpoint_ids:
        placeholders = ",".join("?" for _ in payload.checkpoint_ids)
        conn.execute(f"DELETE FROM writes WHERE checkpoint_id IN ({placeholders})", payload.checkpoint_ids)
        conn.execute(f"DELETE FROM checkpoints WHERE checkpoint_id IN ({placeholders})", payload.checkpoint_ids)
        conn.commit()
