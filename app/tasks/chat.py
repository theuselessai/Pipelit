"""Chat processing background tasks for RQ workers."""
import logging

from app.services.sessions import SessionService
from app.services.telegram import send_message, send_typing

logger = logging.getLogger(__name__)


def process_chat_message(
    chat_id: int,
    user_id: int,
    message: str,
    message_id: int,
) -> dict:
    """
    RQ task for processing chat messages.

    Runs in worker process (sync).
    """
    session_service = SessionService()

    # Send typing indicator
    try:
        send_typing(chat_id)
    except Exception as e:
        logger.warning(f"Failed to send typing indicator: {e}")

    # Process message
    try:
        response = session_service.process_message(user_id, message)

        # Send response (split if too long)
        max_len = 4096
        if len(response) <= max_len:
            send_message(chat_id, response, message_id)
        else:
            for i in range(0, len(response), max_len):
                chunk = response[i : i + max_len]
                reply_id = message_id if i == 0 else None
                send_message(chat_id, chunk, reply_id)

        return {
            "status": "success",
            "response_length": len(response),
            "user_id": user_id,
        }

    except Exception as e:
        logger.error(f"Task failed for user {user_id}: {e}")
        try:
            send_message(
                chat_id,
                f"Sorry, an error occurred: {str(e)}",
                message_id,
            )
        except Exception:
            pass
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
        }


def compress_conversation_task(user_id: int) -> dict:
    """
    RQ task for compressing a user's conversation.

    Typically run on low priority queue.
    """
    session_service = SessionService()

    try:
        messages = session_service.get_conversation(user_id)
        if not messages:
            return {"status": "skipped", "reason": "no messages"}

        compressed = session_service.compress_conversation(messages)

        # Save compressed conversation
        from app.services.tokens import count_tokens

        token_count = count_tokens(compressed)
        session_service.repository.save_conversation(
            user_id, compressed, token_count
        )

        return {
            "status": "success",
            "original_messages": len(messages),
            "compressed_messages": len(compressed),
            "token_count": token_count,
        }

    except Exception as e:
        logger.error(f"Compression task failed for user {user_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
        }
