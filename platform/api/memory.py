"""Memory read-only API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models.memory import MemoryEpisode, MemoryFact, MemoryProcedure, MemoryUser
from models.user import UserProfile
from schemas.memory import EpisodeOut, FactOut, ProcedureOut, UserOut

router = APIRouter()


@router.get("/facts/", response_model=list[FactOut])
def list_facts(
    scope: str | None = Query(None),
    fact_type: str | None = Query(None),
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryFact).order_by(MemoryFact.updated_at.desc())
    if scope:
        stmt = stmt.where(MemoryFact.scope == scope)
    if fact_type:
        stmt = stmt.where(MemoryFact.fact_type == fact_type)
    return list(db.execute(stmt).scalars().all())


@router.get("/episodes/", response_model=list[EpisodeOut])
def list_episodes(
    agent_id: str | None = Query(None),
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryEpisode).order_by(MemoryEpisode.started_at.desc())
    if agent_id:
        stmt = stmt.where(MemoryEpisode.agent_id == agent_id)
    return list(db.execute(stmt).scalars().all())


@router.get("/procedures/", response_model=list[ProcedureOut])
def list_procedures(
    agent_id: str | None = Query(None),
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryProcedure).order_by(MemoryProcedure.created_at.desc())
    if agent_id:
        stmt = stmt.where(MemoryProcedure.agent_id == agent_id)
    return list(db.execute(stmt).scalars().all())


@router.get("/users/", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    profile: UserProfile = Depends(get_current_user),
):
    stmt = select(MemoryUser).order_by(MemoryUser.last_seen_at.desc())
    return list(db.execute(stmt).scalars().all())
