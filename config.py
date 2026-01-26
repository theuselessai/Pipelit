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
    AICHAT_MODEL: str = os.getenv("AICHAT_MODEL", "venice:glm-4.7")


config = Config()
