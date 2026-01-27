"""
RQ tasks that invoke AIChat agents and macros via CLI.

Workers execute these tasks using local `aichat` commands.
"""

import logging
import os
import re
import subprocess
from typing import Optional

from app.config import settings
from app.services.telegram import send_message, send_photo, send_typing

logger = logging.getLogger(__name__)


def run_agent_task(
    agent: str,
    message: str,
    user_id: int,
    chat_id: int,
    session_id: str,
    message_id: Optional[int] = None,
) -> dict:
    """
    Run an AIChat agent via CLI.

    Args:
        agent: Agent name (e.g., "browser_agent", "system_agent")
        message: The message/prompt for the agent
        user_id: Telegram user ID
        chat_id: Telegram chat ID
        session_id: Session ID for conversation continuity
        message_id: Original message ID for reply

    Returns:
        Dict with success status and response
    """
    # Set environment variables for tools
    env = os.environ.copy()
    env["USER_ID"] = str(user_id)
    env["CHAT_ID"] = str(chat_id)

    cmd = [
        "aichat",
        "--agent",
        agent,
        "--session",
        session_id,
        message,
    ]

    logger.info(f"Running agent: {agent} for user {user_id}")

    try:
        send_typing(chat_id)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=settings.JOB_TIMEOUT,
        )

        response_text = result.stdout.strip()
        stderr = result.stderr.strip()

        if stderr:
            logger.warning(f"Agent stderr: {stderr[:500]}")

        if result.returncode != 0:
            logger.error(f"Agent {agent} failed with code {result.returncode}")
            error_msg = stderr or response_text or "Unknown error"
            send_message(chat_id, f"Agent error: {error_msg[:500]}", message_id)
            return {"success": False, "error": error_msg}

        # Handle image responses (e.g., screenshots)
        if "[IMAGE:" in response_text:
            _handle_image_response(chat_id, response_text, message_id)
        elif response_text:
            _send_response(chat_id, response_text, message_id)
        else:
            send_message(chat_id, "Task completed (no output)", message_id)

        return {"success": True, "response": response_text}

    except subprocess.TimeoutExpired:
        logger.error(f"Agent {agent} timed out")
        send_message(chat_id, "Task timed out. Please try again.", message_id)
        return {"success": False, "error": "timeout"}

    except Exception as e:
        logger.exception(f"Agent task failed: {agent}")
        send_message(chat_id, f"Error: {str(e)[:500]}", message_id)
        return {"success": False, "error": str(e)}


def run_macro_task(
    macro: str,
    args: str,
    user_id: int,
    chat_id: int,
    message_id: Optional[int] = None,
) -> dict:
    """
    Run an AIChat macro via CLI.

    Args:
        macro: Macro name (e.g., "generate-commit-message")
        args: Arguments for the macro
        user_id: Telegram user ID
        chat_id: Telegram chat ID
        message_id: Original message ID for reply

    Returns:
        Dict with success status and response
    """
    # Build command - macros may have variable arguments
    cmd = ["aichat", "--macro", macro]

    # Parse args if provided
    if args and args.strip():
        # Simple argument parsing - split on whitespace
        # TODO: Handle quoted strings properly
        cmd.extend(args.split())

    logger.info(f"Running macro: {macro} for user {user_id}")

    try:
        send_typing(chat_id)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.JOB_TIMEOUT,
        )

        response_text = result.stdout.strip()
        stderr = result.stderr.strip()

        if stderr:
            logger.warning(f"Macro stderr: {stderr[:500]}")

        if result.returncode != 0:
            logger.error(f"Macro {macro} failed with code {result.returncode}")
            error_msg = stderr or response_text or "Unknown error"
            send_message(chat_id, f"Macro error: {error_msg[:500]}", message_id)
            return {"success": False, "error": error_msg}

        if response_text:
            _send_response(chat_id, response_text, message_id)
        else:
            send_message(chat_id, "Macro completed (no output)", message_id)

        return {"success": True, "response": response_text}

    except subprocess.TimeoutExpired:
        logger.error(f"Macro {macro} timed out")
        send_message(chat_id, "Task timed out. Please try again.", message_id)
        return {"success": False, "error": "timeout"}

    except Exception as e:
        logger.exception(f"Macro task failed: {macro}")
        send_message(chat_id, f"Error: {str(e)[:500]}", message_id)
        return {"success": False, "error": str(e)}


