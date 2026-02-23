"""Context window management — trimming and model context lookups."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Context window sizes by model prefix (longest-prefix-first).
MODEL_CONTEXT_WINDOWS: list[tuple[str, int]] = [
    # Anthropic
    ("claude-3-5-sonnet", 200_000),
    ("claude-3-5-haiku", 200_000),
    ("claude-3-opus", 200_000),
    ("claude-sonnet-4", 200_000),
    ("claude-opus-4", 200_000),
    ("claude-haiku-4", 200_000),
    ("claude", 200_000),
    # OpenAI
    ("gpt-4o-mini", 128_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4", 8_192),
    ("gpt-3.5-turbo", 16_384),
    ("o3-mini", 200_000),
    ("o1-mini", 128_000),
    ("o1", 200_000),
    ("o3", 200_000),
]

DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model_name: str) -> int:
    """Return the context window size for a model name via prefix match."""
    if not model_name:
        return DEFAULT_CONTEXT_WINDOW
    lower = model_name.lower()
    for prefix, window in MODEL_CONTEXT_WINDOWS:
        if lower.startswith(prefix):
            return window
    return DEFAULT_CONTEXT_WINDOW


def trim_messages_for_model(
    messages: list,
    model_name: str,
    max_completion_tokens: int | None = None,
    context_window_override: int | None = None,
) -> list:
    """Trim messages to fit within the model's context window.

    Uses LangChain's trim_messages with strategy='last' and approximate
    token counting. Always preserves the system message if present.

    Returns the original list unchanged if messages fit within budget.

    Args:
        context_window_override: When > 0, use this instead of auto-detected
            window size. Useful for custom/self-hosted models.
    """
    from langchain_core.messages import trim_messages as lc_trim_messages

    if context_window_override and context_window_override > 0:
        context_window = context_window_override
    else:
        context_window = get_context_window(model_name)
    completion_reserve = max_completion_tokens or min(16_384, context_window // 4)
    # 512 token safety margin
    budget = context_window - completion_reserve - 512

    if budget <= 0:
        logger.warning(
            "Context budget non-positive for model=%s (window=%d, reserve=%d); skipping trim",
            model_name, context_window, completion_reserve,
        )
        return messages

    try:
        trimmed = lc_trim_messages(
            messages,
            max_tokens=budget,
            strategy="last",
            token_counter="approximate",
            include_system=True,
            start_on="human",
            allow_partial=False,
        )
    except Exception:
        logger.warning(
            "trim_messages failed for model=%s; returning original %d messages",
            model_name, len(messages), exc_info=True,
        )
        return messages

    if len(trimmed) < len(messages):
        logger.warning(
            "Trimmed messages from %d to %d for model=%s (budget=%d tokens)",
            len(messages), len(trimmed), model_name, budget,
        )

    return trimmed
