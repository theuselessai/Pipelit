#!/usr/bin/env python3
"""
Telegram bot that relays messages to a local AIChat server.
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

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# HTTP client for AIChat
http_client = httpx.AsyncClient(timeout=120.0)


def is_allowed(user_id: int) -> bool:
    """Check if user is whitelisted."""
    if not config.ALLOWED_USER_IDS:
        return True  # No whitelist = allow all (for testing)
    return user_id in config.ALLOWED_USER_IDS


async def chat_with_aichat(message: str) -> str:
    """Send message to AIChat server and get response."""
    try:
        response = await http_client.post(
            f"{config.AICHAT_BASE_URL}/v1/chat/completions",
            json={
                "model": config.AICHAT_MODEL,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        return "Request timed out. Please try again."
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e}")
        return f"API error: {e.response.status_code}"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"Error: {str(e)}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text(
        "Hello! I'm connected to AIChat + Venice.ai GLM-4.7.\n\n" "Just send me a message!"
    )


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

    # Get response from AIChat
    response = await chat_with_aichat(user_message)

    # Send response (split if too long)
    max_len = 4096
    if len(response) <= max_len:
        await update.message.reply_text(response)
    else:
        for i in range(0, len(response), max_len):
            await update.message.reply_text(response[i : i + max_len])


async def on_shutdown(application: Application):
    """Cleanup on shutdown."""
    await http_client.aclose()


def main():
    """Start the bot."""
    logger.info("Starting Telegram-AIChat bot...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Shutdown hook
    app.post_shutdown = on_shutdown

    # Run
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
