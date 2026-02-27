"""Workspace schemas."""

from datetime import datetime

from pydantic import BaseModel


class WorkspaceEnvVar(BaseModel):
    key: str
    value: str | None = None  # for raw source
    credential_id: int | None = None  # for credential source
    credential_field: str | None = None  # e.g. "api_key", "base_url"
    source: str = "raw"  # "raw" or "credential"


class WorkspaceIn(BaseModel):
    name: str
    path: str | None = None
    allow_network: bool = False
    env_vars: list[WorkspaceEnvVar] | None = None


class WorkspaceUpdate(BaseModel):
    allow_network: bool | None = None
    env_vars: list[WorkspaceEnvVar] | None = None


class WorkspaceOut(BaseModel):
    id: int
    name: str
    path: str
    allow_network: bool
    env_vars: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}
