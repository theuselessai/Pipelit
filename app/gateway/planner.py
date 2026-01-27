"""
Dynamic Planner: LLM-based planning for novel/complex tasks.

Uses AIChat to decompose tasks, track progress, and adapt plans.
Plan state is persisted in Redis for reliability across restarts.
"""

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a plan step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Step:
    """A single step in a plan."""

    order: int
    agent: str
    action: str
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    depends_on: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert step to dictionary for serialization."""
        return {
            "order": self.order,
            "agent": self.agent,
            "action": self.action,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Step":
        """Create step from dictionary."""
        return cls(
            order=data["order"],
            agent=data["agent"],
            action=data["action"],
            status=StepStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            depends_on=data.get("depends_on", []),
        )


@dataclass
class Plan:
    """A multi-step execution plan."""

    plan_id: str
    user_id: int
    goal: str
    steps: list[Step]
    checkpoints: list[int]  # Steps requiring confirmation
    current_step: int = 0
    status: str = "active"

    def to_dict(self) -> dict:
        """Convert plan to dictionary for serialization."""
        return {
            "plan_id": self.plan_id,
            "user_id": self.user_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "checkpoints": self.checkpoints,
            "current_step": self.current_step,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        """Create plan from dictionary."""
        return cls(
            plan_id=data["plan_id"],
            user_id=data["user_id"],
            goal=data["goal"],
            steps=[Step.from_dict(s) for s in data["steps"]],
            checkpoints=data.get("checkpoints", []),
            current_step=data.get("current_step", 0),
            status=data.get("status", "active"),
        )

    def get_progress(self) -> tuple[int, int]:
        """Get (completed, total) step counts."""
        completed = sum(
            1
            for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return completed, len(self.steps)

    def is_complete(self) -> bool:
        """Check if all steps are done."""
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED)
            for s in self.steps
        )


class DynamicPlanner:
    """Creates and manages execution plans for complex tasks."""

    PLANNING_PROMPT = """You are a task planner. Break down this task into steps.

Available agents:
- browser_agent: Navigate websites, click, type, screenshot, extract text
- system_agent: Execute shell commands, read/write files
- research_agent: Analyze, summarize, compare information

Task: {task}

Return a JSON array of steps:
[
  {{"order": 1, "agent": "browser_agent", "action": "description of what to do"}},
  {{"order": 2, "agent": "research_agent", "action": "...", "depends_on": [1]}}
]

Rules:
- Each step should be atomic (one clear action)
- Use depends_on to specify step dependencies
- browser_agent for any web interaction
- system_agent for file/shell operations
- research_agent for analysis/summarization
- Maximum 10 steps

