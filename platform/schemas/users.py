"""User and API key management schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── User schemas ──────────────────────────────────────────────────────────────


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8)
    role: Literal["admin", "normal"] = "normal"
    first_name: str | None = None
    last_name: str | None = None


class UserUpdateIn(BaseModel):
    role: Literal["admin", "normal"] | None = None
    password: str | None = Field(default=None, min_length=8)
    first_name: str | None = None
    last_name: str | None = None


class SelfUpdateIn(BaseModel):
    password: str | None = Field(default=None, min_length=8)
    first_name: str | None = None
    last_name: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    first_name: str
    last_name: str
    created_at: datetime
    mfa_enabled: bool
    key_count: int = 0

    model_config = {"from_attributes": True}


class UserListOut(BaseModel):
    users: list[UserOut]
    total: int


# ── API Key schemas ───────────────────────────────────────────────────────────


class APIKeyCreateIn(BaseModel):
    name: str = Field(max_length=100)
    expires_at: datetime | None = None


class APIKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class APIKeyCreatedOut(APIKeyOut):
    key: str  # full key — shown only at creation
