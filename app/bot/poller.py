"""Telegram polling setup using python-telegram-bot."""
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.bot.handlers import (
    cancel_handler,
    clear_handler,
    confirm_handler,
    context_handler,
    message_handler,
    pending_handler,
    start_handler,
    stats_handler,
)
from app.config import settings

logger = logging.getLogger(__name__)


async def on_startup(application: Application) -> None:
    """Initialize on startup."""
    logger.info("Bot started with LangChain LLM and RQ integration")


async def on_shutdown(application: Application) -> None:
    """Cleanup on shutdown."""
    logger.info("Bot shutdown complete")


def create_application() -> Application:
    """Create and configure the Telegram application."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("clear", clear_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("context", context_handler))
    app.add_handler(CommandHandler("pending", pending_handler))

    # Dynamic confirm/cancel commands using regex filter
    app.add_handler(
        MessageHandler(filters.Regex(r"^/confirm_[a-f0-9]+$"), confirm_handler)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^/cancel_[a-f0-9]+$"), cancel_handler)
    )

    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Lifecycle hooks
    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    return app


def run_polling() -> None:
    """Run the bot with polling."""
    logger.info("Starting Telegram bot with polling...")

    app = create_application()
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)
