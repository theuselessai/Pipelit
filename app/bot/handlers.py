"""Telegram command and message handlers."""
import asyncio
import logging

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.services.aichat import (
    AsyncAIChatService,
    get_compress_threshold,
    get_context_window,
    strip_thinking_tags,
)
from app.services.sessions import SessionService
from app.services.tokens import count_tokens
from app.tasks.chat import process_chat_message
from app.tasks.queues import default_queue

logger = logging.getLogger(__name__)

# Session service for sync operations (via asyncio.to_thread)
_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    """Get or create session service."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service


def is_allowed(user_id: int) -> bool:
    """Check if user is whitelisted."""
    allowed = settings.allowed_user_ids_list
    if not allowed:
        return True  # No whitelist = allow all (for testing)
    return user_id in allowed


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text(
        "Hello! I'm connected to AIChat + Venice.ai.\n\n"
        "Commands:\n"
        "/clear - Clear conversation history\n"
        "/stats - Show session statistics\n"
        "/context - Show context window usage\n\n"
        "Just send me a message to chat!"
    )


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command - clear conversation history."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    session_service = get_session_service()
    await asyncio.to_thread(session_service.clear_conversation, user_id)
    await update.message.reply_text("Conversation cleared.")


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show session statistics."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    session_service = get_session_service()
    stats_data = await asyncio.to_thread(session_service.get_stats, user_id)

    if stats_data["message_count"] == 0:
        await update.message.reply_text("No conversation history yet.")
        return

    text = (
        f"Session Statistics:\n"
        f"- Messages: {stats_data['message_count']}\n"
        f"- Tokens: {stats_data['token_count']:,}\n"
        f"- Started: {stats_data['created_at']}\n"
        f"- Updated: {stats_data['updated_at']}"
    )
    await update.message.reply_text(text)


async def context_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /context command - show context window usage."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    session_service = get_session_service()
    stats_data = await asyncio.to_thread(session_service.get_stats, user_id)

    context_window = get_context_window(settings.AICHAT_MODEL)
    threshold = get_compress_threshold(settings.AICHAT_MODEL)
    token_count = stats_data["token_count"]

    usage_pct = (token_count / context_window * 100) if context_window > 0 else 0
    threshold_pct = (token_count / threshold * 100) if threshold > 0 else 0

    text = (
        f"Context Window Usage:\n"
        f"- Model: {settings.AICHAT_MODEL}\n"
        f"- Context window: {context_window:,} tokens\n"
        f"- Compress threshold: {threshold:,} tokens ({settings.COMPRESS_RATIO:.0%})\n"
        f"- Current usage: {token_count:,} tokens ({usage_pct:.1f}%)\n"
        f"- Until compression: {threshold_pct:.1f}%"
    )
    await update.message.reply_text(text)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        logger.warning(f"Unauthorized: {user_id}")
        await update.message.reply_text("Access denied.")
        return

    user_message = update.message.text
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    logger.info(f"[{user_id}] {user_message[:50]}...")

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    session_service = get_session_service()

    # Check if we should use background processing
    should_background = await asyncio.to_thread(
        session_service.should_use_background, user_id, user_message
    )

    if should_background:
        # Enqueue to RQ for background processing
        job = default_queue.enqueue(
            process_chat_message,
            chat_id=chat_id,
            user_id=user_id,
            message=user_message,
            message_id=message_id,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued job {job.id} for user {user_id}")
        # Don't send "processing" message - just let the worker respond
        return

    # Process synchronously via thread pool for small contexts
    try:
        response = await asyncio.to_thread(
            session_service.process_message, user_id, user_message
        )

        # Send response (split if too long)
        max_len = 4096
        if len(response) <= max_len:
            await update.message.reply_text(response)
        else:
            for i in range(0, len(response), max_len):
                await update.message.reply_text(response[i : i + max_len])

    except httpx.TimeoutException:
        await update.message.reply_text(
            "Request timed out. The server took too long to respond.\n"
            "Your message was saved - you can try again or use /clear to start fresh."
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        await update.message.reply_text(f"API error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Error: {str(e)}")
