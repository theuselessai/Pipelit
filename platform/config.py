"""Pydantic settings loaded from .env, with conf.json overlay."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# conf.json: platform runtime config (separate from .env secrets)
# ---------------------------------------------------------------------------


def get_pipelit_dir() -> Path:
    """Resolve the pipelit data directory. PIPELIT_DIR env var or ~/.config/pipelit."""
    d = os.environ.get("PIPELIT_DIR", "")
    return Path(d).expanduser() if d else Path.home() / ".config" / "pipelit"


class PipelitConfig(BaseModel):
    setup_completed: bool = False
    pipelit_dir: str = ""
    sandbox_mode: str = "auto"  # auto | container | bwrap
    database_url: str = ""
    redis_url: str = ""
    log_level: str = ""
    log_file: str = ""
    platform_base_url: str = ""
    cors_allow_all_origins: bool | None = None  # None = use Settings default
    zombie_execution_threshold_seconds: int | None = None
    detected_environment: dict = {}


_logger = logging.getLogger(__name__)


def load_conf() -> PipelitConfig:
    """Load conf.json from the pipelit data directory."""
    conf_path = get_pipelit_dir() / "conf.json"
    if conf_path.exists():
        try:
            return PipelitConfig.model_validate_json(conf_path.read_text())
        except Exception:
            _logger.warning("Failed to parse %s, using defaults", conf_path, exc_info=True)
    return PipelitConfig()


def save_conf(config: PipelitConfig) -> None:
    """Save conf.json to the pipelit data directory."""
    pipelit_dir = get_pipelit_dir()
    pipelit_dir.mkdir(parents=True, exist_ok=True)
    (pipelit_dir / "conf.json").write_text(config.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Secret auto-generation
# ---------------------------------------------------------------------------


def _ensure_secrets(env_file: Path) -> None:
    """Generate FIELD_ENCRYPTION_KEY and SECRET_KEY if missing, append to .env."""
    from cryptography.fernet import Fernet
    import secrets as _secrets

    lines_to_append: list[str] = []

    if not os.environ.get("FIELD_ENCRYPTION_KEY"):
        key = Fernet.generate_key().decode()
        os.environ["FIELD_ENCRYPTION_KEY"] = key
        lines_to_append.append(f"FIELD_ENCRYPTION_KEY={key}")

    if not os.environ.get("SECRET_KEY"):
        key = _secrets.token_urlsafe(32)
        os.environ["SECRET_KEY"] = key
        lines_to_append.append(f"SECRET_KEY={key}")

    if lines_to_append:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        with open(env_file, "a") as f:
            f.write("\n" + "\n".join(lines_to_append) + "\n")


# ---------------------------------------------------------------------------
# Bootstrap: load .env, generate secrets, load conf.json
# ---------------------------------------------------------------------------

_env_file = BASE_DIR.parent / ".env"
load_dotenv(_env_file)
_ensure_secrets(_env_file)
_conf = load_conf()

# ---------------------------------------------------------------------------
# Settings (pydantic-settings): .env / env vars override conf.json defaults
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False

    DATABASE_URL: str = _conf.database_url or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    REDIS_URL: str = _conf.redis_url or "redis://localhost:6379/0"

    FIELD_ENCRYPTION_KEY: str = ""

    CORS_ALLOW_ALL_ORIGINS: bool = (
        _conf.cors_allow_all_origins if _conf.cors_allow_all_origins is not None else True
    )

    ZOMBIE_EXECUTION_THRESHOLD_SECONDS: int = (
        _conf.zombie_execution_threshold_seconds if _conf.zombie_execution_threshold_seconds is not None else 900
    )

    LOG_LEVEL: str = _conf.log_level or "INFO"
    LOG_FILE: str = _conf.log_file or ""
    LOG_MAX_BYTES: int = 10_485_760
    LOG_BACKUP_COUNT: int = 5

    SANDBOX_MODE: str = _conf.sandbox_mode or "auto"
    PLATFORM_BASE_URL: str = _conf.platform_base_url or "http://localhost:8000"

    SKILLS_DIR: str = ""  # default: ~/.config/pipelit/skills/ (resolved at runtime)
    WORKSPACE_DIR: str = ""  # default: ~/.config/pipelit/workspaces/default (resolved at runtime)

    model_config = ConfigDict(
        env_file=str(BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
