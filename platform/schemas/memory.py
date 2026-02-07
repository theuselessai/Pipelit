"""Pydantic response schemas for memory endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int


class FactOut(BaseModel):
    id: str
    scope: str
    agent_id: str | None
    user_id: str | None
    key: str
    value: Any
    fact_type: str
    confidence: float
    times_confirmed: int
    access_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EpisodeOut(BaseModel):
    id: str
    agent_id: str
    user_id: str | None
    trigger_type: str
    success: bool
    error_code: str | None
    summary: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProcedureOut(BaseModel):
    id: str
    agent_id: str
    name: str
    description: str
    procedure_type: str
    times_used: int
    times_succeeded: int
    times_failed: int
    success_rate: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: str
    canonical_id: str
    display_name: str | None
    telegram_id: str | None
    email: str | None
    total_conversations: int
    last_seen_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class CheckpointOut(BaseModel):
    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str
    parent_checkpoint_id: str | None
    step: int | None
    source: str | None
    blob_size: int
