"""Tests for remaining components: code, control_flow, data_ops, operators,
categorizer, router, output_parser, memory_read, memory_write, agent."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, Mock

import pytest


def _make_node(component_type="test", extra_config=None, system_prompt=None, node_id="test_1"):
    concrete = SimpleNamespace(
        system_prompt=system_prompt or "",
        extra_config=extra_config or {},
    )
    config = SimpleNamespace(
        component_type=component_type,
        extra_config=extra_config or {},
        system_prompt=system_prompt or "",
        concrete=concrete,
    )
    return SimpleNamespace(
        node_id=node_id,
        workflow_id=1,
        component_type=component_type,
        component_config=config,
    )


# ── Operators ─────────────────────────────────────────────────────────────────

class TestOperators:
    def test_equals(self):
        from components.operators import OPERATORS
        assert OPERATORS["equals"]("abc", "abc") is True
        assert OPERATORS["equals"]("abc", "def") is False
        assert OPERATORS["equals"](1, 1) is True

    def test_not_equals(self):
        from components.operators import OPERATORS
        assert OPERATORS["not_equals"]("a", "b") is True
        assert OPERATORS["not_equals"]("a", "a") is False

    def test_contains(self):
        from components.operators import OPERATORS
        assert OPERATORS["contains"]("hello world", "world") is True
        assert OPERATORS["contains"]([1, 2, 3], 2) is True
        assert OPERATORS["contains"]("abc", "z") is False

    def test_not_contains(self):
        from components.operators import OPERATORS
        assert OPERATORS["not_contains"]("hello", "xyz") is True
        assert OPERATORS["not_contains"]("hello", "ell") is False

    def test_starts_with(self):
        from components.operators import OPERATORS
        assert OPERATORS["starts_with"]("hello world", "hello") is True
        assert OPERATORS["starts_with"]("hello world", "world") is False

    def test_ends_with(self):
        from components.operators import OPERATORS
        assert OPERATORS["ends_with"]("hello world", "world") is True
        assert OPERATORS["ends_with"]("hello world", "hello") is False

    def test_gt(self):
        from components.operators import OPERATORS
        assert OPERATORS["gt"](10, 5) is True
        assert OPERATORS["gt"](5, 10) is False
        assert OPERATORS["gt"]("10", "5") is True

    def test_gte(self):
        from components.operators import OPERATORS
        assert OPERATORS["gte"](10, 10) is True
        assert OPERATORS["gte"](10, 5) is True

    def test_lt(self):
        from components.operators import OPERATORS
        assert OPERATORS["lt"](3, 5) is True
        assert OPERATORS["lt"](5, 3) is False

    def test_lte(self):
        from components.operators import OPERATORS
        assert OPERATORS["lte"](5, 5) is True
        assert OPERATORS["lte"](3, 5) is True

    def test_is_empty(self):
        from components.operators import OPERATORS
        assert OPERATORS["is_empty"](None, None) is True
        assert OPERATORS["is_empty"]("", None) is True
        assert OPERATORS["is_empty"]([], None) is True
        assert OPERATORS["is_empty"]({}, None) is True
        assert OPERATORS["is_empty"]("hello", None) is False

    def test_is_not_empty(self):
        from components.operators import OPERATORS
        assert OPERATORS["is_not_empty"]("hello", None) is True
        assert OPERATORS["is_not_empty"]("", None) is False

    def test_exists(self):
        from components.operators import OPERATORS
        assert OPERATORS["exists"]("anything", None) is True
        assert OPERATORS["exists"](None, None) is False

    def test_matches_regex(self):
        from components.operators import OPERATORS
        assert OPERATORS["matches_regex"]("abc123", r"\d+") is True
        assert OPERATORS["matches_regex"]("abc", r"\d+") is False

    def test_is_true_is_false(self):
        from components.operators import OPERATORS
        assert OPERATORS["is_true"](True, None) is True
        assert OPERATORS["is_true"]("true", None) is True
        assert OPERATORS["is_false"](False, None) is True
        assert OPERATORS["is_false"]("0", None) is True

    def test_length_operators(self):
        from components.operators import OPERATORS
        assert OPERATORS["length_eq"]([1, 2, 3], 3) is True
        assert OPERATORS["length_gt"]([1, 2, 3], 2) is True
        assert OPERATORS["length_lt"]([1], 2) is True

    def test_resolve_field(self):
        from components.operators import _resolve_field
        data = {"a": {"b": {"c": 42}}}
        assert _resolve_field("a.b.c", data) == 42
        assert _resolve_field("a.b", data) == {"c": 42}
        assert _resolve_field("x.y", data) is None

    def test_resolve_field_strips_state_prefix(self):
        from components.operators import _resolve_field
        data = {"a": 1}
        assert _resolve_field("state.a", data) == 1

    def test_to_num(self):
        from components.operators import _to_num
        assert _to_num("42") == 42.0
        assert _to_num(3.14) == 3.14
        assert _to_num("not_a_number") is None

    def test_to_bool(self):
        from components.operators import _to_bool
        assert _to_bool("true") is True
        assert _to_bool("false") is False
        assert _to_bool("1") is True
        assert _to_bool("0") is False

    def test_to_dt(self):
        from components.operators import _to_dt
        from datetime import datetime
        result = _to_dt("2024-01-15T10:30:00")
        assert isinstance(result, datetime)
        assert _to_dt("not a date") is None
        assert _to_dt(42) is None

    def test_datetime_operators(self):
        from components.operators import OPERATORS
        assert OPERATORS["after"]("2024-06-01", "2024-01-01") is True
        assert OPERATORS["before"]("2024-01-01", "2024-06-01") is True


# ── Code component ────────────────────────────────────────────────────────────

class TestCodeComponent:
    def _factory(self, code="", language="python"):
        from components.code import code_factory
        return code_factory(_make_node("code", extra_config={"code": code, "language": language}))

    def test_simple_result(self):
        fn = self._factory("result = 2 + 2")
        result = fn({"node_outputs": {}})
        assert result["output"] == "4"

    def test_print_output(self):
        fn = self._factory("print('hello')")
        result = fn({"node_outputs": {}})
        assert "hello" in result["output"]

    def test_access_state(self):
        fn = self._factory("result = state.get('trigger', {}).get('text', 'none')")
        result = fn({"trigger": {"text": "hi"}, "node_outputs": {}})
        assert result["output"] == "hi"

    def test_access_node_outputs(self):
        fn = self._factory("result = node_outputs.get('prev', {}).get('out', 'missing')")
        result = fn({"node_outputs": {"prev": {"out": "data"}}})
        assert result["output"] == "data"

    def test_empty_code_raises(self):
        fn = self._factory("")
        with pytest.raises(ValueError, match="No code provided"):
            fn({"node_outputs": {}})

    def test_error_handling(self):
        fn = self._factory("raise ValueError('boom')")
        with pytest.raises(RuntimeError, match="boom"):
            fn({"node_outputs": {}})

    def test_json_result(self):
        fn = self._factory('result = {"key": "value"}')
        result = fn({"node_outputs": {}})
        assert "key" in result["output"]

    def test_return_syntax(self):
        fn = self._factory("return 42")
        result = fn({"node_outputs": {}})
        assert result["output"] == "42"

    def test_unsupported_language(self):
        fn = self._factory("echo hello", language="bash")
        with pytest.raises(ValueError, match="not yet supported"):
            fn({"node_outputs": {}})


# ── Control Flow ──────────────────────────────────────────────────────────────

class TestLoopComponent:
    def _factory(self, **extra):
        from components.control_flow import loop_factory
        return loop_factory(_make_node("loop", extra_config=extra))

    def test_loop_from_source(self):
        fn = self._factory(source_node="prev", field="items")
        result = fn({"node_outputs": {"prev": {"items": [1, 2, 3]}}})
        assert result["_loop"]["items"] == [1, 2, 3]
        assert result["items"] == [1, 2, 3]

    def test_loop_empty_items(self):
        fn = self._factory(source_node="prev", field="items")
        result = fn({"node_outputs": {"prev": {"items": []}}})
        assert result["_loop"]["items"] == []

    def test_loop_missing_source(self):
        fn = self._factory(source_node="missing", field="items")
        result = fn({"node_outputs": {}})
        assert result["_loop"]["items"] == []

    def test_loop_missing_field(self):
        fn = self._factory(source_node="prev", field="nonexistent")
        result = fn({"node_outputs": {"prev": {"other": "data"}}})
        assert result["_loop"]["items"] == []


class TestWaitComponent:
    def _factory(self, **extra):
        from components.control_flow import wait_factory
        return wait_factory(_make_node("wait", extra_config=extra))

    def test_seconds(self):
        fn = self._factory(duration=5, unit="seconds")
        result = fn({})
        assert result["_delay_seconds"] == 5

    def test_minutes(self):
        fn = self._factory(duration=2, unit="minutes")
        result = fn({})
        assert result["_delay_seconds"] == 120

    def test_hours(self):
        fn = self._factory(duration=1, unit="hours")
        result = fn({})
        assert result["_delay_seconds"] == 3600

    def test_default(self):
        fn = self._factory(duration=10)
        result = fn({})
        assert result["_delay_seconds"] == 10


class TestErrorHandlerComponent:
    def test_not_implemented(self):
        from components.control_flow import error_handler_factory
        fn = error_handler_factory(_make_node("error_handler"))
        with pytest.raises(NotImplementedError):
            fn({})


# ── Switch ────────────────────────────────────────────────────────────────────

class TestSwitchComponent:
    def _factory(self, **extra):
        from components.switch import switch_factory
        return switch_factory(_make_node("switch", extra_config=extra))

    def test_matching_rule(self):
        fn = self._factory(
            rules=[
                {"id": "spam_route", "field": "category", "operator": "equals", "value": "spam"},
                {"id": "ham_route", "field": "category", "operator": "equals", "value": "ham"},
            ],
        )
        result = fn({"category": "spam"})
        assert result["_route"] == "spam_route"
        assert result["route"] == "spam_route"

    def test_no_match_no_fallback(self):
        fn = self._factory(
            rules=[
                {"id": "a", "field": "x", "operator": "equals", "value": "never"},
            ],
            enable_fallback=False,
        )
        result = fn({"x": "other"})
        assert result["_route"] == ""

    def test_no_match_with_fallback(self):
        fn = self._factory(
            rules=[
                {"id": "a", "field": "x", "operator": "equals", "value": "never"},
            ],
            enable_fallback=True,
        )
        result = fn({"x": "other"})
        assert result["_route"] == "__other__"

    def test_legacy_mode(self):
        fn = self._factory(condition_field="route")
        result = fn({"route": "branch_a"})
        assert result["_route"] == "branch_a"

    def test_legacy_expression(self):
        fn = self._factory(condition_expression="state.route == 'chat'")
        result = fn({"route": "chat"})
        assert result["_route"] == "chat"


# ── Data Ops ──────────────────────────────────────────────────────────────────

class TestFilterComponent:
    def _factory(self, **extra):
        from components.data_ops import filter_factory
        return filter_factory(_make_node("filter", extra_config=extra))

    def test_filter_equals(self):
        fn = self._factory(
            source_node="prev",
            field="items",
            rules=[{"field": "status", "operator": "equals", "value": "active"}],
        )
        items = [{"status": "active", "id": 1}, {"status": "inactive", "id": 2}]
        result = fn({"node_outputs": {"prev": {"items": items}}})
        assert len(result["filtered"]) == 1
        assert result["filtered"][0]["id"] == 1

    def test_filter_empty_rules(self):
        fn = self._factory(source_node="prev", field="items", rules=[])
        items = [1, 2, 3]
        result = fn({"node_outputs": {"prev": {"items": items}}})
        assert len(result["filtered"]) == 3


class TestMergeComponent:
    def _factory(self, **extra):
        from components.data_ops import merge_factory
        return merge_factory(_make_node("merge", extra_config=extra))

    def test_merge_append(self):
        fn = self._factory()
        result = fn({"node_outputs": {"a": {"x": 1}, "b": {"y": 2}}})
        assert "merged" in result
        assert isinstance(result["merged"], list)

    def test_merge_combine(self):
        fn = self._factory(mode="combine")
        result = fn({"node_outputs": {"a": {"x": 1}, "b": {"y": 2}}})
        assert "merged" in result
        assert isinstance(result["merged"], dict)
        assert result["merged"]["x"] == 1
        assert result["merged"]["y"] == 2


# ── Categorizer ───────────────────────────────────────────────────────────────

class TestCategorizer:
    @patch("components.categorizer.resolve_llm_for_node")
    def test_basic(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="spam")
        mock_resolve.return_value = mock_llm

        node = _make_node("categorizer", extra_config={
            "categories": [
                {"name": "spam", "description": "Spam messages"},
                {"name": "ham", "description": "Normal messages"},
            ]
        })
        fn = categorizer_factory(node)
        result = fn({"messages": [MagicMock(content="buy now")]})
        assert result["category"] == "spam"
        assert result["_route"] == "spam"

    @patch("components.categorizer.resolve_llm_for_node")
    def test_unknown_category(self, mock_resolve):
        from components.categorizer import categorizer_factory

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="completely_random_xyz")
        mock_resolve.return_value = mock_llm

        node = _make_node("categorizer", extra_config={
            "categories": [
                {"name": "alpha", "description": "A"},
                {"name": "beta", "description": "B"},
            ]
        })
        fn = categorizer_factory(node)
        result = fn({"messages": []})
        # Falls back to first category when nothing matches
        assert result["category"] == "alpha"


class TestParseCategory:
    def test_exact_match(self):
        from components.categorizer import _parse_category
        assert _parse_category("spam", ["spam", "ham"]) == "spam"

    def test_case_insensitive(self):
        from components.categorizer import _parse_category
        assert _parse_category("SPAM", ["spam", "ham"]) == "spam"

    def test_json_format(self):
        from components.categorizer import _parse_category
        assert _parse_category('{"category": "spam"}', ["spam", "ham"]) == "spam"

    def test_no_match_falls_back_to_first(self):
        from components.categorizer import _parse_category
        result = _parse_category("completely_unknown_xyz", ["spam", "ham"])
        assert result == "spam"

    def test_no_match_empty_list(self):
        from components.categorizer import _parse_category
        result = _parse_category("xyz", [])
        assert result == "unknown"


# ── Router ────────────────────────────────────────────────────────────────────

class TestRouter:
    def test_basic_routing_from_state(self):
        from components.router import router_factory

        node = _make_node("router", extra_config={"condition_field": "route"})
        fn = router_factory(node)
        result = fn({"route": "branch_a"})
        assert result["_route"] == "branch_a"
        assert result["route"] == "branch_a"

    def test_routing_with_expression(self):
        from components.router import router_factory

        node = _make_node("router", extra_config={
            "condition_expression": "state.route == 'chat'"
        })
        fn = router_factory(node)
        result = fn({"route": "chat"})
        assert result["_route"] == "chat"

    def test_routing_expression_no_match(self):
        from components.router import router_factory

        node = _make_node("router", extra_config={
            "condition_expression": "state.route == 'chat'"
        })
        fn = router_factory(node)
        result = fn({"route": "other"})
        assert result["_route"] == ""


# ── Output Parser ─────────────────────────────────────────────────────────────

class TestOutputParser:
    def _factory(self, **extra):
        from components.output_parser import output_parser_factory
        return output_parser_factory(_make_node("output_parser", extra_config=extra, node_id="parser_1"))

    def test_json_parse(self):
        fn = self._factory(parser_type="json", source_node="prev")
        result = fn({
            "node_outputs": {"prev": '{"key": "value"}'},
            "messages": [],
        })
        assert result["node_outputs"]["parser_1"]["key"] == "value"

    def test_list_parse(self):
        fn = self._factory(parser_type="list", source_node="prev")
        result = fn({
            "node_outputs": {"prev": "- item 1\n- item 2\n- item 3"},
            "messages": [],
        })
        parsed = result["node_outputs"]["parser_1"]
        assert isinstance(parsed, list)
        assert len(parsed) == 3

    def test_regex_parse(self):
        fn = self._factory(parser_type="regex", source_node="prev", pattern=r"\d+")
        result = fn({
            "node_outputs": {"prev": "age: 25, score: 100"},
            "messages": [],
        })
        parsed = result["node_outputs"]["parser_1"]
        assert "25" in parsed
        assert "100" in parsed

    def test_no_source_uses_messages(self):
        fn = self._factory(parser_type="json")
        result = fn({
            "node_outputs": {},
            "messages": [MagicMock(content='{"a": 1}')],
        })
        assert result["node_outputs"]["parser_1"]["a"] == 1

    def test_no_source_no_messages(self):
        fn = self._factory(parser_type="json")
        result = fn({
            "node_outputs": {},
            "messages": [],
        })
        assert result["node_outputs"]["parser_1"] is None


# ── Memory Read ───────────────────────────────────────────────────────────────

class TestMemoryRead:
    @patch("components.memory_read.SessionLocal")
    @patch("components.memory_read.MemoryService")
    def test_recall_by_key(self, mock_mem_cls, mock_session_cls):
        from components.memory_read import memory_read_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_mem = MagicMock()
        mock_mem.get_fact.return_value = "coffee"
        mock_mem_cls.return_value = mock_mem

        node = _make_node("memory_read", extra_config={"memory_type": "facts"})
        tool = memory_read_factory(node)
        result = tool.invoke({"key": "favorite_drink"})
        assert "coffee" in result

    @patch("components.memory_read.SessionLocal")
    @patch("components.memory_read.MemoryService")
    def test_recall_by_query(self, mock_mem_cls, mock_session_cls):
        from components.memory_read import memory_read_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_mem = MagicMock()
        mock_fact = MagicMock()
        mock_fact.key = "drink"
        mock_fact.value = "coffee"
        mock_fact.confidence = 0.9
        mock_mem.search_facts.return_value = [mock_fact]
        mock_mem_cls.return_value = mock_mem

        node = _make_node("memory_read", extra_config={"memory_type": "facts"})
        tool = memory_read_factory(node)
        result = tool.invoke({"query": "preferences"})
        assert "coffee" in result

    @patch("components.memory_read.SessionLocal")
    @patch("components.memory_read.MemoryService")
    def test_recall_no_key_no_query(self, mock_mem_cls, mock_session_cls):
        from components.memory_read import memory_read_factory

        node = _make_node("memory_read", extra_config={})
        tool = memory_read_factory(node)
        result = tool.invoke({})
        assert "Error" in result or "must be provided" in result

    @patch("components.memory_read.SessionLocal")
    @patch("components.memory_read.MemoryService")
    def test_recall_error(self, mock_mem_cls, mock_session_cls):
        from components.memory_read import memory_read_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_mem_cls.side_effect = RuntimeError("DB error")

        node = _make_node("memory_read", extra_config={})
        tool = memory_read_factory(node)
        result = tool.invoke({"key": "test"})
        assert "Error" in result


# ── Memory Write ──────────────────────────────────────────────────────────────

class TestMemoryWrite:
    @patch("components.memory_write.SessionLocal")
    @patch("components.memory_write.MemoryService")
    def test_remember(self, mock_mem_cls, mock_session_cls):
        from components.memory_write import memory_write_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_mem = MagicMock()
        mock_fact = MagicMock(times_confirmed=1)
        mock_mem.set_fact.return_value = mock_fact
        mock_mem_cls.return_value = mock_mem

        node = _make_node("memory_write", extra_config={"fact_type": "preference", "overwrite": True})
        tool = memory_write_factory(node)
        result = tool.invoke({"key": "drink", "value": "coffee"})
        assert "Remembered" in result
        mock_mem.set_fact.assert_called_once()

    @patch("components.memory_write.SessionLocal")
    @patch("components.memory_write.MemoryService")
    def test_remember_error(self, mock_mem_cls, mock_session_cls):
        from components.memory_write import memory_write_factory

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_mem_cls.side_effect = RuntimeError("fail")

        node = _make_node("memory_write", extra_config={})
        tool = memory_write_factory(node)
        result = tool.invoke({"key": "k", "value": "v"})
        assert "Error" in result


# ── Agent ─────────────────────────────────────────────────────────────────────

class TestAgentComponent:
    @patch("components.agent._resolve_tools", return_value=[])
    @patch("components.agent.create_react_agent")
    @patch("components.agent.resolve_llm_for_node")
    def test_basic_agent(self, mock_resolve, mock_create_agent, mock_tools):
        from components.agent import agent_factory

        mock_llm = MagicMock()
        mock_resolve.return_value = mock_llm

        # Mock the compiled agent graph
        mock_agent = MagicMock()
        ai_msg = MagicMock()
        ai_msg.content = "I am an agent"
        ai_msg.type = "ai"
        ai_msg.additional_kwargs = {}
        mock_agent.invoke.return_value = {"messages": [ai_msg]}
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", extra_config={"conversation_memory": False},
                          system_prompt="You are a test agent.")
        fn = agent_factory(node)
        result = fn({"messages": [], "user_context": {}})
        assert result["output"] == "I am an agent"
        assert "_messages" in result

    @patch("components.agent._resolve_tools", return_value=[])
    @patch("components.agent.create_react_agent")
    @patch("components.agent.resolve_llm_for_node")
    def test_agent_with_system_prompt(self, mock_resolve, mock_create_agent, mock_tools):
        from components.agent import agent_factory

        mock_llm = MagicMock()
        mock_resolve.return_value = mock_llm

        mock_agent = MagicMock()
        ai_msg = MagicMock()
        ai_msg.content = "Response"
        ai_msg.type = "ai"
        ai_msg.additional_kwargs = {}
        mock_agent.invoke.return_value = {"messages": [ai_msg]}
        mock_create_agent.return_value = mock_agent

        node = _make_node("agent", extra_config={"conversation_memory": False},
                          system_prompt="Custom prompt")
        fn = agent_factory(node)
        result = fn({"messages": [], "user_context": {}})
        assert result["output"] == "Response"
        # Agent was created with system prompt
        mock_create_agent.assert_called_once()
        call_kwargs = mock_create_agent.call_args
        assert call_kwargs.kwargs.get("prompt") is not None


# ── AI Model ──────────────────────────────────────────────────────────────────

class TestAiModelComponent:
    @patch("components.ai_model.resolve_llm_for_node")
    def test_basic_invocation(self, mock_resolve):
        from components.ai_model import ai_model_factory

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Hello from LLM"
        mock_llm.invoke.return_value = mock_response
        mock_resolve.return_value = mock_llm

        node = _make_node("ai_model", node_id="model_1")
        fn = ai_model_factory(node)
        result = fn({"messages": [MagicMock(content="Hi")]})
        assert result["node_outputs"]["model_1"] == "Hello from LLM"
        assert result["messages"] == [mock_response]

    @patch("components.ai_model.resolve_llm_for_node")
    def test_empty_messages(self, mock_resolve):
        from components.ai_model import ai_model_factory

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_llm.invoke.return_value = mock_response
        mock_resolve.return_value = mock_llm

        node = _make_node("ai_model", node_id="model_1")
        fn = ai_model_factory(node)
        result = fn({"messages": []})
        assert result["node_outputs"]["model_1"] == "Response"


# ── Delivery service ──────────────────────────────────────────────────────────

class TestDeliveryService:
    @patch("services.delivery.requests.post")
    def test_send_telegram_message(self, mock_post):
        from services.delivery import OutputDelivery

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        delivery = OutputDelivery()
        result = delivery.send_telegram_message("bot123:token", 12345, "Hello!")
        assert result["ok"] is True
        mock_post.assert_called_once()

    @patch("services.delivery.requests.post")
    def test_send_long_message_splits(self, mock_post):
        from services.delivery import OutputDelivery

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        delivery = OutputDelivery()
        long_text = "line\n" * 2000  # > 4096 chars
        delivery._send_long_message("bot123:token", 12345, long_text)
        # Should split into multiple messages
        assert mock_post.call_count > 1

    @patch("services.delivery.requests.post")
    def test_send_typing_action(self, mock_post):
        from services.delivery import OutputDelivery

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        delivery = OutputDelivery()
        delivery.send_typing_action("bot:token", 123)
        mock_post.assert_called_once()

    @patch("services.delivery.requests.post")
    def test_send_telegram_error(self, mock_post):
        import requests as req
        from services.delivery import OutputDelivery

        mock_post.side_effect = req.RequestException("network error")

        delivery = OutputDelivery()
        result = delivery.send_telegram_message("bot:token", 123, "hi")
        assert result is None

    def test_format_output(self):
        from services.delivery import OutputDelivery

        delivery = OutputDelivery()
        assert delivery._format_output({"message": "hello"}) == "hello"
        assert delivery._format_output({"output": "data"}) == "data"
        assert delivery._format_output({"node_outputs": {"n1": "val"}}) != ""
        assert delivery._format_output(None) == ""
        assert delivery._format_output({}) == ""

    def test_format_output_str_fallback(self):
        from services.delivery import OutputDelivery

        delivery = OutputDelivery()
        result = delivery._format_output({"custom_key": 42})
        assert "42" in result
