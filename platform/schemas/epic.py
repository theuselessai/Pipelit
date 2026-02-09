"""Epic and Task Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── Epic schemas ───────────────────────────────────────────────────────────────

class EpicCreate(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = []
    priority: int = 2
    budget_tokens: int | None = None
    budget_usd: float | None = None
    workflow_id: int | None = None


class EpicUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: Literal[
        "planning", "active", "paused", "completed", "failed", "cancelled"
    ] | None = None
    priority: int | None = None
    budget_tokens: int | None = None
    budget_usd: float | None = None
    result_summary: str | None = None


class EpicOut(BaseModel):
    id: str
    title: str
    description: str = ""
    tags: list[str] = []
    created_by_node_id: str | None = None
    workflow_id: int | None = None
    user_profile_id: int | None = None
    status: str = "planning"
    priority: int = 2
    budget_tokens: int | None = None
    budget_usd: float | None = None
    spent_tokens: int = 0
    spent_usd: float = 0.0
    agent_overhead_tokens: int = 0
    agent_overhead_usd: float = 0.0
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    result_summary: str | None = None

    model_config = {"from_attributes": True}


# ── Task schemas ───────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    epic_id: str
    title: str
    description: str = ""
    tags: list[str] = []
    depends_on: list[str] = []
    priority: int | None = None
    workflow_slug: str | None = None
    estimated_tokens: int | None = None
    max_retries: int = 2
    requirements: dict | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    status: Literal[
        "pending", "blocked", "running", "completed", "failed", "cancelled"
    ] | None = None
    priority: int | None = None
    workflow_slug: str | None = None
    execution_id: str | None = None
    result_summary: str | None = None
    error_message: str | None = None
    notes: list | None = None


class TaskOut(BaseModel):
    id: str
    epic_id: str
    title: str
    description: str = ""
    tags: list[str] = []
    created_by_node_id: str | None = None
    status: str = "pending"
    priority: int = 2
    workflow_id: int | None = None
    workflow_slug: str | None = None
    execution_id: str | None = None
    workflow_source: str = "inline"
    depends_on: list[str] = []
    requirements: dict | None = None
    estimated_tokens: int | None = None
    actual_tokens: int = 0
    actual_usd: float = 0.0
    llm_calls: int = 0
    tool_invocations: int = 0
    duration_ms: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_summary: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    notes: list = []

    model_config = {"from_attributes": True}


# ── Batch delete schemas ──────────────────────────────────────────────────────

class BatchDeleteEpicsIn(BaseModel):
    epic_ids: list[str]


class BatchDeleteTasksIn(BaseModel):
    task_ids: list[str]
