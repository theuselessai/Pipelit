"""Management command to run Telegram polling for all active bot credentials."""

from __future__ import annotations

import asyncio
import logging
import signal

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run Telegram polling for all active workflow bot credentials"

    def handle(self, *args, **options):
        self.stdout.write("Starting Telegram worker...")
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.stdout.write("Shutting down Telegram worker.")

    async def _run(self):
        from telegram import Update
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            MessageHandler,
            filters,
        )

        from apps.workflows.handlers.telegram import telegram_handler

        bot_tokens = self._get_active_bot_tokens()
        if not bot_tokens:
            self.stderr.write("No active bot tokens found. Exiting.")
            return

        self.stdout.write(f"Found {len(bot_tokens)} active bot(s)")
        apps = []

        for token in bot_tokens:
            app = ApplicationBuilder().token(token).build()

            # Confirmation commands
            app.add_handler(CommandHandler("start", self._make_command_handler(token, "start")))
            app.add_handler(CommandHandler("pending", self._make_command_handler(token, "pending")))

            # /confirm_<id> and /cancel_<id> — use regex-based filter
            app.add_handler(
                MessageHandler(
                    filters.Regex(r"^/confirm_[a-f0-9]+"),
                    self._make_confirmation_handler(token, "confirm"),
                )
            )
            app.add_handler(
                MessageHandler(
                    filters.Regex(r"^/cancel_[a-f0-9]+"),
                    self._make_confirmation_handler(token, "cancel"),
                )
            )

            # All other text messages
            app.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    self._make_message_handler(token),
                )
            )

            apps.append(app)

        # Start all pollers
        shutdown_event = asyncio.Event()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_event.set)

        for app in apps:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)

        self.stdout.write("Telegram polling started. Press Ctrl+C to stop.")
        await shutdown_event.wait()

        self.stdout.write("Shutting down pollers...")
        for app in apps:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    def _get_active_bot_tokens(self) -> list[str]:
        """Get bot tokens from TelegramCredentials linked to active workflows."""
        from apps.credentials.models import TelegramCredential

        creds = TelegramCredential.objects.filter(
            workflows__is_active=True,
            workflows__deleted_at__isnull=True,
        ).distinct()

        return [cred.bot_token for cred in creds]

    def _make_message_handler(self, bot_token: str):
        """Create an async handler that routes text messages to the sync handler."""

        async def handler(update: "Update", context):
            update_data = update.to_dict()
            # Run sync handler in thread pool
            await asyncio.to_thread(telegram_handler.handle_message, bot_token, update_data)

        return handler

    def _make_command_handler(self, bot_token: str, command: str):
        """Create an async handler for known commands."""

        async def handler(update: "Update", context):
            update_data = update.to_dict()
            await asyncio.to_thread(telegram_handler.handle_command, bot_token, command, update_data)

        return handler

    def _make_confirmation_handler(self, bot_token: str, action: str):
        """Create an async handler for /confirm_<id> or /cancel_<id>."""

        async def handler(update: "Update", context):
            text = update.message.text or ""
            # Extract task_id from /confirm_<id> or /cancel_<id>
            prefix = f"/{action}_"
            if text.startswith(prefix):
                task_id = text[len(prefix):].strip().split()[0]
                await asyncio.to_thread(
                    telegram_handler.handle_confirmation, bot_token, task_id, action
                )

        return handler
