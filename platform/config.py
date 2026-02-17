"""Pydantic settings loaded from .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent

# Load .env from the repository root (one level above platform/)
load_dotenv(BASE_DIR.parent / ".env")


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False
    ALLOWED_HOSTS: str = "localhost"

    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

    REDIS_URL: str = "redis://localhost:6379/0"

    FIELD_ENCRYPTION_KEY: str = ""

    CORS_ALLOW_ALL_ORIGINS: bool = True

    ZOMBIE_EXECUTION_THRESHOLD_SECONDS: int = 900  # 15 min

    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = ""                    # empty = console only; set to e.g. "logs/pipelit.log"
    LOG_MAX_BYTES: int = 10_485_760       # 10 MB
    LOG_BACKUP_COUNT: int = 5

    model_config = ConfigDict(
        env_file=str(BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
