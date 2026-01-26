"""Telegram Bot API client - sync version for RQ workers."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Synchronous Telegram API client for RQ workers."""

    def __init__(self):
        """Initialize with bot token."""
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
    ) -> dict:
        """Send a message to a chat."""
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if parse_mode:
            payload["parse_mode"] = parse_mode

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self.base_url}/sendMessage",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        """Send a chat action (e.g., typing indicator)."""
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self.base_url}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
            )
            response.raise_for_status()
            return response.json()

    def send_long_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        max_length: int = 4096,
    ) -> list[dict]:
        """Send a message, splitting if too long."""
        results = []
        for i in range(0, len(text), max_length):
            chunk = text[i : i + max_length]
            # Only reply to the original message for the first chunk
            reply_id = reply_to_message_id if i == 0 else None
            result = self.send_message(chat_id, chunk, reply_id)
            results.append(result)
        return results


# Convenience functions for tasks
_telegram_service: TelegramService | None = None


def get_telegram_service() -> TelegramService:
    """Get or create Telegram service instance."""
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service


def send_message(
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
) -> dict:
    """Send a message (convenience function for tasks)."""
    return get_telegram_service().send_message(chat_id, text, reply_to_message_id)


def send_typing(chat_id: int) -> dict:
    """Send typing indicator (convenience function for tasks)."""
    return get_telegram_service().send_chat_action(chat_id, "typing")
