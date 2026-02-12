"""Categorizer component — LLM-based classification into categories."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from components import register
from services.llm import resolve_llm_for_node
from services.token_usage import (
    calculate_cost,
    extract_usage_from_response,
    get_model_name_for_node,
)


@register("categorizer")
def categorizer_factory(node):
    """Build a categorizer graph node."""
    llm = resolve_llm_for_node(node)
    model_name = get_model_name_for_node(node)
    extra = node.component_config.extra_config
    categories = extra.get("categories", [])

    category_descriptions = "\n".join(
        f"- {cat['name']}: {cat.get('description', '')}" for cat in categories
    )
    category_names = [cat["name"] for cat in categories]

    system_prompt = (
        "You are a message classifier. Classify the user's message into exactly one category.\n\n"
        f"Categories:\n{category_descriptions}\n\n"
        f"Respond with ONLY a JSON object: {{\"category\": \"<name>\"}}\n"
        f"Valid category names: {category_names}"
    )

    concrete = node.component_config.concrete
    custom_prompt = getattr(concrete, "system_prompt", "")
    if custom_prompt:
        system_prompt = custom_prompt + "\n\n" + system_prompt

    def categorizer_node(state: dict) -> dict:
        messages = [SystemMessage(content=system_prompt)]
        user_messages = state.get("messages", [])
        if user_messages:
            messages.append(user_messages[-1])
        else:
            messages.append(HumanMessage(content="(no message)"))

        response = llm.invoke(messages)
        content = response.content.strip()

        # Extract token usage
        usage = extract_usage_from_response(response)
        usage["llm_calls"] = 1
        usage["cost_usd"] = calculate_cost(
            model_name, usage["input_tokens"], usage["output_tokens"]
        )

        # Parse category from response
        category = _parse_category(content, category_names)
        return {
            "_route": category,
            "_token_usage": usage,
            "category": category,
            "raw": content,
        }

    return categorizer_node


def _parse_category(content: str, valid_names: list[str]) -> str:
    """Extract category name from LLM response."""
    # Try JSON parse
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "category" in data:
            name = data["category"]
            if name in valid_names:
                return name
    except (json.JSONDecodeError, TypeError):
        pass

    # Try regex for {"category": "..."}
    match = re.search(r'"category"\s*:\s*"([^"]+)"', content)
    if match and match.group(1) in valid_names:
        return match.group(1)

    # Try exact match in content
    for name in valid_names:
        if name.lower() in content.lower():
            return name

    return valid_names[0] if valid_names else "unknown"
