"""Session management service."""
import logging

from app.config import settings
from app.db.repository import ConversationRepository, get_repository
from app.services.llm import (
    LLMService,
    get_compress_threshold,
    strip_thinking_tags,
)
from app.services.tokens import count_tokens

logger = logging.getLogger(__name__)


class SessionService:
    """Session management service for processing chat messages."""

    def __init__(
        self,
        repository: ConversationRepository | None = None,
        llm_service: LLMService | None = None,
    ):
        """Initialize with optional dependencies."""
        self.repository = repository or get_repository()
        self.llm = llm_service or LLMService()

    def get_conversation(self, user_id: int) -> list[dict]:
        """Get conversation for a user."""
        return self.repository.get_conversation(user_id)

    def clear_conversation(self, user_id: int) -> None:
        """Clear conversation for a user."""
        self.repository.clear_conversation(user_id)

    def get_stats(self, user_id: int) -> dict:
        """Get conversation stats for a user."""
        return self.repository.get_stats(user_id)

    def compress_conversation(self, messages: list[dict]) -> list[dict]:
        """Compress conversation by summarizing old messages."""
        if len(messages) <= settings.KEEP_RECENT_MESSAGES:
            return messages

        # Separate system messages and conversation
        system_msgs = [m for m in messages if m["role"] == "system"]
        conversation = [m for m in messages if m["role"] != "system"]

        # Keep recent messages
        recent = conversation[-settings.KEEP_RECENT_MESSAGES :]
        old = conversation[: -settings.KEEP_RECENT_MESSAGES]

        if not old:
            return messages

        # Format old messages for summarization
        old_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in old
        )

        try:
            summary = self.llm.summarize(old_text)
            logger.info(f"Compressed {len(old)} messages into summary")

            # Rebuild conversation with summary
            return system_msgs + [
                {
                    "role": "system",
                    "content": f"Previous conversation summary:\n{summary}",
                }
            ] + recent

        except Exception as e:
            logger.error(f"Compression failed: {e}")
            # Fallback: just keep recent messages
            return system_msgs + recent

    def process_message(self, user_id: int, user_message: str) -> str:
        """
        Process a user message with session management.

        This is the main sync method used by RQ workers.
        """
        # Load existing conversation
        messages = self.repository.get_conversation(user_id)

        # Add user message
        messages.append({"role": "user", "content": user_message})

        # Check if compression is needed
        token_count = count_tokens(messages)
        threshold = get_compress_threshold()

        if token_count > threshold:
            logger.info(
                f"Token count {token_count} exceeds threshold {threshold}, "
                "compressing..."
            )
            messages = self.compress_conversation(messages)
            token_count = count_tokens(messages)

        # Send to LLM
        try:
            assistant_message = self.llm.chat(messages)

            # Strip thinking tags for display
            display_message = strip_thinking_tags(assistant_message)

            # Store full message (with thinking) for context continuity
            messages.append({"role": "assistant", "content": assistant_message})
            token_count = count_tokens(messages)

            # Save conversation
            self.repository.save_conversation(user_id, messages, token_count)

            return display_message

        except Exception as e:
            # Save the user message so it's not lost
            self.repository.save_conversation(
                user_id, messages, count_tokens(messages)
            )
            logger.error(f"Error processing message for user {user_id}: {e}")
            raise

# Convenience functions
_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    """Get or create session service instance."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
