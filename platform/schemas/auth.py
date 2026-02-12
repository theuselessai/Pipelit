"""Auth schemas."""

from datetime import datetime

from pydantic import BaseModel


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    key: str
    requires_mfa: bool = False


class SetupRequest(BaseModel):
    username: str
    password: str


class SetupStatusResponse(BaseModel):
    needs_setup: bool


class MeResponse(BaseModel):
    username: str
    mfa_enabled: bool = False


class AgentUserResponse(BaseModel):
    id: int
    username: str
    purpose: str
    api_key_preview: str
    created_at: datetime
    created_by: str | None


# ── MFA schemas ───────────────────────────────────────────────────────────────


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MFAVerifyRequest(BaseModel):
    code: str


class MFADisableRequest(BaseModel):
    code: str


class MFALoginVerifyRequest(BaseModel):
    username: str
    code: str


class MFAStatusResponse(BaseModel):
    mfa_enabled: bool
