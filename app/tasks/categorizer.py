"""Categorizer task: classifies messages via aichat LLM role, then enqueues execution."""

import json
import logging
import subprocess

from app.config import settings
from app.gateway.confirmation import ConfirmationHandler
from app.gateway.executor import Executor
from app.gateway.router import ExecutionStrategy, RouteResult, parse_categorizer_output
from app.services.telegram import send_message

logger = logging.getLogger(__name__)

STRATEGY_DESCRIPTIONS = {
    ExecutionStrategy.MACRO: "Predefined workflow",
    ExecutionStrategy.AGENT: "Agent task",
    ExecutionStrategy.DYNAMIC_PLAN: "Multi-step plan",
    ExecutionStrategy.CHAT: "Conversation",
}


def categorize_and_execute(
    message: str,
    user_id: int,
    chat_id: int,
    message_id: int,
    session_id: str,
) -> None:
    """
    Classify a message using aichat -r categorizer, then enqueue the real task.

    Called as an RQ task from the handler.
    """
    # Run aichat categorizer
    raw_output = _run_categorizer(message)
    route = parse_categorizer_output(raw_output, message)

    logger.info(
        f"Categorized to {route.strategy.value}: {route.target} "
        f"(confirm={route.requires_confirmation})"
    )

    # Handle confirmation
    if route.requires_confirmation:
        handler = ConfirmationHandler(
            timeout_minutes=settings.CONFIRMATION_TIMEOUT_MINUTES
        )
        task_id = handler.create_pending_task(
            user_id=user_id,
            chat_id=chat_id,
            message=message,
            target=route.target,
            strategy=route.strategy.value,
        )
        desc = STRATEGY_DESCRIPTIONS.get(route.strategy, "Task")
        msg = handler.format_confirmation_message(
            handler.get_pending_task(task_id),
            f"{desc}: {route.target}",
        )
        send_message(chat_id, msg, reply_to_message_id=message_id)
        return

    # Execute the routed task
    executor = Executor()
    job_id = executor.execute(
        route=route,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        session_id=session_id,
    )

    # Send status for non-chat routes
    if route.strategy != ExecutionStrategy.CHAT:
        status_msg = {
            ExecutionStrategy.MACRO: f"Running macro: {route.target}",
            ExecutionStrategy.AGENT: f"Processing with {route.target}",
            ExecutionStrategy.DYNAMIC_PLAN: "Creating execution plan...",
        }
        send_message(
            chat_id,
            f"{status_msg.get(route.strategy, 'Processing...')}\nJob: {job_id[:8]}",
            reply_to_message_id=message_id,
        )

    logger.info(f"Enqueued job {job_id} for user {user_id}")


def _run_categorizer(message: str) -> str:
    """Run aichat -r categorizer and return raw output."""
    try:
        result = subprocess.run(
            ["aichat", "-r", "categorizer", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"aichat categorizer failed: {result.stderr}")
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error(f"aichat categorizer error: {e}")
        return ""
