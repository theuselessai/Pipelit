"""Tests for data operation and control flow components."""

from __future__ import annotations

from unittest.mock import MagicMock

from components.data_ops import filter_factory, merge_factory
from components.control_flow import loop_factory, wait_factory


def _make_node(extra_config: dict):
    """Build a mock node with the given extra_config."""
    node = MagicMock()
    node.component_config.extra_config = extra_config
    return node


# ── Filter ────────────────────────────────────────────────────────────────────


class TestFilter:
    def test_filter_with_rules(self):
        node = _make_node({
            "source_node": "src",
            "rules": [
                {"field": "status", "operator": "equals", "value": "active"},
            ],
        })
        fn = filter_factory(node)

        state = {
            "node_outputs": {
                "src": [
                    {"name": "a", "status": "active"},
                    {"name": "b", "status": "inactive"},
                    {"name": "c", "status": "active"},
                ],
            },
        }
        result = fn(state)
        assert len(result["filtered"]) == 2
        assert all(item["status"] == "active" for item in result["filtered"])

    def test_filter_no_rules_returns_all(self):
        node = _make_node({"source_node": "src", "rules": []})
        fn = filter_factory(node)

        state = {"node_outputs": {"src": [1, 2, 3]}}
        result = fn(state)
        assert result["filtered"] == [1, 2, 3]

    def test_filter_no_match(self):
        node = _make_node({
            "source_node": "src",
            "rules": [
                {"field": "x", "operator": "equals", "value": "never"},
            ],
        })
        fn = filter_factory(node)

        state = {"node_outputs": {"src": [{"x": "a"}, {"x": "b"}]}}
        result = fn(state)
        assert result["filtered"] == []

    def test_filter_non_list_data(self):
        node = _make_node({"source_node": "src"})
        fn = filter_factory(node)

        state = {"node_outputs": {"src": "not a list"}}
        result = fn(state)
        assert result["filtered"] == "not a list"

    def test_filter_none_source(self):
        node = _make_node({"source_node": "missing"})
        fn = filter_factory(node)

        state = {"node_outputs": {}}
        result = fn(state)
        assert result["filtered"] == []

    def test_filter_with_field_extraction(self):
        node = _make_node({
            "source_node": "src",
            "field": "items",
            "rules": [{"field": "val", "operator": "gt", "value": "5"}],
        })
        fn = filter_factory(node)

        state = {
            "node_outputs": {
                "src": {"items": [{"val": 10}, {"val": 3}, {"val": 8}]},
            },
        }
        result = fn(state)
        assert len(result["filtered"]) == 2

    def test_filter_multiple_rules_all_must_match(self):
        node = _make_node({
            "source_node": "src",
            "rules": [
                {"field": "status", "operator": "equals", "value": "active"},
                {"field": "score", "operator": "gt", "value": "50"},
            ],
        })
        fn = filter_factory(node)

        state = {
            "node_outputs": {
                "src": [
                    {"status": "active", "score": 80},
                    {"status": "active", "score": 30},
                    {"status": "inactive", "score": 90},
                ],
            },
        }
        result = fn(state)
        assert len(result["filtered"]) == 1
        assert result["filtered"][0]["score"] == 80


# ── Merge ─────────────────────────────────────────────────────────────────────


class TestMerge:
    def test_append_mode(self):
        node = _make_node({"mode": "append", "source_nodes": ["a", "b"]})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": [1, 2], "b": [3, 4]}}
        result = fn(state)
        assert result["merged"] == [1, 2, 3, 4]

    def test_append_non_list_values(self):
        node = _make_node({"mode": "append", "source_nodes": ["a", "b"]})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": "hello", "b": "world"}}
        result = fn(state)
        assert result["merged"] == ["hello", "world"]

    def test_combine_mode(self):
        node = _make_node({"mode": "combine", "source_nodes": ["a", "b"]})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": {"x": 1}, "b": {"y": 2}}}
        result = fn(state)
        assert result["merged"] == {"x": 1, "y": 2}

    def test_no_source_nodes_uses_all(self):
        node = _make_node({"mode": "append"})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": [1], "b": [2]}}
        result = fn(state)
        assert sorted(result["merged"]) == [1, 2]

    def test_single_source(self):
        node = _make_node({"mode": "append", "source_nodes": ["a"]})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": [1, 2, 3]}}
        result = fn(state)
        assert result["merged"] == [1, 2, 3]

    def test_missing_source_skipped(self):
        node = _make_node({"mode": "append", "source_nodes": ["a", "missing"]})
        fn = merge_factory(node)

        state = {"node_outputs": {"a": [1, 2]}}
        result = fn(state)
        assert result["merged"] == [1, 2]


# ── Loop ──────────────────────────────────────────────────────────────────────


class TestLoop:
    def test_extracts_array(self):
        node = _make_node({"source_node": "src"})
        fn = loop_factory(node)

        state = {"node_outputs": {"src": [1, 2, 3]}}
        result = fn(state)
        assert result["items"] == [1, 2, 3]
        assert result["results"] == []
        assert result["_loop"]["items"] == [1, 2, 3]

    def test_field_extraction(self):
        node = _make_node({"source_node": "src", "field": "data"})
        fn = loop_factory(node)

        state = {"node_outputs": {"src": {"data": ["a", "b"]}}}
        result = fn(state)
        assert result["items"] == ["a", "b"]

    def test_non_list_wraps_in_array(self):
        node = _make_node({"source_node": "src"})
        fn = loop_factory(node)

        state = {"node_outputs": {"src": "single_item"}}
        result = fn(state)
        assert result["items"] == ["single_item"]

    def test_missing_source_wraps_empty_dict(self):
        node = _make_node({"source_node": "missing"})
        fn = loop_factory(node)

        state = {"node_outputs": {}}
        result = fn(state)
        # Missing key returns default {} which gets wrapped as [{}]
        assert result["items"] == [{}]

    def test_empty_array(self):
        node = _make_node({"source_node": "src"})
        fn = loop_factory(node)

        state = {"node_outputs": {"src": []}}
        result = fn(state)
        assert result["items"] == []

    def test_no_source_node(self):
        node = _make_node({})
        fn = loop_factory(node)

        state = {"node_outputs": {}}
        result = fn(state)
        assert result["items"] == []


# ── Wait ──────────────────────────────────────────────────────────────────────


class TestWait:
    def test_seconds(self):
        node = _make_node({"duration": 5, "unit": "seconds"})
        fn = wait_factory(node)

        result = fn({})
        assert result["_delay_seconds"] == 5.0
        assert "Waited" in result["output"]

    def test_minutes(self):
        node = _make_node({"duration": 2, "unit": "minutes"})
        fn = wait_factory(node)

        result = fn({})
        assert result["_delay_seconds"] == 120.0

    def test_hours(self):
        node = _make_node({"duration": 1, "unit": "hours"})
        fn = wait_factory(node)

        result = fn({})
        assert result["_delay_seconds"] == 3600.0

    def test_default_zero_duration(self):
        node = _make_node({})
        fn = wait_factory(node)

        result = fn({})
        assert result["_delay_seconds"] == 0.0

    def test_fractional_duration(self):
        node = _make_node({"duration": 0.5, "unit": "seconds"})
        fn = wait_factory(node)

        result = fn({})
        assert result["_delay_seconds"] == 0.5