Return ONLY the JSON array, no other text."""

    def __init__(self):
        """Initialize planner with Redis connection."""
        self.redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
        self.plan_ttl = 3600  # 1 hour TTL for plans

    def create_plan(self, task: str, user_id: int) -> Plan:
        """
        Use LLM to decompose task into steps.

        Args:
            task: The task description
            user_id: User who requested the task

        Returns:
            Plan object with steps
        """
        prompt = self.PLANNING_PROMPT.format(task=task)

        try:
            result = subprocess.run(
                ["aichat", prompt],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Parse LLM response
            steps = self._parse_steps(result.stdout.strip())

        except subprocess.TimeoutExpired:
            logger.error("Planning timed out")
            steps = [Step(order=1, agent="browser_agent", action=task)]
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            steps = [Step(order=1, agent="browser_agent", action=task)]

        plan = Plan(
            plan_id=f"plan_{user_id}_{int(time.time())}",
            user_id=user_id,
            goal=task,
            steps=steps,
            checkpoints=self._identify_checkpoints(steps),
        )

        self._save_plan(plan)
        return plan

    def _parse_steps(self, response: str) -> list[Step]:
        """Parse LLM response into Step objects."""
        # Try to extract JSON from response
        response = response.strip()

        # Handle markdown code blocks
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            response = response[start:end].strip()

        try:
            steps_data = json.loads(response)
            if not isinstance(steps_data, list):
                raise ValueError("Expected JSON array")

            steps = []
            for s in steps_data[:10]:  # Max 10 steps
                steps.append(
                    Step(
                        order=s.get("order", len(steps) + 1),
                        agent=s.get("agent", "browser_agent"),
                        action=s.get("action", ""),
                        depends_on=s.get("depends_on", []),
                    )
                )
            return steps

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse plan: {e}, response: {response[:200]}")
            return []

    def _identify_checkpoints(self, steps: list[Step]) -> list[int]:
        """Find steps that need user confirmation."""
        checkpoint_words = [
            "checkout",
            "purchase",
            "delete",
            "send",
            "submit",
            "pay",
            "confirm",
            "order",
        ]
        return [
            s.order
            for s in steps
            if any(word in s.action.lower() for word in checkpoint_words)
        ]

    def _save_plan(self, plan: Plan) -> None:
        """Save plan state to Redis."""
        self.redis.setex(
            f"plan:{plan.plan_id}",
            self.plan_ttl,
            json.dumps(plan.to_dict()),
        )
        # Also track user's active plans
        self.redis.sadd(f"user_plans:{plan.user_id}", plan.plan_id)

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        """Load plan from Redis."""
        data = self.redis.get(f"plan:{plan_id}")
        if not data:
            return None
        return Plan.from_dict(json.loads(data))

    def get_user_plans(self, user_id: int) -> list[Plan]:
        """Get all active plans for a user."""
        plan_ids = self.redis.smembers(f"user_plans:{user_id}")
        plans = []
        for plan_id in plan_ids:
            plan = self.get_plan(plan_id)
            if plan:
                plans.append(plan)
        return plans

    def update_step(
        self,
        plan_id: str,
        step_order: int,
        status: StepStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[Plan]:
        """
        Update step status and re-plan if needed.

        Args:
            plan_id: Plan identifier
            step_order: Step number to update
            status: New status
            result: Result text (for completed steps)
            error: Error text (for failed steps)

        Returns:
            Updated plan or None if not found
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return None

        for step in plan.steps:
            if step.order == step_order:
                step.status = status
                step.result = result
                step.error = error
                break

        # If step failed, handle dependent steps
        if status == StepStatus.FAILED:
            self._handle_failure(plan, step_order)

        # Check if plan is complete
        if plan.is_complete():
            plan.status = "completed"

        self._save_plan(plan)
        return plan

    def _handle_failure(self, plan: Plan, failed_step: int) -> None:
        """Mark dependent steps as skipped after a failure."""
        logger.info(f"Step {failed_step} failed, marking dependents as skipped")

        for step in plan.steps:
            if failed_step in step.depends_on and step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED

    def get_next_step(self, plan_id: str) -> Optional[Step]:
        """
        Get next executable step (dependencies satisfied).

        Returns the first pending step whose dependencies are all completed.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return None

        completed_orders = {
            s.order for s in plan.steps if s.status == StepStatus.COMPLETED
        }

        for step in plan.steps:
            if step.status != StepStatus.PENDING:
                continue
            if all(dep in completed_orders for dep in step.depends_on):
                return step

        return None

    def cancel_plan(self, plan_id: str, user_id: int) -> bool:
        """Cancel a plan and clean up."""
        plan = self.get_plan(plan_id)
        if not plan or plan.user_id != user_id:
            return False

        plan.status = "cancelled"
        for step in plan.steps:
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED

        self._save_plan(plan)
        return True

    def format_plan_summary(self, plan: Plan) -> str:
        """Format plan as human-readable summary."""
        lines = [f"Plan: {plan.goal}", ""]

        for step in plan.steps:
            status_emoji = {
                StepStatus.PENDING: "",
                StepStatus.RUNNING: "",
                StepStatus.COMPLETED: "",
                StepStatus.FAILED: "",
                StepStatus.SKIPPED: "",
            }.get(step.status, "")

            lines.append(f"{status_emoji} Step {step.order}: {step.action}")

        completed, total = plan.get_progress()
        lines.append(f"\nProgress: {completed}/{total} steps")

        return "\n".join(lines)
