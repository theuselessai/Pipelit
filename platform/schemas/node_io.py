"""Core Node I/O schemas for standardised node execution."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeError(BaseModel):
    code: str = ""
    message: str = ""
    details: dict[str, Any] = {}
    recoverable: bool = False
    node_id: str = ""


class NodeResult(BaseModel):
    status: NodeStatus = NodeStatus.SUCCESS
    data: dict[str, Any] = {}
    error: NodeError | None = None
    metadata: dict[str, Any] = {}
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def success(cls, data: dict[str, Any] | None = None, **kwargs: Any) -> NodeResult:
        return cls(status=NodeStatus.SUCCESS, data=data or {}, **kwargs)

    @classmethod
    def failed(cls, error_code: str, message: str, node_id: str = "", recoverable: bool = False, **kwargs: Any) -> NodeResult:
        return cls(
            status=NodeStatus.FAILED,
            error=NodeError(code=error_code, message=message, node_id=node_id, recoverable=recoverable),
            **kwargs,
        )

    @classmethod
    def skipped(cls, reason: str = "", **kwargs: Any) -> NodeResult:
        return cls(status=NodeStatus.SKIPPED, metadata={"skip_reason": reason}, **kwargs)


class NodeInput(BaseModel):
    trigger_payload: dict[str, Any] = {}
    upstream_results: dict[str, NodeResult] = {}
    config: dict[str, Any] = {}
    execution_id: str = ""
    workflow_id: int = 0
    node_id: str = ""
