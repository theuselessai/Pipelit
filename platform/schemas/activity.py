"""Activity summary schema — transient JSON only, not persisted to DB."""

from __future__ import annotations

from pydantic import BaseModel


class ActivitySummary(BaseModel):
    """Aggregate stats for a completed execution, included in execution_completed WS event."""

    total_steps: int = 0
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    llm_calls: int = 0
    tool_invocations: int = 0
