"""
Router: Classifies incoming messages and determines execution strategy.

Routes messages to:
- MACRO: Predefined AIChat macros for common workflows
- AGENT: Direct agent execution for simple tasks
- DYNAMIC_PLAN: LLM-based planning for complex/novel tasks
- CHAT: Regular conversation (fallback to existing chat processing)
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExecutionStrategy(Enum):
    """How a message should be executed."""

    MACRO = "macro"  # Use predefined AIChat macro
    AGENT = "agent"  # Use single agent directly
    DYNAMIC_PLAN = "dynamic"  # Use dynamic planner for complex tasks
    CHAT = "chat"  # Regular conversation (existing flow)


@dataclass
class RouteResult:
    """Result of routing a message."""

    strategy: ExecutionStrategy
    target: str  # Macro name, agent name, or "planner"/"chat"
    requires_confirmation: bool
    requires_planning: bool  # True if dynamic planner needed
    confidence: float
    original_message: str


# Pattern-based routing rules
# Format: (pattern, target, requires_confirmation)
MACRO_ROUTES: list[tuple[str, str, bool]] = [
    # Predefined workflows -> use macros
    (r"\b(commit|git commit)\s*(message)?\b", "generate-commit-message", False),
    (r"\b(daily news|news summary)\b", "daily-news-summary", False),
    (r"\b(shop|buy from)\s+woolworths\b", "shop-woolworths", True),
]

AGENT_ROUTES: list[tuple[str, str, bool]] = [
    # Browser agent tasks
    (
        r"\b(navigate|go to|open|visit)\b.*\.(com|org|net|au|io|dev)",
        "browser_agent",
        False,
    ),
    (r"\b(screenshot|take screenshot|capture screen)\b", "browser_agent", False),
    (r"\b(click|type|fill|scroll)\b.*\b(on|in|at)\b", "browser_agent", False),
    # System agent tasks
    (r"\b(disk usage|df|free space|storage)\b", "system_agent", False),
    (r"\b(list files|ls|directory|show files)\b", "system_agent", False),
    (r"\b(run|execute)\s+(command|script)\b", "system_agent", True),
    (r"\b(process|processes|ps|htop)\b", "system_agent", False),
]

COMPLEX_PATTERNS: list[str] = [
    # Multi-step tasks -> dynamic planner
    r"\b(find|search|compare|analyze).*\band\b.*(save|summarize|compare|list)\b",
    r"\b(research|investigate)\b.*\b(then|and)\b",
    r"\bstep.?by.?step\b",
    r"\b(first|then|finally|after that)\b.*\b(then|and|finally)\b",
    r"\bcompare\b.*\boptions?\b",
]

CONFIRMATION_PATTERNS: list[str] = [
    r"\b(buy|order|purchase|checkout|pay)\b",
    r"\b(delete|remove|rm\s+-rf?)\b",
    r"\b(send|submit|post)\b",
    r"\b(install|uninstall)\b",
    r"\b(reboot|shutdown|restart)\b",
]


class Router:
    """Routes incoming requests to appropriate execution strategy."""

    def __init__(
        self,
        macro_routes: Optional[list[tuple[str, str, bool]]] = None,
        agent_routes: Optional[list[tuple[str, str, bool]]] = None,
        complex_patterns: Optional[list[str]] = None,
        confirmation_patterns: Optional[list[str]] = None,
    ):
        """Initialize router with optional custom routing rules."""
        self.macro_routes = macro_routes or MACRO_ROUTES
        self.agent_routes = agent_routes or AGENT_ROUTES
        self.complex_patterns = complex_patterns or COMPLEX_PATTERNS
        self.confirmation_patterns = confirmation_patterns or CONFIRMATION_PATTERNS

    def classify(self, message: str) -> RouteResult:
        """
        Classify a message and determine execution strategy.

        Args:
            message: The user's message to classify

        Returns:
            RouteResult with strategy, target, and metadata
        """
        message_lower = message.lower().strip()

        # Check if this action requires confirmation
        requires_confirmation = any(
            re.search(p, message_lower) for p in self.confirmation_patterns
        )

        # 1. Check for macro routes first (predefined workflows)
        for pattern, macro_name, needs_confirm in self.macro_routes:
            if re.search(pattern, message_lower):
                return RouteResult(
                    strategy=ExecutionStrategy.MACRO,
                    target=macro_name,
                    requires_confirmation=needs_confirm or requires_confirmation,
                    requires_planning=False,
                    confidence=0.95,
                    original_message=message,
                )

        # 2. Check if task is complex (needs dynamic planning)
        is_complex = any(re.search(p, message_lower) for p in self.complex_patterns)

        if is_complex:
            return RouteResult(
                strategy=ExecutionStrategy.DYNAMIC_PLAN,
                target="planner",
                requires_confirmation=requires_confirmation,
                requires_planning=True,
                confidence=0.8,
                original_message=message,
            )

        # 3. Check for direct agent routes
        for pattern, agent_name, needs_confirm in self.agent_routes:
            if re.search(pattern, message_lower):
                return RouteResult(
                    strategy=ExecutionStrategy.AGENT,
                    target=agent_name,
                    requires_confirmation=needs_confirm or requires_confirmation,
                    requires_planning=False,
                    confidence=0.9,
                    original_message=message,
                )

        # 4. Default: regular chat conversation
        return RouteResult(
            strategy=ExecutionStrategy.CHAT,
            target="chat",
            requires_confirmation=False,
            requires_planning=False,
            confidence=1.0,
            original_message=message,
        )

    def is_command(self, message: str) -> bool:
        """Check if message is a Telegram command."""
        return message.startswith("/")

    def get_strategy_description(self, strategy: ExecutionStrategy) -> str:
        """Get human-readable description of a strategy."""
        descriptions = {
            ExecutionStrategy.MACRO: "Predefined workflow",
            ExecutionStrategy.AGENT: "Agent task",
            ExecutionStrategy.DYNAMIC_PLAN: "Multi-step plan",
            ExecutionStrategy.CHAT: "Conversation",
        }
        return descriptions.get(strategy, "Unknown")
