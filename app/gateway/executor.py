"""
Executor: Enqueues tasks to RQ workers based on routing decisions.

Handles:
- Macro execution
- Agent execution
- Dynamic plan execution
- Regular chat fallback
"""

import logging
from typing import Optional

from redis import Redis
from rq import Queue

from app.config import settings
from app.gateway.planner import DynamicPlanner
from app.gateway.router import ExecutionStrategy, RouteResult

logger = logging.getLogger(__name__)


class Executor:
    """Executes tasks via RQ workers."""

    def __init__(self):
        """Initialize executor with Redis connection and queues."""
        self.redis = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
        )
        self.queues = {
            "browser": Queue("browser", connection=self.redis),
            "default": Queue("default", connection=self.redis),
            "high": Queue("high", connection=self.redis),
            "low": Queue("low", connection=self.redis),
        }
        self.planner = DynamicPlanner()

    def execute(
        self,
        route: RouteResult,
        user_id: int,
        chat_id: int,
        message_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Execute based on routing result.

        Args:
            route: RouteResult from Router.classify()
            user_id: Telegram user ID
            chat_id: Telegram chat ID
            message_id: Original message ID (for replies)
            session_id: Session ID for agent conversations

        Returns:
            Job ID of the enqueued task
        """
        session_id = session_id or f"user_{user_id}"

        if route.strategy == ExecutionStrategy.MACRO:
            return self._enqueue_macro(
                route.target, route.original_message, user_id, chat_id, message_id
            )

        elif route.strategy == ExecutionStrategy.AGENT:
            return self._enqueue_agent(
                route.target,
                route.original_message,
                user_id,
                chat_id,
                session_id,
                message_id,
            )

        elif route.strategy == ExecutionStrategy.DYNAMIC_PLAN:
            return self._enqueue_plan(
                route.original_message, user_id, chat_id, session_id, message_id
            )

        else:  # CHAT
            return self._enqueue_chat(
                route.original_message, user_id, chat_id, message_id
            )

    def _enqueue_macro(
        self,
        macro: str,
        message: str,
        user_id: int,
        chat_id: int,
        message_id: Optional[int],
    ) -> str:
        """Enqueue a macro execution."""
        from app.tasks.agent_tasks import run_macro_task

        job = self.queues["default"].enqueue(
            run_macro_task,
            macro=macro,
            args=message,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued macro '{macro}' as job {job.id}")
        return job.id

    def _enqueue_agent(
        self,
        agent: str,
        message: str,
        user_id: int,
        chat_id: int,
        session_id: str,
        message_id: Optional[int],
    ) -> str:
        """Enqueue a single agent task."""
        from app.tasks.agent_tasks import run_agent_task

        # Browser agent uses dedicated queue (single worker for Playwright)
        queue = self.queues["browser"] if agent == "browser_agent" else self.queues["default"]

        job = queue.enqueue(
            run_agent_task,
            agent=agent,
            message=message,
            user_id=user_id,
            chat_id=chat_id,
            session_id=session_id,
            message_id=message_id,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued agent '{agent}' as job {job.id}")
        return job.id

    def _enqueue_plan(
        self,
        message: str,
        user_id: int,
        chat_id: int,
        session_id: str,
        message_id: Optional[int],
    ) -> str:
        """Create plan and enqueue first step."""
        from app.tasks.agent_tasks import run_plan_step

        # Create the plan
        plan = self.planner.create_plan(message, user_id)

        if not plan.steps:
            # Fallback to regular chat if planning failed
            logger.warning("Planning failed, falling back to chat")
            return self._enqueue_chat(message, user_id, chat_id, message_id)

        # Enqueue first step execution
        job = self.queues["default"].enqueue(
            run_plan_step,
            plan_id=plan.plan_id,
            user_id=user_id,
            chat_id=chat_id,
            session_id=session_id,
            message_id=message_id,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued plan '{plan.plan_id}' first step as job {job.id}")
        return job.id

    def _enqueue_chat(
        self, message: str, user_id: int, chat_id: int, message_id: Optional[int]
    ) -> str:
        """Enqueue regular chat processing (existing flow)."""
        from app.tasks.chat import process_chat_message

        job = self.queues["default"].enqueue(
            process_chat_message,
            chat_id=chat_id,
            user_id=user_id,
            message=message,
            message_id=message_id or 0,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued chat message as job {job.id}")
        return job.id

    def enqueue_next_plan_step(
        self,
        plan_id: str,
        user_id: int,
        chat_id: int,
        session_id: str,
    ) -> Optional[str]:
        """
        Enqueue the next step in a plan.

        Called by plan step tasks after completing a step.

        Returns:
            Job ID if there's a next step, None if plan is complete
        """
        from app.tasks.agent_tasks import run_plan_step

        next_step = self.planner.get_next_step(plan_id)
        if not next_step:
            return None

        job = self.queues["default"].enqueue(
            run_plan_step,
            plan_id=plan_id,
            user_id=user_id,
            chat_id=chat_id,
            session_id=session_id,
            message_id=None,
            job_timeout=settings.JOB_TIMEOUT,
        )
        logger.info(f"Enqueued plan '{plan_id}' step {next_step.order} as job {job.id}")
        return job.id
