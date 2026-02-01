"""TelegramTriggerHandler — process Telegram updates into workflow executions."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from handlers import dispatch_event
from models.credential import TelegramCredential
from models.user import UserProfile
from services.delivery import output_delivery

logger = logging.getLogger(__name__)


class TelegramTriggerHandler:

    def handle_message(self, bot_token: str, update_data: dict, db: Session) -> None:
        message = update_data.get("message", {})
        if not message:
            return
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        text = message.get("text", "")

        if not user_id or not chat_id:
            return

        if not self._is_user_allowed(bot_token, user_id, db):
            return

        user_profile = self._get_or_create_profile(user_id, message.get("from", {}), db)

        event_data = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "bot_token": bot_token,
        }

        output_delivery.send_typing_action(bot_token, chat_id)
        execution = dispatch_event("telegram_chat", event_data, user_profile, db)

        if execution is None:
            output_delivery.send_telegram_message(
                bot_token, chat_id,
                "No workflow configured to handle this message.",
                reply_to=message_id,
            )

    def handle_confirmation(self, bot_token: str, task_id: str, user_action: str, db: Session) -> None:
        import redis
        from datetime import datetime, timezone
        from rq import Queue

        from config import settings
        from models.execution import PendingTask
        from tasks import resume_workflow_job

        pending = db.query(PendingTask).filter(PendingTask.task_id == task_id).first()
        if not pending:
            return

        if pending.expires_at < datetime.now(timezone.utc):
            db.delete(pending)
            db.commit()
            output_delivery.send_telegram_message(
                bot_token, pending.telegram_chat_id,
                "This confirmation has expired.",
            )
            return

        execution = pending.execution
        chat_id = pending.telegram_chat_id
        db.delete(pending)
        db.commit()

        if user_action == "cancel":
            execution.status = "cancelled"
            execution.completed_at = datetime.now(timezone.utc)
            db.commit()
            output_delivery.send_telegram_message(bot_token, chat_id, "Action cancelled.")
            return

        conn = redis.from_url(settings.REDIS_URL)
        queue = Queue("workflows", connection=conn)
        queue.enqueue(resume_workflow_job, str(execution.execution_id), user_action)

    def handle_command(self, bot_token: str, command: str, update_data: dict, db: Session) -> None:
        message = update_data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return

        if command == "start":
            output_delivery.send_telegram_message(bot_token, chat_id, "Workflow bot is ready. Send a message to begin.")
        elif command == "pending":
            self._show_pending_tasks(bot_token, chat_id, message, db)
        else:
            self.handle_message(bot_token, update_data, db)

    def _show_pending_tasks(self, bot_token: str, chat_id: int, message: dict, db: Session) -> None:
        from datetime import datetime, timezone
        from models.execution import PendingTask

        user_id = message.get("from", {}).get("id")
        if not user_id:
            return

        tasks = (
            db.query(PendingTask)
            .filter(PendingTask.telegram_chat_id == chat_id, PendingTask.expires_at > datetime.now(timezone.utc))
            .order_by(PendingTask.created_at.desc())
            .limit(10)
            .all()
        )

        if not tasks:
            output_delivery.send_telegram_message(bot_token, chat_id, "No pending tasks.")
            return

        lines = ["Pending confirmations:"]
        for t in tasks:
            lines.append(f"  {t.prompt}\n  /confirm_{t.task_id}  /cancel_{t.task_id}")
        output_delivery.send_telegram_message(bot_token, chat_id, "\n\n".join(lines))

    def _is_user_allowed(self, bot_token: str, user_id: int, db: Session) -> bool:
        cred = db.query(TelegramCredential).filter(TelegramCredential.bot_token == bot_token).first()
        if not cred:
            return True
        if not cred.allowed_user_ids:
            return True
        allowed = [int(uid.strip()) for uid in cred.allowed_user_ids.split(",") if uid.strip()]
        return not allowed or user_id in allowed

    def _get_or_create_profile(self, telegram_user_id: int, from_data: dict, db: Session) -> UserProfile:
        profile = db.query(UserProfile).filter(UserProfile.telegram_user_id == telegram_user_id).first()
        if profile:
            return profile

        first = from_data.get("first_name", "")
        last = from_data.get("last_name", "")
        username = from_data.get("username") or f"tg_{telegram_user_id}"

        base_username = username
        counter = 1
        while db.query(UserProfile).filter(UserProfile.username == username).first():
            username = f"{base_username}_{counter}"
            counter += 1

        from passlib.hash import pbkdf2_sha256
        profile = UserProfile(
            username=username,
            first_name=first,
            last_name=last,
            telegram_user_id=telegram_user_id,
            password_hash=pbkdf2_sha256.hash(uuid.uuid4().hex),  # random password
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile


import uuid  # noqa: E402

telegram_handler = TelegramTriggerHandler()
