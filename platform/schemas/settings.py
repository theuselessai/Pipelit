"""Settings API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from schemas.auth import EnvironmentInfo


class PlatformConfigOut(BaseModel):
    """Safe-to-expose conf.json values."""

    pipelit_dir: str
    sandbox_mode: str
    database_url: str
    redis_url: str
    log_level: str
    log_file: str
    platform_base_url: str
    cors_allow_all_origins: bool | None = None
    zombie_execution_threshold_seconds: int | None = None


class SettingsResponse(BaseModel):
    config: PlatformConfigOut
    environment: EnvironmentInfo


class SettingsUpdate(BaseModel):
    """PATCH body — all fields optional."""

    sandbox_mode: str | None = None
    database_url: str | None = None
    redis_url: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    log_file: str | None = None
    platform_base_url: str | None = None
    cors_allow_all_origins: bool | None = None
    zombie_execution_threshold_seconds: int | None = Field(None, ge=0)


class SettingsUpdateResponse(BaseModel):
    config: PlatformConfigOut
    hot_reloaded: list[str]
    restart_required: list[str]
