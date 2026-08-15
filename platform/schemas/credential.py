"""Credential schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CredentialTypeStr = Literal["git", "llm", "gateway", "tool"]


class CredentialIn(BaseModel):
    name: str
    credential_type: CredentialTypeStr
    detail: dict | None = None


class CredentialUpdate(BaseModel):
    name: str | None = None
    detail: dict | None = None


class CredentialOut(BaseModel):
    id: int
    name: str
    credential_type: CredentialTypeStr
    detail: str | dict | None = None
    created_at: datetime
    updated_at: datetime
    agentgateway_backend: str | None = None

    model_config = {"from_attributes": True}


class CredentialTestOut(BaseModel):
    ok: bool
    error: str = ""
    detail: str | dict | None = None


class CredentialModelOut(BaseModel):
    id: str
    name: str
