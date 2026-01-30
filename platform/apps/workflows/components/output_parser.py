"""Output parser component — extract structured data from previous node output."""

from __future__ import annotations

import json
import re

from apps.workflows.components import register


@register("output_parser")
def output_parser_factory(node):
    """Build an output_parser graph node."""
    extra = node.component_config.extra_config
    parser_type = extra.get("parser_type", "json")
    source_node = extra.get("source_node")
    pattern = extra.get("pattern", "")
    node_id = node.node_id

    def output_parser_node(state: dict) -> dict:
        raw = _get_raw(state, source_node)
        if raw is None:
            return {"node_outputs": {node_id: None}}

        text = str(raw)

        if parser_type == "json":
            result = _parse_json(text)
        elif parser_type == "regex":
            result = _parse_regex(text, pattern)
        elif parser_type == "list":
            result = _parse_list(text)
        else:
            result = text

        return {"node_outputs": {node_id: result}}

    return output_parser_node


def _get_raw(state: dict, source_node: str | None):
    if source_node:
        return state.get("node_outputs", {}).get(source_node)
    messages = state.get("messages", [])
    return messages[-1].content if messages else None


def _parse_json(text: str):
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting JSON from markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    return text


def _parse_regex(text: str, pattern: str):
    matches = re.findall(pattern, text)
    return matches if matches else text


def _parse_list(text: str) -> list[str]:
    lines = text.strip().split("\n")
    result = []
    for line in lines:
        line = re.sub(r"^[\s\-\*\d.)+]+", "", line).strip()
        if line:
            result.append(line)
    return result
