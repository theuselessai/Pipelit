#!/usr/bin/env python3
"""
Telegram bot that relays messages to a local AIChat server with session management.
"""
import logging

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import config
import sessions

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# HTTP client for AIChat
http_client = httpx.AsyncClient(timeout=120.0)

# Database connection
db_conn = None


def is_allowed(user_id: int) -> bool:
    """Check if user is whitelisted."""
    if not config.ALLOWED_USER_IDS:
        return True  # No whitelist = allow all (for testing)
    return user_id in config.ALLOWED_USER_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command - clear conversation history."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    sessions.clear_conversation(db_conn, user_id)
    await update.message.reply_text("Conversation cleared.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command - show session statistics."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    stats_data = sessions.get_stats(db_conn, user_id)

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


async def context_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /context command - show context window usage."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        await update.message.reply_text("Access denied.")
        return

    stats_data = sessions.get_stats(db_conn, user_id)
    context_window = sessions.get_context_window(config.AICHAT_MODEL)
    threshold = sessions.get_compress_threshold(config.AICHAT_MODEL)
    token_count = stats_data["token_count"]

    usage_pct = (token_count / context_window * 100) if context_window > 0 else 0
    threshold_pct = (token_count / threshold * 100) if threshold > 0 else 0

    text = (
        f"Context Window Usage:\n"
        f"- Model: {config.AICHAT_MODEL}\n"
        f"- Context window: {context_window:,} tokens\n"
        f"- Compress threshold: {threshold:,} tokens ({config.COMPRESS_RATIO:.0%})\n"
        f"- Current usage: {token_count:,} tokens ({usage_pct:.1f}%)\n"
        f"- Until compression: {threshold_pct:.1f}%"
    )
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        logger.warning(f"Unauthorized: {user_id}")
        await update.message.reply_text("Access denied.")
        return

    user_message = update.message.text
    logger.info(f"[{user_id}] {user_message[:50]}...")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        # Process message with session management
        response = await sessions.process_message(
            db_conn, http_client, user_id, user_message
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


async def on_startup(application: Application):
    """Initialize on startup."""
    global db_conn

    # Initialize database
    db_conn = sessions.init_db()

    # Fetch model context windows
    await sessions.fetch_model_context_windows(http_client)

    logger.info("Bot started with session management enabled")


async def on_shutdown(application: Application):
    """Cleanup on shutdown."""
    await http_client.aclose()
    if db_conn:
        db_conn.close()


def main():
    """Start the bot."""
    logger.info("Starting Telegram-AIChat bot...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("context", context_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Lifecycle hooks
    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    # Run
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
