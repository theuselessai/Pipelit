"""Workspace schemas."""

from datetime import datetime

from pydantic import BaseModel


class WorkspaceIn(BaseModel):
    name: str
    path: str | None = None
    allow_network: bool = False


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    allow_network: bool | None = None


class WorkspaceOut(BaseModel):
    id: int
    name: str
    path: str
    allow_network: bool
    created_at: datetime

    model_config = {"from_attributes": True}
