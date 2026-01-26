#!/usr/bin/env python3
"""
AIChat Telegram Bot - Entry point.

Starts the Telegram poller and optionally the FastAPI server.
"""
import asyncio
import logging
import sys
import threading

import uvicorn
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.sessions import router as sessions_router
from app.bot.poller import run_polling
from app.config import settings

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def create_api() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="AIChat Telegram Bot API",
        description="REST API for AIChat Telegram Bot",
        version="2.0.0",
    )

    app.include_router(health_router)
    app.include_router(sessions_router)

    return app


def run_api_server() -> None:
    """Run the FastAPI server in a separate thread."""
    app = create_api()
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT, log_level="info")


def main() -> None:
    """Main entry point."""
    logger.info("Starting AIChat Telegram Bot...")
    logger.info(f"API enabled: {settings.API_ENABLED}")

    if settings.API_ENABLED:
        # Start API server in background thread
        api_thread = threading.Thread(target=run_api_server, daemon=True)
        api_thread.start()
        logger.info(f"API server started on port {settings.API_PORT}")

    # Run Telegram bot (blocking)
    run_polling()


if __name__ == "__main__":
    main()
