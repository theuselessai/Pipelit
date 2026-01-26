"""Telegram command and message handlers."""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.services.aichat import get_compress_threshold, get_context_window
from app.services.sessions import SessionService
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

    # Enqueue to RQ worker for processing
    job = default_queue.enqueue(
        process_chat_message,
        chat_id=chat_id,
        user_id=user_id,
        message=user_message,
        message_id=message_id,
        job_timeout=settings.JOB_TIMEOUT,
    )
    logger.info(f"Enqueued job {job.id} for user {user_id}")
