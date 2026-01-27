"""
Handles user confirmations for sensitive actions.

Uses Redis for persistence (survives bot restarts).
Confirmation tokens have a TTL and auto-expire.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis

from app.config import settings


@dataclass
class PendingTask:
    """A task awaiting user confirmation."""

    task_id: str
    user_id: int
    chat_id: int
    message: str
    target: str  # Agent name, macro name, or "planner"
    strategy: str  # "macro", "agent", or "dynamic"
    plan_id: Optional[str]
    created_at: str
    expires_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "message": self.message,
            "target": self.target,
            "strategy": self.strategy,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingTask":
        """Create from dictionary."""
        return cls(
            task_id=data["task_id"],
            user_id=data["user_id"],
            chat_id=data["chat_id"],
            message=data["message"],
            target=data["target"],
            strategy=data["strategy"],
            plan_id=data.get("plan_id"),
            created_at=data["created_at"],
            expires_at=data["expires_at"],
        )

    def is_expired(self) -> bool:
        """Check if the confirmation has expired."""
        expires = datetime.fromisoformat(self.expires_at)
        return datetime.now(timezone.utc) > expires

    def get_remaining_time(self) -> timedelta:
        """Get time remaining until expiration."""
        expires = datetime.fromisoformat(self.expires_at)
        remaining = expires - datetime.now(timezone.utc)
        return max(remaining, timedelta(0))


class ConfirmationHandler:
    """Manages pending confirmations in Redis."""

    def __init__(self, timeout_minutes: int = 5):
        """
        Initialize handler.

        Args:
            timeout_minutes: How long confirmations are valid
        """
        self.redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
        self.timeout_minutes = timeout_minutes

    def create_pending_task(
        self,
        user_id: int,
        chat_id: int,
        message: str,
        target: str,
        strategy: str,
        plan_id: Optional[str] = None,
    ) -> str:
        """
        Create a pending task awaiting confirmation.

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID
            message: Original user message
            target: Agent/macro name or "planner"
            strategy: "macro", "agent", or "dynamic"
            plan_id: Plan ID if this is a plan checkpoint

        Returns:
            Task ID for the confirmation
        """
        task_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self.timeout_minutes)

        task = PendingTask(
            task_id=task_id,
            user_id=user_id,
            chat_id=chat_id,
            message=message,
            target=target,
            strategy=strategy,
            plan_id=plan_id,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
        )

        # Store in Redis with TTL
        self.redis.setex(
            f"confirm:{task_id}",
            self.timeout_minutes * 60,
            json.dumps(task.to_dict()),
        )

        # Track user's pending confirmations
        self.redis.sadd(f"user_confirms:{user_id}", task_id)
        self.redis.expire(f"user_confirms:{user_id}", self.timeout_minutes * 60)

        return task_id

    def get_pending_task(self, task_id: str) -> Optional[PendingTask]:
        """
        Get a pending task by ID.

        Args:
            task_id: The task ID

        Returns:
            PendingTask or None if not found/expired
        """
        data = self.redis.get(f"confirm:{task_id}")
        if not data:
            return None
        return PendingTask.from_dict(json.loads(data))

    def confirm(self, task_id: str, user_id: int) -> Optional[PendingTask]:
        """
        Confirm a pending task.

        Args:
            task_id: The task ID to confirm
            user_id: The user confirming (must match original user)

        Returns:
            The confirmed PendingTask, or None if not found/invalid
        """
        task = self.get_pending_task(task_id)
        if not task:
            return None

        # Verify user owns this task
        if task.user_id != user_id:
            return None

        # Delete from Redis
        self.redis.delete(f"confirm:{task_id}")
        self.redis.srem(f"user_confirms:{user_id}", task_id)

        return task

    def cancel(self, task_id: str, user_id: int) -> bool:
        """
        Cancel a pending task.

        Args:
            task_id: The task ID to cancel
            user_id: The user cancelling (must match original user)

        Returns:
            True if cancelled, False if not found/invalid
        """
        task = self.get_pending_task(task_id)
        if not task:
            return False

        # Verify user owns this task
        if task.user_id != user_id:
            return False

        # Delete from Redis
        self.redis.delete(f"confirm:{task_id}")
        self.redis.srem(f"user_confirms:{user_id}", task_id)

        return True

    def get_user_pending(self, user_id: int) -> list[PendingTask]:
        """
        Get all pending confirmations for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of pending tasks
        """
        task_ids = self.redis.smembers(f"user_confirms:{user_id}")
        tasks = []
        for task_id in task_ids:
            task = self.get_pending_task(task_id)
            if task:
                tasks.append(task)
        return tasks

    def format_confirmation_message(self, task: PendingTask, target_desc: str) -> str:
        """
        Format a confirmation request message.

        Args:
            task: The pending task
            target_desc: Human-readable description of the target

        Returns:
            Formatted message for Telegram
        """
        remaining = task.get_remaining_time()
        minutes = int(remaining.total_seconds() // 60)
        seconds = int(remaining.total_seconds() % 60)

        lines = [
            "This action requires confirmation:",
            "",
            f"**Task**: {task.message[:100]}{'...' if len(task.message) > 100 else ''}",
            f"**Strategy**: {target_desc}",
            f"**Expires in**: {minutes}m {seconds}s",
            "",
            f"Reply `/confirm_{task.task_id}` to proceed",
            f"Reply `/cancel_{task.task_id}` to abort",
        ]
        return "\n".join(lines)
