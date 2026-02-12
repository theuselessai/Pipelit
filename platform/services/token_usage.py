"""Token usage extraction, pricing, and cost calculation utilities."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Pricing table: (model_prefix, input_cost_per_1M_tokens, output_cost_per_1M_tokens)
# Ordered longest-prefix-first so more specific prefixes match before generic ones.
MODEL_PRICING: list[tuple[str, float, float]] = [
    # OpenAI
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("gpt-4-turbo", 10.00, 30.00),
    ("gpt-4", 30.00, 60.00),
    ("gpt-3.5-turbo", 0.50, 1.50),
    ("o3-mini", 1.10, 4.40),
    ("o1-mini", 3.00, 12.00),
    ("o1", 15.00, 60.00),
    # Anthropic
    ("claude-3-5-sonnet", 3.00, 15.00),
    ("claude-3-5-haiku", 0.80, 4.00),
    ("claude-3-opus", 15.00, 75.00),
    ("claude-sonnet-4", 3.00, 15.00),
    ("claude-opus-4", 15.00, 75.00),
]


def get_model_pricing(model_name: str) -> tuple[float, float]:
    """Return (input_cost_per_1M, output_cost_per_1M) for a model name via prefix match.

    Unknown models return (0.0, 0.0) — tokens are tracked but cost is $0.
    """
    if not model_name:
        return (0.0, 0.0)
    lower = model_name.lower()
    for prefix, input_cost, output_cost in MODEL_PRICING:
        if lower.startswith(prefix):
            return (input_cost, output_cost)
    return (0.0, 0.0)


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for a given model and token counts."""
    input_rate, output_rate = get_model_pricing(model_name)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def extract_usage_from_response(response) -> dict:
    """Extract token usage from a single AIMessage (or similar LangChain response).

    Returns dict with input_tokens, output_tokens, total_tokens.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        return {
            "input_tokens": input_t,
            "output_tokens": output_t,
            "total_tokens": input_t + output_t,
        }
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def extract_usage_from_messages(messages: list) -> dict:
    """Extract and sum token usage from a list of messages.

    Counts AI messages with usage_metadata as llm_calls.
    Returns dict with input_tokens, output_tokens, total_tokens, llm_calls.
    """
    total_input = 0
    total_output = 0
    llm_calls = 0

    for msg in messages:
        if not (hasattr(msg, "type") and msg.type == "ai"):
            continue
        usage = getattr(msg, "usage_metadata", None)
        if not usage or not isinstance(usage, dict):
            continue
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        total_input += input_t
        total_output += output_t
        llm_calls += 1

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "llm_calls": llm_calls,
    }


def merge_usage(existing: dict, new: dict) -> dict:
    """Merge two token usage dicts by summing all numeric fields."""
    merged = {}
    all_keys = set(existing.keys()) | set(new.keys())
    for k in all_keys:
        ev = existing.get(k, 0)
        nv = new.get(k, 0)
        if isinstance(ev, (int, float)) and isinstance(nv, (int, float)):
            merged[k] = ev + nv
        else:
            merged[k] = nv  # non-numeric: take the new value
    return merged


def get_model_name_for_node(node) -> str:
    """Resolve the model name string for a node by following its llm_model_config_id chain.

    Same resolution logic as resolve_llm_for_node() but returns the model name
    string instead of creating the LLM instance.
    """
    cc = node.component_config
    if getattr(cc, "component_type", None) == "ai_model":
        return getattr(cc, "model_name", None) or ""

    llm_config_id = getattr(cc, "llm_model_config_id", None)
    if llm_config_id and isinstance(llm_config_id, int):
        try:
            from database import SessionLocal
            from models.node import BaseComponentConfig as BCC

            db = SessionLocal()
            try:
                tc = db.get(BCC, llm_config_id)
                if tc and tc.component_type == "ai_model" and tc.model_name:
                    return tc.model_name
            finally:
                db.close()
        except Exception:
            logger.debug("Could not resolve model name for node via llm_model_config_id=%s", llm_config_id)

    return ""
