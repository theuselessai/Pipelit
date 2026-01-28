"""
Router: Data classes and parse helper for message categorization.

The actual classification is done by the aichat categorizer role via RQ worker.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
logger = logging.getLogger(__name__)


class ExecutionStrategy(Enum):
    """How a message should be executed."""

    AGENT = "agent"
    DYNAMIC_PLAN = "dynamic"
    CHAT = "chat"


@dataclass
class RouteResult:
    """Result of routing a message."""

    strategy: ExecutionStrategy
    target: str
    requires_confirmation: bool
    requires_planning: bool
    confidence: float
    original_message: str


def parse_categorizer_output(raw: str, original_message: str) -> RouteResult:
    """
    Parse JSON output from `aichat -r categorizer` into a RouteResult.

    Falls back to CHAT strategy on any parse failure.
    """
    if not raw:
        return _default_route(original_message)

    try:
        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)

        strategy_str = data.get("strategy", "chat").lower()
        target = data.get("target", "chat")
        requires_confirmation = bool(data.get("requires_confirmation", False))

        # Map strategy string to enum
        strategy_map = {
            "agent": ExecutionStrategy.AGENT,
            "dynamic": ExecutionStrategy.DYNAMIC_PLAN,
            "dynamic_plan": ExecutionStrategy.DYNAMIC_PLAN,
            "chat": ExecutionStrategy.CHAT,
        }
        strategy = strategy_map.get(strategy_str, ExecutionStrategy.CHAT)

        return RouteResult(
            strategy=strategy,
            target=target,
            requires_confirmation=requires_confirmation,
            requires_planning=strategy == ExecutionStrategy.DYNAMIC_PLAN,
            confidence=0.9,
            original_message=original_message,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse categorizer output: {e}, raw={raw!r}")
        return _default_route(original_message)


def _default_route(message: str) -> RouteResult:
    """Return a default CHAT route."""
    return RouteResult(
        strategy=ExecutionStrategy.CHAT,
        target="chat",
        requires_confirmation=False,
        requires_planning=False,
        confidence=0.5,
        original_message=message,
    )
