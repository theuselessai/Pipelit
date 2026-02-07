"""Data operation components — filter, merge."""

from __future__ import annotations

from components import register


@register("filter")
def filter_factory(node):
    """Filter items from a source node output using rule-based matching."""
    from components.operators import OPERATORS

    extra = node.component_config.extra_config
    rules = extra.get("rules", [])
    source_node = extra.get("source_node")
    items_field = extra.get("field", "")

    def filter_node(state: dict) -> dict:
        data = _get_source_data(state, source_node)
        if items_field and isinstance(data, dict):
            data = data.get(items_field)
        if not isinstance(data, list):
            return {"filtered": data if data is not None else []}
        if not rules:
            return {"filtered": data}

        result = []
        for item in data:
            match_all = True
            for rule in rules:
                field_val = item.get(rule.get("field", "")) if isinstance(item, dict) else item
                op_fn = OPERATORS.get(rule.get("operator", "equals"))
                if op_fn and not op_fn(field_val, rule.get("value", "")):
                    match_all = False
                    break
            if match_all:
                result.append(item)
        return {"filtered": result}

    return filter_node


@register("merge")
def merge_factory(node):
    """Merge outputs from multiple source nodes. Modes: append (flat array) or combine (merged object)."""
    extra = node.component_config.extra_config
    mode = extra.get("mode", "append")

    def merge_node(state: dict) -> dict:
        outputs = state.get("node_outputs", {})
        source_nodes = extra.get("source_nodes", [])
        sources = [outputs[sn] for sn in source_nodes if sn in outputs] if source_nodes else list(outputs.values())

        if mode == "combine":
            result = {}
            for s in sources:
                if isinstance(s, dict):
                    result.update(s)
                else:
                    result[str(id(s))] = s
        else:  # "append" (default, also handles legacy "concat")
            result = []
            for s in sources:
                if isinstance(s, list):
                    result.extend(s)
                else:
                    result.append(s)
        return {"merged": result}

    return merge_node


# --- Helpers ---


def _get_source_data(state: dict, source_node: str | None):
    """Get data from a source node's output."""
    if not source_node:
        return state.get("output")
    return state.get("node_outputs", {}).get(source_node)
