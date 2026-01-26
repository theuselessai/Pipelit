"""Application configuration using Pydantic settings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    ALLOWED_USER_IDS: str = ""

    # AIChat server
    AICHAT_BASE_URL: str = "http://127.0.0.1:8000"
    AICHAT_MODEL: str = "venice:zai-org-glm-4.7"

    # Venice.ai API (for fetching model context windows)
    VENICE_API_BASE: str = "https://api.venice.ai/api/v1"
    VENICE_API_KEY: str = ""

    # Database
    DB_PATH: str = "sessions.db"

    # Session management
    COMPRESS_RATIO: float = 0.75
    KEEP_RECENT_MESSAGES: int = 6
    DEFAULT_CONTEXT_WINDOW: int = 128000

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Task settings
    JOB_TIMEOUT: int = 300

    # Optional API
    API_ENABLED: bool = False
    API_PORT: int = 8080

    @property
    def allowed_user_ids_list(self) -> list[int]:
        """Parse allowed user IDs into a list of integers."""
        if not self.ALLOWED_USER_IDS:
            return []
        return [
            int(uid.strip())
            for uid in self.ALLOWED_USER_IDS.split(",")
            if uid.strip()
        ]

    @property
    def redis_url(self) -> str:
        """Get Redis URL."""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience alias
settings = get_settings()
