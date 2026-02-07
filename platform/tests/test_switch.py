"""Tests for switch component — rule-based routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from components.switch import switch_factory


def _make_node(extra_config: dict):
    """Build a mock node with the given extra_config."""
    node = MagicMock()
    node.component_config.extra_config = extra_config
    return node


class TestRuleBasedSwitch:
    def test_first_matching_rule_wins(self):
        node = _make_node({
            "rules": [
                {"id": "route_a", "field": "category", "operator": "equals", "value": "chat"},
                {"id": "route_b", "field": "category", "operator": "equals", "value": "search"},
            ],
        })
        fn = switch_factory(node)

        result = fn({"category": "chat"})
        assert result["_route"] == "route_a"
        assert result["route"] == "route_a"

    def test_second_rule_matches(self):
        node = _make_node({
            "rules": [
                {"id": "route_a", "field": "category", "operator": "equals", "value": "chat"},
                {"id": "route_b", "field": "category", "operator": "equals", "value": "search"},
            ],
        })
        fn = switch_factory(node)

        result = fn({"category": "search"})
        assert result["_route"] == "route_b"

    def test_no_match_returns_empty_route(self):
        node = _make_node({
            "rules": [
                {"id": "route_a", "field": "category", "operator": "equals", "value": "chat"},
            ],
        })
        fn = switch_factory(node)

        result = fn({"category": "unknown"})
        assert result["_route"] == ""

    def test_no_match_with_fallback(self):
        node = _make_node({
            "rules": [
                {"id": "route_a", "field": "category", "operator": "equals", "value": "chat"},
            ],
            "enable_fallback": True,
        })
        fn = switch_factory(node)

        result = fn({"category": "unknown"})
        assert result["_route"] == "__other__"

    def test_empty_rules_list(self):
        node = _make_node({"rules": []})
        fn = switch_factory(node)

        result = fn({"category": "anything"})
        assert result["_route"] == ""

    def test_nested_field_resolution(self):
        node = _make_node({
            "rules": [
                {"id": "deep", "field": "node_outputs.cat1.category", "operator": "equals", "value": "chat"},
            ],
        })
        fn = switch_factory(node)

        result = fn({"node_outputs": {"cat1": {"category": "chat"}}})
        assert result["_route"] == "deep"

    def test_contains_operator(self):
        node = _make_node({
            "rules": [
                {"id": "found", "field": "text", "operator": "contains", "value": "hello"},
            ],
        })
        fn = switch_factory(node)

        assert switch_factory(node)({"text": "say hello world"})["_route"] == "found"
        assert switch_factory(node)({"text": "goodbye"})["_route"] == ""

    def test_gt_operator(self):
        node = _make_node({
            "rules": [
                {"id": "high", "field": "score", "operator": "gt", "value": "50"},
            ],
        })
        fn = switch_factory(node)

        assert fn({"score": 100})["_route"] == "high"
        assert fn({"score": 30})["_route"] == ""

    def test_is_empty_operator(self):
        node = _make_node({
            "rules": [
                {"id": "empty", "field": "data", "operator": "is_empty", "value": ""},
            ],
        })
        fn = switch_factory(node)

        assert fn({"data": ""})["_route"] == "empty"
        assert fn({"data": "something"})["_route"] == ""

    def test_missing_field_returns_none(self):
        node = _make_node({
            "rules": [
                {"id": "check", "field": "nonexistent", "operator": "exists", "value": ""},
            ],
        })
        fn = switch_factory(node)

        assert fn({})["_route"] == ""


class TestLegacySwitch:
    def test_condition_field_default(self):
        node = _make_node({})
        fn = switch_factory(node)

        result = fn({"route": "chat"})
        assert result["_route"] == "chat"

    def test_custom_condition_field(self):
        node = _make_node({"condition_field": "category"})
        fn = switch_factory(node)

        result = fn({"category": "search"})
        assert result["_route"] == "search"

    def test_missing_field_returns_empty(self):
        node = _make_node({"condition_field": "missing"})
        fn = switch_factory(node)

        result = fn({"other": "data"})
        assert result["_route"] == ""

    def test_condition_expression_equality(self):
        node = _make_node({"condition_expression": "state.route == 'chat'"})
        fn = switch_factory(node)

        result = fn({"route": "chat"})
        assert result["_route"] == "chat"

    def test_condition_expression_no_match(self):
        node = _make_node({"condition_expression": "state.route == 'chat'"})
        fn = switch_factory(node)

        result = fn({"route": "search"})
        assert result["_route"] == ""

    def test_condition_expression_field_reference(self):
        node = _make_node({"condition_expression": "state.route"})
        fn = switch_factory(node)

        result = fn({"route": "some_value"})
        assert result["_route"] == "some_value"
