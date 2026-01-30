"""TelegramTriggerHandler — process Telegram updates into workflow executions."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User

from apps.credentials.models import TelegramCredential
from apps.users.models import UserProfile
from apps.workflows.delivery import output_delivery
from apps.workflows.handlers import dispatch_event

logger = logging.getLogger(__name__)


class TelegramTriggerHandler:
    """Handles incoming Telegram messages and routes them to workflows."""

    def handle_message(self, bot_token: str, update_data: dict) -> None:
        """Process a Telegram message update.

        Args:
            bot_token: The bot token that received this update.
            update_data: Raw Telegram update dict (contains "message" key).
        """
        message = update_data.get("message", {})
        if not message:
            return

        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        text = message.get("text", "")

        if not user_id or not chat_id:
            return

        # Check allowed users for this bot
        if not self._is_user_allowed(bot_token, user_id):
            logger.debug("User %s not allowed for this bot", user_id)
            return

        user_profile = self._get_or_create_profile(user_id, message.get("from", {}))

        event_data = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "bot_token": bot_token,
        }

        # Use telegram_chat as default event type
        event_type = "telegram_chat"

        # Send typing indicator
        output_delivery.send_typing_action(bot_token, chat_id)

        execution = dispatch_event(event_type, event_data, user_profile)

        if execution is None:
            # No workflow matched — send fallback
            output_delivery.send_telegram_message(
                bot_token,
                chat_id,
                "No workflow configured to handle this message.",
                reply_to=message_id,
            )

    def handle_confirmation(
        self, bot_token: str, task_id: str, user_action: str
    ) -> None:
        """Handle /confirm_<id> or /cancel_<id> commands.

        Args:
            bot_token: Bot token.
            task_id: PendingTask.task_id (8-char hex).
            user_action: "confirm" or "cancel".
        """
        import django_rq
        from django.utils import timezone

        from apps.workflows.executor import resume_workflow_job
        from apps.workflows.models import PendingTask

        try:
            pending = PendingTask.objects.select_related("execution").get(task_id=task_id)
        except PendingTask.DoesNotExist:
            logger.warning("PendingTask %s not found", task_id)
            return

        # Check expiry
        if pending.expires_at < timezone.now():
            pending.delete()
            output_delivery.send_telegram_message(
                bot_token,
                pending.telegram_chat_id,
                "This confirmation has expired.",
            )
            return

        execution = pending.execution
        chat_id = pending.telegram_chat_id
        pending.delete()

        if user_action == "cancel":
            execution.status = "cancelled"
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "completed_at"])
            output_delivery.send_telegram_message(bot_token, chat_id, "Action cancelled.")
            return

        # Resume the workflow
        queue = django_rq.get_queue("workflows")
        queue.enqueue(resume_workflow_job, str(execution.execution_id), user_action)

    def handle_command(
        self, bot_token: str, command: str, update_data: dict
    ) -> None:
        """Handle bot commands like /start, /pending.

        Args:
            bot_token: Bot token.
            command: Command name without slash (e.g., "start").
            update_data: Raw Telegram update dict.
        """
        message = update_data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return

        if command == "start":
            output_delivery.send_telegram_message(
                bot_token, chat_id, "Workflow bot is ready. Send a message to begin."
            )
        elif command == "pending":
            self._show_pending_tasks(bot_token, chat_id, message)
        else:
            # Unknown command — treat as regular message
            self.handle_message(bot_token, update_data)

    def _show_pending_tasks(self, bot_token: str, chat_id: int, message: dict) -> None:
        """List pending confirmation tasks for the user."""
        from django.utils import timezone

        from apps.workflows.models import PendingTask

        user_id = message.get("from", {}).get("id")
        if not user_id:
            return

        tasks = PendingTask.objects.filter(
            telegram_chat_id=chat_id,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at")[:10]

        if not tasks:
            output_delivery.send_telegram_message(bot_token, chat_id, "No pending tasks.")
            return

        lines = ["Pending confirmations:"]
        for t in tasks:
            lines.append(f"  {t.prompt}\n  /confirm_{t.task_id}  /cancel_{t.task_id}")
        output_delivery.send_telegram_message(bot_token, chat_id, "\n\n".join(lines))

    def _is_user_allowed(self, bot_token: str, user_id: int) -> bool:
        """Check if user is allowed by the bot's credential config."""
        try:
            cred = TelegramCredential.objects.get(bot_token=bot_token)
        except TelegramCredential.DoesNotExist:
            return True  # No credential record — allow (bot token passed directly)

        if not cred.allowed_user_ids:
            return True

        allowed = [
            int(uid.strip())
            for uid in cred.allowed_user_ids.split(",")
            if uid.strip()
        ]
        return not allowed or user_id in allowed

    def _get_or_create_profile(self, telegram_user_id: int, from_data: dict) -> UserProfile:
        """Look up or auto-provision a UserProfile for a Telegram user."""
        try:
            return UserProfile.objects.get(telegram_user_id=telegram_user_id)
        except UserProfile.DoesNotExist:
            pass

        # Auto-create Django user + profile
        first = from_data.get("first_name", "")
        last = from_data.get("last_name", "")
        username = from_data.get("username") or f"tg_{telegram_user_id}"

        # Ensure unique username
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            first_name=first,
            last_name=last,
        )
        profile = UserProfile.objects.create(
            user=user,
            telegram_user_id=telegram_user_id,
        )
        logger.info("Auto-provisioned UserProfile for Telegram user %s", telegram_user_id)
        return profile


# Module-level singleton
telegram_handler = TelegramTriggerHandler()
