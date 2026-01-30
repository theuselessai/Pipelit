"""Data operation components — filter, transform, sort, limit, merge."""

from __future__ import annotations

import re

from apps.workflows.components import register


@register("filter")
def filter_factory(node):
    """Filter items from a source node output."""
    extra = node.component_config.extra_config
    source_node = extra.get("source_node")
    field = extra.get("field", "")
    operator = extra.get("operator", "eq")
    value = extra.get("value")
    node_id = node.node_id

    def filter_node(state: dict) -> dict:
        data = _get_source_data(state, source_node)
        if not isinstance(data, list):
            return {"node_outputs": {node_id: data}}

        result = [item for item in data if _match(item, field, operator, value)]
        return {"node_outputs": {node_id: result}}

    return filter_node


@register("transform")
def transform_factory(node):
    """Transform data using a field mapping."""
    extra = node.component_config.extra_config
    source_node = extra.get("source_node")
    mapping = extra.get("mapping", {})
    node_id = node.node_id

    def transform_node(state: dict) -> dict:
        data = _get_source_data(state, source_node)
        if isinstance(data, list):
            result = [_apply_mapping(item, mapping) for item in data]
        elif isinstance(data, dict):
            result = _apply_mapping(data, mapping)
        else:
            result = data
        return {"node_outputs": {node_id: result}}

    return transform_node


@register("sort")
def sort_factory(node):
    """Sort a list by a field."""
    extra = node.component_config.extra_config
    source_node = extra.get("source_node")
    field = extra.get("field", "")
    reverse = extra.get("reverse", False)
    node_id = node.node_id

    def sort_node(state: dict) -> dict:
        data = _get_source_data(state, source_node)
        if not isinstance(data, list):
            return {"node_outputs": {node_id: data}}

        result = sorted(
            data,
            key=lambda item: item.get(field, "") if isinstance(item, dict) else item,
            reverse=reverse,
        )
        return {"node_outputs": {node_id: result}}

    return sort_node


@register("limit")
def limit_factory(node):
    """Limit list to N items."""
    extra = node.component_config.extra_config
    source_node = extra.get("source_node")
    count = extra.get("count", 10)
    offset = extra.get("offset", 0)
    node_id = node.node_id

    def limit_node(state: dict) -> dict:
        data = _get_source_data(state, source_node)
        if not isinstance(data, list):
            return {"node_outputs": {node_id: data}}

        result = data[offset : offset + count]
        return {"node_outputs": {node_id: result}}

    return limit_node


@register("merge")
def merge_factory(node):
    """Merge outputs from multiple source nodes."""
    extra = node.component_config.extra_config
    source_nodes = extra.get("source_nodes", [])
    merge_strategy = extra.get("strategy", "concat")
    node_id = node.node_id

    def merge_node(state: dict) -> dict:
        outputs = state.get("node_outputs", {})
        sources = [outputs.get(sn) for sn in source_nodes if sn in outputs]

        if merge_strategy == "concat":
            result = []
            for s in sources:
                if isinstance(s, list):
                    result.extend(s)
                else:
                    result.append(s)
        elif merge_strategy == "dict":
            result = {}
            for sn in source_nodes:
                if sn in outputs:
                    result[sn] = outputs[sn]
        else:
            result = sources

        return {"node_outputs": {node_id: result}}

    return merge_node


# --- Helpers ---


def _get_source_data(state: dict, source_node: str | None):
    """Get data from a source node's output."""
    if not source_node:
        return state.get("output")
    return state.get("node_outputs", {}).get(source_node)


def _match(item, field: str, operator: str, value) -> bool:
    """Check if item matches a filter condition."""
    if isinstance(item, dict):
        item_val = item.get(field)
    else:
        item_val = item

    if operator == "eq":
        return item_val == value
    if operator == "neq":
        return item_val != value
    if operator == "gt":
        return item_val is not None and item_val > value
    if operator == "lt":
        return item_val is not None and item_val < value
    if operator == "contains":
        return value in str(item_val) if item_val else False
    if operator == "regex":
        return bool(re.search(str(value), str(item_val))) if item_val else False
    if operator == "exists":
        return item_val is not None
    return True


def _apply_mapping(item: dict, mapping: dict) -> dict:
    """Apply field mapping to a dict item."""
    if not mapping:
        return item
    result = {}
    for target_key, source_key in mapping.items():
        if isinstance(source_key, str) and source_key in item:
            result[target_key] = item[source_key]
        else:
            result[target_key] = source_key
    return result
