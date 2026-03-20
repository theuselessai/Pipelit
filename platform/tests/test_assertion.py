"""Tests for assertion component — rule evaluation with pass/fail routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from components.assertion import assertion_factory


def _make_node(extra_config: dict):
    """Build a mock node with the given extra_config."""
    node = MagicMock()
    node.component_config.extra_config = extra_config
    return node


class TestAssertionComponent:
    def test_all_rules_pass(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "status", "operator": "equals", "value": "active"},
                {"id": "r2", "field": "count", "operator": "gt", "value": "0"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"status": "active", "count": 5})

        assert result["_route"] == "pass"
        assert result["output"]["passed"] is True
        assert len(result["output"]["results"]) == 2
        assert all(r["passed"] for r in result["output"]["results"])

    def test_one_rule_fails(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "status", "operator": "equals", "value": "active"},
                {"id": "r2", "field": "status", "operator": "equals", "value": "deleted"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"status": "active"})

        assert result["_route"] == "fail"
        assert result["output"]["passed"] is False
        assert result["output"]["results"][0]["passed"] is True
        assert result["output"]["results"][1]["passed"] is False

    def test_multiple_rules_mixed_results(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "name", "operator": "contains", "value": "foo"},
                {"id": "r2", "field": "age", "operator": "gt", "value": "18"},
                {"id": "r3", "field": "role", "operator": "equals", "value": "admin"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"name": "foobar", "age": 10, "role": "admin"})

        assert result["_route"] == "fail"
        assert result["output"]["passed"] is False
        results = result["output"]["results"]
        assert results[0]["passed"] is True   # name contains foo
        assert results[1]["passed"] is False  # age not > 18
        assert results[2]["passed"] is True   # role equals admin

    def test_empty_rules_passes(self):
        node = _make_node({"rules": []})
        fn = assertion_factory(node)
        result = fn({"anything": "value"})

        assert result["_route"] == "pass"
        assert result["output"]["passed"] is True
        assert result["output"]["results"] == []

    def test_no_rules_key_passes(self):
        node = _make_node({})
        fn = assertion_factory(node)
        result = fn({"anything": "value"})

        assert result["_route"] == "pass"
        assert result["output"]["passed"] is True

    def test_missing_field_fails_gracefully(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "nonexistent", "operator": "equals", "value": "something"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"other_field": "value"})

        assert result["_route"] == "fail"
        assert result["output"]["passed"] is False
        assert result["output"]["results"][0]["passed"] is False
        assert result["output"]["results"][0]["actual"] is None

    def test_nested_field_resolution(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "node_outputs.agent_1.output", "operator": "contains", "value": "hello"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"node_outputs": {"agent_1": {"output": "hello world"}}})

        assert result["_route"] == "pass"
        assert result["output"]["passed"] is True

    def test_check_description_format(self):
        node = _make_node({
            "rules": [
                {"id": "r1", "field": "status", "operator": "equals", "value": "ok"},
            ],
        })
        fn = assertion_factory(node)
        result = fn({"status": "ok"})

        check = result["output"]["results"][0]
        assert check["check"] == "status equals ok"
        assert check["expected"] == "ok"
        assert check["actual"] == "ok"
