"""Tests for LLM-dependent components with mocked LLM responses."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCategorizerComponent:
    """Test categorizer with mocked LLM."""

    def _make_categories(self, names):
        """Categories must be dicts with 'name' key."""
        return [{"name": n, "description": f"Category {n}"} for n in names]

    def _make_categorizer_node(self, category_names, system_prompt=""):
        node = MagicMock()
        node.component_config.extra_config = {
            "categories": self._make_categories(category_names),
        }
        node.component_config.system_prompt = system_prompt
        node.component_config.concrete = node.component_config
        node.component_config.id = 1
        return node

    def _mock_llm_response(self, content):
        response = MagicMock()
        response.content = content
        return response

    @patch("components.categorizer.resolve_llm_for_node")
    def test_categorizer_json_response(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response('{"category": "chat"}')
        mock_resolve.return_value = mock_llm

        node = self._make_categorizer_node(["chat", "search", "code"])
        fn = categorizer_factory(node)

        state = {"messages": [MagicMock(content="hello")]}
        result = fn(state)

        assert result["category"] == "chat"
        assert result["_route"] == "chat"

    @patch("components.categorizer.resolve_llm_for_node")
    def test_categorizer_plain_text_response(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response("search")
        mock_resolve.return_value = mock_llm

        node = self._make_categorizer_node(["chat", "search", "code"])
        fn = categorizer_factory(node)

        state = {"messages": [MagicMock(content="find me something")]}
        result = fn(state)

        assert result["category"] == "search"

    @patch("components.categorizer.resolve_llm_for_node")
    def test_categorizer_defaults_to_first(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response("gibberish_not_a_category")
        mock_resolve.return_value = mock_llm

        node = self._make_categorizer_node(["chat", "search"])
        fn = categorizer_factory(node)

        state = {"messages": [MagicMock(content="test")]}
        result = fn(state)

        assert result["category"] == "chat"  # Falls back to first

    @patch("components.categorizer.resolve_llm_for_node")
    def test_categorizer_outputs_raw_response(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response('{"category": "code"}')
        mock_resolve.return_value = mock_llm

        node = self._make_categorizer_node(["chat", "code"])
        fn = categorizer_factory(node)

        state = {"messages": [MagicMock(content="test")]}
        result = fn(state)

        assert result["raw"] == '{"category": "code"}'


class TestRouterComponent:
    """Test router — pure logic, no LLM needed."""

    def _make_router_node(self, extra_config):
        node = MagicMock()
        node.component_config.extra_config = extra_config
        return node

    def test_field_lookup_default(self):
        from components.router import router_factory

        node = self._make_router_node({})
        fn = router_factory(node)

        result = fn({"route": "chat"})
        assert result["_route"] == "chat"
        assert result["route"] == "chat"

    def test_custom_field(self):
        from components.router import router_factory

        node = self._make_router_node({"condition_field": "category"})
        fn = router_factory(node)

        result = fn({"category": "search"})
        assert result["_route"] == "search"

    def test_expression_equality(self):
        from components.router import router_factory

        node = self._make_router_node({"condition_expression": "state.route == 'chat'"})
        fn = router_factory(node)

        assert fn({"route": "chat"})["_route"] == "chat"
        assert fn({"route": "search"})["_route"] == ""

    def test_expression_field_reference(self):
        from components.router import router_factory

        node = self._make_router_node({"condition_expression": "state.node_outputs.cat.category"})
        fn = router_factory(node)

        result = fn({"node_outputs": {"cat": {"category": "agent"}}})
        assert result["_route"] == "agent"


class TestCodeComponent:
    """Test code execution component."""

    def _make_code_node(self, code, language="python"):
        node = MagicMock()
        node.component_config.extra_config = {"code": code, "language": language}
        node.component_config.code_snippet = code
        node.component_config.code_language = language
        return node

    def test_simple_result(self):
        from components.code import code_factory

        node = self._make_code_node("result = 42")
        fn = code_factory(node)

        result = fn({"node_outputs": {}})
        # code component stringifies result via str()
        assert result["output"] == "42"

    def test_access_state(self):
        from components.code import code_factory

        node = self._make_code_node("result = state.get('my_key', 'default')")
        fn = code_factory(node)

        result = fn({"my_key": "hello", "node_outputs": {}})
        assert result["output"] == "hello"

    def test_access_node_outputs(self):
        from components.code import code_factory

        node = self._make_code_node("result = node_outputs.get('upstream', {}).get('val')")
        fn = code_factory(node)

        result = fn({"node_outputs": {"upstream": {"val": 99}}})
        assert result["output"] == "99"

    def test_return_statement(self):
        from components.code import code_factory

        node = self._make_code_node("return 'from_return'")
        fn = code_factory(node)

        result = fn({"node_outputs": {}})
        assert result["output"] == "from_return"

    def test_list_result(self):
        from components.code import code_factory

        node = self._make_code_node("result = [1, 2, 3]")
        fn = code_factory(node)

        result = fn({"node_outputs": {}})
        assert result["output"] == "[1, 2, 3]"

    def test_error_raises(self):
        from components.code import code_factory

        node = self._make_code_node("raise ValueError('test error')")
        fn = code_factory(node)

        with pytest.raises(Exception):
            fn({"node_outputs": {}})


class TestSwitchWithFullState:
    """Integration test: switch operating on node_outputs from upstream."""

    def test_switch_reads_upstream_output(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.component_config.extra_config = {
            "rules": [
                {"id": "chat_route", "field": "node_outputs.categorizer.category",
                 "operator": "equals", "value": "chat"},
                {"id": "search_route", "field": "node_outputs.categorizer.category",
                 "operator": "equals", "value": "search"},
            ],
        }
        fn = switch_factory(node)

        state = {"node_outputs": {"categorizer": {"category": "search"}}}
        result = fn(state)
        assert result["_route"] == "search_route"

    def test_switch_with_numeric_comparison(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.component_config.extra_config = {
            "rules": [
                {"id": "high", "field": "node_outputs.scorer.score",
                 "operator": "gte", "value": "80"},
                {"id": "low", "field": "node_outputs.scorer.score",
                 "operator": "lt", "value": "80"},
            ],
        }
        fn = switch_factory(node)

        assert fn({"node_outputs": {"scorer": {"score": 95}}})["_route"] == "high"
        assert fn({"node_outputs": {"scorer": {"score": 50}}})["_route"] == "low"
