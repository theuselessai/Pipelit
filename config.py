import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ALLOWED_USER_IDS: list[int] = [
        int(uid.strip())
        for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
        if uid.strip()
    ]
    AICHAT_BASE_URL: str = os.getenv("AICHAT_BASE_URL", "http://127.0.0.1:8000")
    AICHAT_MODEL: str = os.getenv("AICHAT_MODEL", "zai-org-glm-4.7")

    # Venice.ai API (for fetching model context windows)
    VENICE_API_BASE: str = os.getenv("VENICE_API_BASE", "https://api.venice.ai/api/v1")
    VENICE_API_KEY: str = os.getenv("VENICE_API_KEY", "")

    # Session management
    DB_PATH: str = os.getenv("DB_PATH", "sessions.db")
    COMPRESS_RATIO: float = float(os.getenv("COMPRESS_RATIO", "0.75"))
    KEEP_RECENT_MESSAGES: int = int(os.getenv("KEEP_RECENT_MESSAGES", "6"))
    DEFAULT_CONTEXT_WINDOW: int = int(os.getenv("DEFAULT_CONTEXT_WINDOW", "128000"))


config = Config()
