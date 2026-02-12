"""ScheduledJob Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class ScheduledJobCreate(BaseModel):
    name: str
    description: str = ""
    workflow_id: int
    trigger_node_id: str | None = None
    interval_seconds: int
    total_repeats: int = 0
    max_retries: int = 3
    timeout_seconds: int = 600
    trigger_payload: dict | None = None

    @field_validator("interval_seconds")
    @classmethod
    def interval_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval_seconds must be >= 1")
        return v

    @field_validator("total_repeats")
    @classmethod
    def total_repeats_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("total_repeats must be >= 0")
        return v

    @field_validator("max_retries")
    @classmethod
    def retries_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retries must be >= 0")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("timeout_seconds must be >= 1")
        return v


class ScheduledJobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    interval_seconds: int | None = None
    total_repeats: int | None = None
    max_retries: int | None = None
    timeout_seconds: int | None = None
    trigger_payload: dict | None = None

    @field_validator("interval_seconds")
    @classmethod
    def interval_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("interval_seconds must be >= 1")
        return v

    @field_validator("total_repeats")
    @classmethod
    def total_repeats_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("total_repeats must be >= 0")
        return v

    @field_validator("max_retries")
    @classmethod
    def retries_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("max_retries must be >= 0")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def timeout_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("timeout_seconds must be >= 1")
        return v


class ScheduledJobOut(BaseModel):
    id: str
    name: str
    description: str = ""
    workflow_id: int
    trigger_node_id: str | None = None
    user_profile_id: int
    interval_seconds: int
    total_repeats: int = 0
    max_retries: int = 3
    timeout_seconds: int = 600
    trigger_payload: dict | None = None
    status: str = "active"
    current_repeat: int = 0
    current_retry: int = 0
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
    error_count: int = 0
    last_error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class BatchDeleteSchedulesIn(BaseModel):
    schedule_ids: list[str]
