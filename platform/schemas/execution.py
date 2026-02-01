"""Execution schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExecutionOut(BaseModel):
    execution_id: str
    workflow_slug: str
    status: str
    error_message: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExecutionLogOut(BaseModel):
    id: int
    node_id: str
    status: str
    input: Any | None = None
    output: Any | None = None
    error: str = ""
    duration_ms: int = 0
    timestamp: datetime

    model_config = {"from_attributes": True}


class ExecutionDetailOut(ExecutionOut):
    final_output: Any | None = None
    trigger_payload: Any | None = None
    logs: list[ExecutionLogOut] = []


class ChatMessageIn(BaseModel):
    text: str


class ChatMessageOut(BaseModel):
    execution_id: str
    status: str
    response: str