def run_plan_step(
    plan_id: str,
    user_id: int,
    chat_id: int,
    session_id: str,
    message_id: Optional[int] = None,
) -> dict:
    """
    Execute the next step in a dynamic plan.

    Automatically enqueues the following step after completion.

    Args:
        plan_id: Plan identifier
        user_id: Telegram user ID
        chat_id: Telegram chat ID
        session_id: Session ID for agent conversations
        message_id: Original message ID for reply

    Returns:
        Dict with success status and step info
    """
    from app.gateway.executor import Executor
    from app.gateway.planner import DynamicPlanner, StepStatus

    planner = DynamicPlanner()
    step = planner.get_next_step(plan_id)

    if not step:
        # Plan is complete or has no more steps
        plan = planner.get_plan(plan_id)
        if plan:
            completed, total = plan.get_progress()
            send_message(
                chat_id, f"Plan completed! ({completed}/{total} steps)", message_id
            )
        return {"success": True, "status": "plan_completed"}

    # Check if this step needs confirmation
    plan = planner.get_plan(plan_id)
    if plan and step.order in plan.checkpoints:
        from app.gateway.confirmation import ConfirmationHandler

        handler = ConfirmationHandler()
        task_id = handler.create_pending_task(
            user_id=user_id,
            chat_id=chat_id,
            message=step.action,
            target=step.agent,
            strategy="plan_step",
            plan_id=plan_id,
        )
        send_message(
            chat_id,
            f"Step {step.order} requires confirmation:\n"
            f"**Action**: {step.action}\n\n"
            f"Reply `/confirm_{task_id}` to proceed or `/cancel_{task_id}` to skip.",
            message_id,
        )
        return {"success": True, "status": "awaiting_confirmation", "task_id": task_id}

    # Mark step as running
    planner.update_step(plan_id, step.order, StepStatus.RUNNING)

    # Send progress update
    completed, total = plan.get_progress() if plan else (0, 1)
    send_message(
        chat_id,
        f"Step {step.order}/{total}: {step.action}",
        message_id,
    )

    # Execute the step
    result = run_agent_task(
        agent=step.agent,
        message=step.action,
        user_id=user_id,
        chat_id=chat_id,
        session_id=session_id,
        message_id=None,  # Don't reply to original for intermediate steps
    )

    # Update step status
    if result["success"]:
        planner.update_step(
            plan_id, step.order, StepStatus.COMPLETED, result.get("response")
        )
    else:
        planner.update_step(
            plan_id, step.order, StepStatus.FAILED, error=result.get("error")
        )

    # Enqueue next step if available
    executor = Executor()
    next_job_id = executor.enqueue_next_plan_step(plan_id, user_id, chat_id, session_id)

    if not next_job_id:
        # No more steps
        plan = planner.get_plan(plan_id)
        if plan:
            completed, total = plan.get_progress()
            status = "completed" if result["success"] else "completed with errors"
            send_message(
                chat_id,
                f"Plan {status}! ({completed}/{total} steps)",
                None,
            )

    return {
        "success": result["success"],
        "step": step.order,
        "next_job": next_job_id,
    }


def _handle_image_response(
    chat_id: int, response_text: str, message_id: Optional[int]
) -> None:
    """
    Handle response containing image markers.

    Expected format: [IMAGE:/path/to/image.png]
    """
    # Extract image path
    match = re.search(r"\[IMAGE:([^\]]+)\]", response_text)
    if not match:
        send_message(chat_id, response_text, message_id)
        return

    img_path = match.group(1)

    # Clean text (remove image markers)
    clean_text = re.sub(r"\[IMAGE:[^\]]+\]", "", response_text).strip()

    if os.path.exists(img_path):
        send_photo(chat_id, img_path, caption=clean_text[:1024] if clean_text else None)
    else:
        logger.warning(f"Image not found: {img_path}")
        send_message(chat_id, clean_text or "Image not found", message_id)


def _send_response(
    chat_id: int, response_text: str, message_id: Optional[int]
) -> None:
    """Send response, splitting if too long for Telegram."""
    max_len = 4096

    if len(response_text) <= max_len:
        send_message(chat_id, response_text, message_id)
    else:
        # Split into chunks
        for i in range(0, len(response_text), max_len):
            chunk = response_text[i : i + max_len]
            # Only reply to original for first chunk
            reply_id = message_id if i == 0 else None
            send_message(chat_id, chunk, reply_id)
