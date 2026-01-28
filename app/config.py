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

    # LLM Configuration
    LLM_PROVIDER: str = "openai_compatible"  # openai, anthropic, openai_compatible
    LLM_MODEL: str = "zai-org-glm-4.7"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "http://127.0.0.1:8000/v1"  # For openai_compatible
    LLM_TEMPERATURE: float = 0.7

    # Optional: use a cheaper/faster model for categorization
    CATEGORIZER_MODEL: str = ""  # Falls back to LLM_MODEL if empty

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

    # Gateway settings
    GATEWAY_ENABLED: bool = True
    CONFIRMATION_TIMEOUT_MINUTES: int = 5
    CHROME_PROFILE_PATH: str = "~/.config/agent-chrome-profile"
    BROWSER_HEADLESS: bool = True

    # Optional API
    API_ENABLED: bool = False
    API_PORT: int = 8080

    # SearXNG (for web search)
    SEARXNG_BASE_URL: str = "http://localhost:8888"

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

    @property
    def categorizer_model(self) -> str:
        """Get categorizer model, falling back to main model."""
        return self.CATEGORIZER_MODEL or self.LLM_MODEL


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience alias
settings = get_settings()
