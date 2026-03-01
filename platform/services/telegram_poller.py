"""Telegram polling service — self-rescheduling RQ job using getUpdates."""

from __future__ import annotations

import logging
from datetime import timedelta

import redis
import requests
from rq import Queue
from sqlalchemy import and_

from config import settings
from database import SessionLocal
from handlers.telegram import telegram_handler
from models.credential import BaseCredential, TelegramCredential
from models.node import BaseComponentConfig, WorkflowNode

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/getUpdates"
OFFSET_KEY = "tg_poll_offset:{credential_id}"
OFFSET_TTL = 30 * 24 * 3600  # 30 days


def poll_telegram_credential(credential_id: int, error_count: int = 0) -> None:
    """Self-rescheduling RQ job. Polls Telegram getUpdates for one credential.

    Called by RQ worker on the ``telegram`` queue.
    """
    db = SessionLocal()
    try:
        # Load credential
        base_cred = db.get(BaseCredential, credential_id)
        if not base_cred or not base_cred.telegram_credential:
            logger.warning("Telegram credential %s not found, stopping poll", credential_id)
            return

        tg_cred: TelegramCredential = base_cred.telegram_credential
        token = tg_cred.bot_token

        # Check at least one active trigger_telegram node uses this credential
        active_count = (
            db.query(WorkflowNode)
            .join(BaseComponentConfig, WorkflowNode.component_config_id == BaseComponentConfig.id)
            .filter(
                and_(
                    WorkflowNode.component_type == "trigger_telegram",
                    BaseComponentConfig.credential_id == credential_id,
                    BaseComponentConfig.is_active == True,  # noqa: E712
                )
            )
            .count()
        )
        if active_count == 0:
            logger.info("No active trigger_telegram nodes for credential %s, stopping poll", credential_id)
            return

        # Get offset from Redis
        r = redis.from_url(settings.REDIS_URL)
        offset_key = OFFSET_KEY.format(credential_id=credential_id)
        raw_offset = r.get(offset_key)
        offset = int(raw_offset) if raw_offset else 0

        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token),
                json={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
                timeout=35,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Telegram getUpdates failed for credential %s", credential_id)
            _enqueue_poll(credential_id, error_count + 1)
            return

        if not data.get("ok"):
            logger.error("Telegram API error for credential %s: %s", credential_id, data.get("description"))
            _enqueue_poll(credential_id, error_count + 1)
            return

        updates = data.get("result", [])
        for update in updates:
            try:
                _route_update(token, update, db)
            except Exception:
                logger.exception("Error processing Telegram update %s", update.get("update_id"))
            # Advance offset even if processing fails
            new_offset = update["update_id"] + 1
            r.set(offset_key, str(new_offset), ex=OFFSET_TTL)

        # Self-reschedule immediately on success
        _enqueue_poll(credential_id, 0)

    except Exception:
        logger.exception("Fatal error in poll_telegram_credential(%s)", credential_id)
        _enqueue_poll(credential_id, error_count + 1)
    finally:
        db.close()


def _route_update(bot_token: str, update: dict, db) -> None:
    """Route a single Telegram update to the appropriate handler."""

    # callback_query → confirmation
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_data = cb.get("data", "")
        if cb_data.startswith("confirm_"):
            task_id = cb_data[len("confirm_"):]
            telegram_handler.handle_confirmation(bot_token, task_id, "confirm", db)
        elif cb_data.startswith("cancel_"):
            task_id = cb_data[len("cancel_"):]
            telegram_handler.handle_confirmation(bot_token, task_id, "cancel", db)
        return

    message = update.get("message", {})
    text = message.get("text", "")

    # /confirm_xxx or /cancel_xxx commands → confirmation
    if text.startswith("/confirm_"):
        task_id = text.split()[0][len("/confirm_"):]
        telegram_handler.handle_confirmation(bot_token, task_id, "confirm", db)
        return
    if text.startswith("/cancel_"):
        task_id = text.split()[0][len("/cancel_"):]
        telegram_handler.handle_confirmation(bot_token, task_id, "cancel", db)
        return

    # Everything else → handle_message (including /start, /help, etc.)
    telegram_handler.handle_message(bot_token, update, db)


def _backoff(error_count: int) -> int:
    """Exponential backoff: 5s, 10s, 20s, 40s, 60s cap."""
    if error_count <= 0:
        return 0
    return min(5 * (2 ** (error_count - 1)), 60)


def _enqueue_poll(credential_id: int, error_count: int) -> None:
    """Enqueue the next poll cycle with deterministic job ID."""
    from tasks import poll_telegram_credential_task

    conn = redis.from_url(settings.REDIS_URL)
    q = Queue("telegram", connection=conn)
    delay = _backoff(error_count)
    rq_job_id = f"tg-poll-{credential_id}"
    if delay > 0:
        q.enqueue_in(
            timedelta(seconds=delay),
            poll_telegram_credential_task,
            credential_id,
            error_count,
            job_id=rq_job_id,
            job_timeout=60,
        )
    else:
        q.enqueue(
            poll_telegram_credential_task,
            credential_id,
            error_count,
            job_id=rq_job_id,
            job_timeout=60,
        )


def start_telegram_polling(credential_id: int) -> None:
    """Start polling for a credential. Called from API endpoints."""
    _enqueue_poll(credential_id, 0)


def stop_telegram_polling(credential_id: int) -> None:
    """Stop polling — no-op. The poller checks is_active and stops itself."""
    pass


def recover_telegram_polling() -> int:
    """Re-enqueue poll jobs for all active telegram triggers on startup.

    Returns the number of distinct credentials recovered.
    """
    db = SessionLocal()
    try:
        # Find distinct credential_ids with active trigger_telegram nodes
        rows = (
            db.query(BaseComponentConfig.credential_id)
            .join(WorkflowNode, WorkflowNode.component_config_id == BaseComponentConfig.id)
            .filter(
                and_(
                    WorkflowNode.component_type == "trigger_telegram",
                    BaseComponentConfig.credential_id.isnot(None),
                    BaseComponentConfig.is_active == True,  # noqa: E712
                )
            )
            .distinct()
            .all()
        )
        credential_ids = [row[0] for row in rows]
        for cid in credential_ids:
            logger.info("Recovering Telegram polling for credential %s", cid)
            _enqueue_poll(cid, 0)
        return len(credential_ids)
    except Exception:
        logger.exception("Error recovering Telegram polling jobs")
        return 0
    finally:
        db.close()
