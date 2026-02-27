"""Auth schemas."""

from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    key: str
    requires_mfa: bool = False


# ── Environment / setup wizard schemas ────────────────────────────────────────


class RuntimeInfo(BaseModel):
    available: bool
    version: str | None = None
    path: str | None = None


class ShellToolInfo(BaseModel):
    available: bool
    tier: int = Field(ge=1, le=2)


class NetworkInfo(BaseModel):
    dns: bool
    http: bool


class CapabilitiesInfo(BaseModel):
    runtimes: dict[str, RuntimeInfo]
    shell_tools: dict[str, ShellToolInfo]
    network: NetworkInfo


class GateResult(BaseModel):
    passed: bool
    blocked_reason: str | None = None


class EnvironmentInfo(BaseModel):
    os: str
    arch: str
    container: str | None = None
    bwrap_available: bool
    rootfs_ready: bool
    sandbox_mode: str
    capabilities: CapabilitiesInfo
    tier1_met: bool
    tier2_warnings: list[str]
    gate: GateResult


class RootfsStatusResponse(BaseModel):
    ready: bool
    preparing: bool
    error: str | None = None


class SetupRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=4)
    sandbox_mode: str | None = None
    database_url: str | None = Field(None, min_length=1)
    redis_url: str | None = Field(None, min_length=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    platform_base_url: str | None = Field(None, min_length=1)


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    environment: EnvironmentInfo | None = None


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
    code: str = Field(pattern=r"^\d{6}$")


class MFADisableRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MFALoginVerifyRequest(BaseModel):
    username: str
    code: str = Field(pattern=r"^\d{6}$")


class MFAStatusResponse(BaseModel):
    mfa_enabled: bool
