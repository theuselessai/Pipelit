"""Telegram command and message handlers."""

import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.gateway import (
    ConfirmationHandler,
    Executor,
    ExecutionStrategy,
)
from app.services.llm import get_compress_threshold, get_context_window
from app.services.sessions import SessionService
from app.tasks.chat import process_chat_message
from app.tasks.categorizer import categorize_and_execute
from app.tasks.queues import default_queue, high_queue

logger = logging.getLogger(__name__)

# Session service for sync operations (via asyncio.to_thread)
_session_service: SessionService | None = None

# Gateway components
_confirmation_handler: ConfirmationHandler | None = None


def get_session_service() -> SessionService:
    """Get or create session service."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service


def get_confirmation_handler() -> ConfirmationHandler:
    """Get or create confirmation handler."""
    global _confirmation_handler
    if _confirmation_handler is None:
        _confirmation_handler = ConfirmationHandler(
            timeout_minutes=settings.CONFIRMATION_TIMEOUT_MINUTES
        )
    return _confirmation_handler


def is_allowed(user_id: int) -> bool:
    """Check if user is whitelisted."""
    allowed = settings.allowed_user_ids_list
    if not allowed:
        return True
    return user_id in allowed


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return

    gateway_status = "enabled" if settings.GATEWAY_ENABLED else "disabled"

    await update.message.reply_text(
        "Hello! I'm connected via LangChain.\n\n"
        "Commands:\n"
        "/clear - Clear conversation history\n"
        "/stats - Show session statistics\n"
        "/context - Show context window usage\n"
        "/pending - Show pending confirmations\n\n"
        f"Gateway: {gateway_status}\n\n"
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

    context_window = get_context_window()
    threshold = get_compress_threshold()
    token_count = stats_data["token_count"]

    usage_pct = (token_count / context_window * 100) if context_window > 0 else 0
    threshold_pct = (token_count / threshold * 100) if threshold > 0 else 0

    text = (
        f"Context Window Usage:\n"
        f"- Model: {settings.LLM_MODEL}\n"
        f"- Context window: {context_window:,} tokens\n"
        f"- Compress threshold: {threshold:,} tokens ({settings.COMPRESS_RATIO:.0%})\n"
        f"- Current usage: {token_count:,} tokens ({usage_pct:.1f}%)\n"
        f"- Until compression: {threshold_pct:.1f}%"
    )
    await update.message.reply_text(text)


async def pending_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pending command - show pending confirmations."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    handler = get_confirmation_handler()
    pending = handler.get_user_pending(user_id)

    if not pending:
        await update.message.reply_text("No pending confirmations.")
        return

    lines = ["Pending confirmations:\n"]
    for task in pending:
        remaining = task.get_remaining_time()
        minutes = int(remaining.total_seconds() // 60)
        lines.append(
            f"- `{task.task_id}`: {task.message[:50]}... ({minutes}m left)\n"
            f"  /confirm_{task.task_id} or /cancel_{task.task_id}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /confirm_<task_id> commands."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    text = update.message.text
    match = re.match(r"/confirm_([a-f0-9]+)", text)
    if not match:
        await update.message.reply_text("Invalid confirm command. Use /confirm_<task_id>")
        return

    task_id = match.group(1)
    handler = get_confirmation_handler()
    task = handler.confirm(task_id, user_id)

    if not task:
        await update.message.reply_text(
            f"Confirmation `{task_id}` not found or expired.", parse_mode="Markdown"
        )
        return

    await update.message.reply_text(f"Confirmed! Executing task...")

    executor = Executor()
    chat_id = update.effective_chat.id
    session_id = f"user_{user_id}"

    from app.gateway.router import RouteResult

    route = RouteResult(
        strategy=ExecutionStrategy(task.strategy)
        if task.strategy in ("macro", "agent", "dynamic")
        else ExecutionStrategy.AGENT,
        target=task.target,
        requires_confirmation=False,
        requires_planning=task.strategy == "dynamic",
        confidence=1.0,
        original_message=task.message,
    )

    if task.strategy == "plan_step" and task.plan_id:
        from app.tasks.agent_tasks import run_plan_step
        from app.tasks.queues import default_queue as dq

        job = dq.enqueue(
            run_plan_step,
            plan_id=task.plan_id,
            user_id=user_id,
            chat_id=chat_id,
            session_id=session_id,
            message_id=update.message.message_id,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Resumed plan step as job {job.id}")
    else:
        job_id = executor.execute(
            route=route,
            user_id=user_id,
            chat_id=chat_id,
            message_id=update.message.message_id,
            session_id=session_id,
        )
        logger.info(f"Confirmed task {task_id} enqueued as job {job_id}")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel_<task_id> commands."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    text = update.message.text
    match = re.match(r"/cancel_([a-f0-9]+)", text)
    if not match:
        await update.message.reply_text("Invalid cancel command. Use /cancel_<task_id>")
        return

    task_id = match.group(1)
    handler = get_confirmation_handler()
    cancelled = handler.cancel(task_id, user_id)

    if cancelled:
        await update.message.reply_text(f"Task `{task_id}` cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"Task `{task_id}` not found or already processed.", parse_mode="Markdown"
        )


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

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if settings.GATEWAY_ENABLED:
        await _handle_via_gateway(
            user_id, chat_id, message_id, user_message, update, context
        )
    else:
        await _handle_direct_chat(user_id, chat_id, message_id, user_message)


async def _handle_via_gateway(
    user_id: int,
    chat_id: int,
    message_id: int,
    user_message: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route message through the gateway by enqueuing a categorizer task."""
    session_id = f"user_{user_id}"
    job = high_queue.enqueue(
        categorize_and_execute,
        message=user_message,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        session_id=session_id,
        job_timeout=settings.JOB_TIMEOUT,
    )
    logger.info(f"Enqueued categorizer job {job.id} for user {user_id}")


async def _handle_direct_chat(
    user_id: int, chat_id: int, message_id: int, user_message: str
) -> None:
    """Handle message via direct chat (legacy mode)."""
    job = default_queue.enqueue(
        process_chat_message,
        chat_id=chat_id,
        user_id=user_id,
        message=user_message,
        message_id=message_id,
        job_timeout=settings.JOB_TIMEOUT,
    )
    logger.info(f"Enqueued job {job.id} for user {user_id}")
