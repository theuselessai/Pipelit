"""Telegram polling setup using python-telegram-bot."""
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.bot.handlers import (
    clear_handler,
    context_handler,
    message_handler,
    start_handler,
    stats_handler,
)
from app.config import settings
from app.services.aichat import AsyncAIChatService

logger = logging.getLogger(__name__)

# Async AIChat service for fetching model info at startup
_aichat_service: AsyncAIChatService | None = None


async def on_startup(application: Application) -> None:
    """Initialize on startup."""
    global _aichat_service

    # Create async AIChat service
    _aichat_service = AsyncAIChatService()

    # Fetch model context windows
    await _aichat_service.fetch_model_context_windows()

    logger.info("Bot started with session management and RQ integration")


async def on_shutdown(application: Application) -> None:
    """Cleanup on shutdown."""
    global _aichat_service

    if _aichat_service is not None:
        await _aichat_service.close()
        _aichat_service = None

    logger.info("Bot shutdown complete")


def create_application() -> Application:
    """Create and configure the Telegram application."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("clear", clear_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("context", context_handler))

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
