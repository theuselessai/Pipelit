"""Tests targeting remaining coverage gaps: output_parser, delivery, edges validation, chat endpoints."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── output_parser component ──────────────────────────────────────────────────

class TestOutputParserComponent:
    def test_parse_json_from_code_block(self):
        from components.output_parser import _parse_json
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_invalid_in_code_block(self):
        from components.output_parser import _parse_json
        text = '```json\nnot valid json\n```'
        result = _parse_json(text)
        assert result == text

    def test_parse_json_direct(self):
        from components.output_parser import _parse_json
        result = _parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_json_invalid(self):
        from components.output_parser import _parse_json
        result = _parse_json("not json")
        assert result == "not json"

    def test_parse_regex_with_matches(self):
        from components.output_parser import _parse_regex
        result = _parse_regex("foo 123 bar 456", r"\d+")
        assert result == ["123", "456"]

    def test_parse_regex_no_matches(self):
        from components.output_parser import _parse_regex
        result = _parse_regex("no numbers here", r"\d+")
        assert result == "no numbers here"

    def test_parse_list(self):
        from components.output_parser import _parse_list
        text = "1. First item\n2. Second item\n3. Third item"
        result = _parse_list(text)
        assert len(result) == 3
        assert result[0] == "First item"

    def test_parse_list_bullet_points(self):
        from components.output_parser import _parse_list
        text = "- Item A\n- Item B\n* Item C"
        result = _parse_list(text)
        assert len(result) == 3

    def test_get_raw_from_messages(self):
        from components.output_parser import _get_raw
        msg = SimpleNamespace(content="hello world")
        state = {"messages": [msg]}
        result = _get_raw(state, None)
        assert result == "hello world"

    def test_get_raw_no_messages(self):
        from components.output_parser import _get_raw
        state = {"messages": []}
        result = _get_raw(state, None)
        assert result is None

    def test_factory_json_parser(self):
        from components.output_parser import output_parser_factory
        node = SimpleNamespace(
            node_id="parser_1",
            component_config=SimpleNamespace(
                extra_config={"parser_type": "json", "source_node": "src"},
            ),
        )
        fn = output_parser_factory(node)
        state = {"node_outputs": {"src": '{"key": "val"}'}}
        result = fn(state)
        assert "node_outputs" in result
        assert result["node_outputs"]["parser_1"] == {"key": "val"}

    def test_factory_regex_parser(self):
        from components.output_parser import output_parser_factory
        node = SimpleNamespace(
            node_id="parser_1",
            component_config=SimpleNamespace(
                extra_config={"parser_type": "regex", "source_node": "src", "pattern": r"\d+"},
            ),
        )
        fn = output_parser_factory(node)
        state = {"node_outputs": {"src": "foo 42 bar 99"}}
        result = fn(state)
        assert result["node_outputs"]["parser_1"] == ["42", "99"]

    def test_factory_list_parser(self):
        from components.output_parser import output_parser_factory
        node = SimpleNamespace(
            node_id="parser_1",
            component_config=SimpleNamespace(
                extra_config={"parser_type": "list", "source_node": "src"},
            ),
        )
        fn = output_parser_factory(node)
        state = {"node_outputs": {"src": "1. A\n2. B"}}
        result = fn(state)
        assert len(result["node_outputs"]["parser_1"]) == 2

    def test_factory_unknown_parser(self):
        from components.output_parser import output_parser_factory
        node = SimpleNamespace(
            node_id="parser_1",
            component_config=SimpleNamespace(
                extra_config={"parser_type": "custom", "source_node": "src"},
            ),
        )
        fn = output_parser_factory(node)
        state = {"node_outputs": {"src": "raw text"}}
        result = fn(state)
        assert result["node_outputs"]["parser_1"] == "raw text"

    def test_factory_null_source(self):
        from components.output_parser import output_parser_factory
        node = SimpleNamespace(
            node_id="parser_1",
            component_config=SimpleNamespace(
                extra_config={"parser_type": "json", "source_node": "missing"},
            ),
        )
        fn = output_parser_factory(node)
        state = {"node_outputs": {}}
        result = fn(state)
        assert result["node_outputs"]["parser_1"] is None


# ── memory_read component ────────────────────────────────────────────────────

class TestMemoryReadComponent:
    def test_memory_read_recall_tool(self):
        """Test the recall tool returned by memory_read_factory."""
        from components.memory_read import memory_read_factory

        node = SimpleNamespace(
            node_id="mem_1",
            workflow_id=1,
            component_config=SimpleNamespace(
                extra_config={"memory_type": "all", "query": "book", "limit": 5},
            ),
        )

        mock_memory = MagicMock()
        mock_memory.get_fact.return_value = "coffee"
        mock_db = MagicMock()

        with patch("components.memory_read.MemoryService", return_value=mock_memory):
            with patch("components.memory_read.SessionLocal", return_value=mock_db):
                recall_tool = memory_read_factory(node)
                # Invoke the tool with a key
                result = recall_tool.invoke({"key": "fav_drink"})

        assert "coffee" in result

    def test_memory_read_recall_search(self):
        from components.memory_read import memory_read_factory

        node = SimpleNamespace(
            node_id="mem_1",
            workflow_id=1,
            component_config=SimpleNamespace(
                extra_config={"memory_type": "facts", "limit": 5},
            ),
        )

        fact = SimpleNamespace(key="name", value="Alice", confidence=0.9)
        mock_memory = MagicMock()
        mock_memory.search_facts.return_value = [fact]
        mock_memory.find_matching_procedure.return_value = None
        mock_memory.get_recent_episodes.return_value = []
        mock_db = MagicMock()

        with patch("components.memory_read.MemoryService", return_value=mock_memory):
            with patch("components.memory_read.SessionLocal", return_value=mock_db):
                recall_tool = memory_read_factory(node)
                result = recall_tool.invoke({"query": "name"})

        assert "Alice" in result

    def test_memory_read_no_args(self):
        from components.memory_read import memory_read_factory

        node = SimpleNamespace(
            node_id="mem_1",
            workflow_id=1,
            component_config=SimpleNamespace(extra_config={}),
        )

        recall_tool = memory_read_factory(node)
        result = recall_tool.invoke({})
        # With no args, recall now lists all memories (or reports empty)
        assert "empty" in result.lower() or ("[" in result and "]" in result)


# ── delivery service ─────────────────────────────────────────────────────────

class TestDeliveryService:
    def test_send_typing_action(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        with patch("services.delivery.requests.post") as mock_post:
            svc.send_typing_action("token123", 456)
            mock_post.assert_called_once()

    def test_send_typing_action_error(self):
        import requests
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        with patch("services.delivery.requests.post", side_effect=requests.RequestException):
            svc.send_typing_action("token", 123)

    def test_format_output_with_message(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        assert svc._format_output({"message": "hello"}) == "hello"

    def test_format_output_with_output(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        assert svc._format_output({"output": "world"}) == "world"

    def test_format_output_with_node_outputs(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        result = svc._format_output({"node_outputs": {"n1": "val1"}})
        assert "n1" in result

    def test_send_telegram_markdown_fallback(self):
        import requests
        from services.delivery import OutputDelivery

        svc = OutputDelivery()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                resp = MagicMock()
                resp.raise_for_status.side_effect = requests.RequestException("parse error")
                return resp
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"ok": True}
            return resp

        with patch("services.delivery.requests.post", side_effect=side_effect):
            result = svc.send_telegram_message("token", 123, "hello *world")
        assert result is not None

    def test_send_telegram_both_fail(self):
        import requests
        from services.delivery import OutputDelivery

        svc = OutputDelivery()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.RequestException("fail")

        with patch("services.delivery.requests.post", return_value=mock_resp):
            result = svc.send_telegram_message("token", 123, "hello")
        assert result is None

    def test_resolve_bot_token_no_trigger(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        execution = MagicMock()
        execution.trigger_node_id = None
        result = svc._resolve_bot_token(execution, MagicMock())
        assert result is None

    def test_resolve_bot_token_no_credential(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        execution = MagicMock()
        execution.trigger_node_id = 1
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.component_config.credential_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_node
        result = svc._resolve_bot_token(execution, mock_db)
        assert result is None

    def test_deliver_no_chat_id(self):
        from services.delivery import OutputDelivery
        svc = OutputDelivery()
        execution = MagicMock()
        execution.trigger_payload = {}
        svc.deliver(execution, MagicMock())


# ── edge validation ──────────────────────────────────────────────────────────

class TestEdgeValidation:
    def test_validate_edge_unknown_source(self):
        from validation.edges import EdgeValidator
        errors = EdgeValidator.validate_edge("totally_unknown_type", "agent")
        assert isinstance(errors, list)

    def test_validate_workflow_edges_conditional_no_value(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
        from validation.edges import EdgeValidator

        cc = BaseComponentConfig(component_type="switch")
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id, node_id="switch_1",
            component_type="switch", component_config_id=cc.id,
        )
        db.add(node)
        db.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id, source_node_id="switch_1",
            target_node_id="handler_1", edge_type="conditional",
            condition_value="",
        )
        db.add(edge)
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("missing condition_value" in e for e in errors)

    def test_validate_workflow_edges_conditional_unknown_target(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
        from validation.edges import EdgeValidator

        cc = BaseComponentConfig(component_type="switch")
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id, node_id="switch_1",
            component_type="switch", component_config_id=cc.id,
        )
        db.add(node)
        db.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id, source_node_id="switch_1",
            target_node_id="nonexistent", edge_type="conditional",
            condition_value="yes",
        )
        db.add(edge)
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("unknown node" in e for e in errors)

    def test_validate_workflow_edges_non_switch_conditional(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
        from validation.edges import EdgeValidator

        cc = BaseComponentConfig(component_type="agent")
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id, node_id="agent_1",
            component_type="agent", component_config_id=cc.id,
        )
        db.add(node)
        db.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id, source_node_id="agent_1",
            target_node_id="handler_1", edge_type="conditional",
            condition_value="yes",
        )
        db.add(edge)
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert any("only 'switch' nodes" in e for e in errors)

    def test_validate_required_inputs(self, db, workflow):
        import schemas.node_type_defs  # noqa: F401 — ensure registry is populated
        from models.node import BaseComponentConfig, WorkflowNode
        from validation.edges import EdgeValidator

        cc = BaseComponentConfig(component_type="agent")
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id, node_id="agent_1",
            component_type="agent", component_config_id=cc.id,
        )
        db.add(node)
        db.commit()

        errors = EdgeValidator.validate_required_inputs(workflow.id, db)
        assert any("requires a model" in e for e in errors)

    def test_validate_required_inputs_trigger_skip(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode
        from validation.edges import EdgeValidator

        cc = BaseComponentConfig(component_type="trigger_manual")
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id, node_id="trigger_1",
            component_type="trigger_manual", component_config_id=cc.id,
        )
        db.add(node)
        db.commit()

        errors = EdgeValidator.validate_required_inputs(workflow.id, db)
        assert len(errors) == 0

    def test_validate_workflow_edges_loop_edges_skipped(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
        from validation.edges import EdgeValidator

        cc1 = BaseComponentConfig(component_type="loop")
        cc2 = BaseComponentConfig(component_type="code")
        db.add_all([cc1, cc2])
        db.flush()
        n1 = WorkflowNode(
            workflow_id=workflow.id, node_id="loop_1",
            component_type="loop", component_config_id=cc1.id,
        )
        n2 = WorkflowNode(
            workflow_id=workflow.id, node_id="body_1",
            component_type="code", component_config_id=cc2.id,
        )
        db.add_all([n1, n2])
        db.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id, source_node_id="loop_1",
            target_node_id="body_1", edge_type="direct",
            edge_label="loop_body",
        )
        db.add(edge)
        db.commit()

        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert not any("loop_1 → body_1" in e for e in errors)


# ── Chat history endpoint ────────────────────────────────────────────────────

class TestChatHistoryAPI:
    @pytest.fixture
    def app(self, db):
        from main import app as _app
        from database import get_db

        def _override_get_db():
            try:
                yield db
            finally:
                pass

        _app.dependency_overrides[get_db] = _override_get_db
        yield _app
        _app.dependency_overrides.clear()

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.fixture
    def auth_client(self, client, api_key):
        client.headers["Authorization"] = f"Bearer {api_key.key}"
        return client

    def test_chat_history_workflow_not_found(self, auth_client):
        resp = auth_client.get("/api/v1/workflows/nonexistent/chat/history")
        assert resp.status_code == 404

    def test_chat_history_empty(self, auth_client, workflow):
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = None

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []

    def test_chat_history_with_messages(self, auth_client, workflow):
        msg1 = SimpleNamespace(type="human", content="Hello", id="1", additional_kwargs={}, response_metadata={})
        msg2 = SimpleNamespace(type="ai", content="Hi there!", id="2", additional_kwargs={"timestamp": "2025-01-01T00:00:00"}, response_metadata={})

        mock_tuple = MagicMock()
        mock_tuple.checkpoint = {"channel_values": {"messages": [msg1, msg2]}}
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = mock_tuple

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    def test_chat_history_skips_system_prompt_fallback(self, auth_client, workflow):
        msg_sys = SimpleNamespace(type="human", content="System prompt", id="system_prompt_fallback", additional_kwargs={}, response_metadata={})
        msg_user = SimpleNamespace(type="human", content="User message", id="2", additional_kwargs={}, response_metadata={})

        mock_tuple = MagicMock()
        mock_tuple.checkpoint = {"channel_values": {"messages": [msg_sys, msg_user]}}
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = mock_tuple

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "User message"

    def test_chat_history_skips_empty_ai_messages(self, auth_client, workflow):
        msg = SimpleNamespace(type="ai", content="", id="1", additional_kwargs={}, response_metadata={})

        mock_tuple = MagicMock()
        mock_tuple.checkpoint = {"channel_values": {"messages": [msg]}}
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = mock_tuple

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        data = resp.json()
        assert data["messages"] == []

    def test_chat_history_with_before_filter(self, auth_client, workflow):
        msg1 = SimpleNamespace(type="human", content="Old", id="1", additional_kwargs={"timestamp": "2024-01-01T00:00:00"}, response_metadata={})
        msg2 = SimpleNamespace(type="human", content="New", id="2", additional_kwargs={"timestamp": "2025-06-01T00:00:00"}, response_metadata={})

        mock_tuple = MagicMock()
        mock_tuple.checkpoint = {"channel_values": {"messages": [msg1, msg2]}}
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = mock_tuple

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history?before=2025-01-01T00:00:00")
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["text"] == "Old"

    def test_chat_history_checkpointer_error(self, auth_client, workflow):
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.side_effect = Exception("DB error")

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        data = resp.json()
        assert data["messages"] == []

    def test_chat_history_response_metadata_timestamp(self, auth_client, workflow):
        msg = SimpleNamespace(
            type="ai", content="Hello!", id="1",
            additional_kwargs={},
            response_metadata={"created": 1704067200},
        )

        mock_tuple = MagicMock()
        mock_tuple.checkpoint = {"channel_values": {"messages": [msg]}}
        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = mock_tuple

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.get(f"/api/v1/workflows/{workflow.slug}/chat/history")
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["timestamp"] is not None

    def test_delete_chat_history_not_found(self, auth_client):
        resp = auth_client.delete("/api/v1/workflows/nonexistent/chat/history")
        assert resp.status_code == 404

    def test_delete_chat_history(self, auth_client, workflow):
        mock_conn = MagicMock()
        mock_checkpointer = MagicMock()
        mock_checkpointer.conn = mock_conn

        with patch("components.agent._get_checkpointer", return_value=mock_checkpointer):
            resp = auth_client.delete(f"/api/v1/workflows/{workflow.slug}/chat/history")
        assert resp.status_code == 204
        assert mock_conn.execute.call_count == 2
        mock_conn.commit.assert_called_once()


# ── Topology service ─────────────────────────────────────────────────────────

class TestTopologyService:
    def test_build_topology_basic(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
        from services.topology import build_topology

        cc1 = BaseComponentConfig(component_type="trigger_manual")
        cc2 = BaseComponentConfig(component_type="agent")
        db.add_all([cc1, cc2])
        db.flush()

        n1 = WorkflowNode(
            workflow_id=workflow.id, node_id="trigger_1",
            component_type="trigger_manual", component_config_id=cc1.id,
        )
        n2 = WorkflowNode(
            workflow_id=workflow.id, node_id="agent_1",
            component_type="agent", component_config_id=cc2.id,
        )
        db.add_all([n1, n2])
        db.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id, source_node_id="trigger_1",
            target_node_id="agent_1", edge_type="direct",
        )
        db.add(edge)
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=n1.id)
        assert "agent_1" in topo.nodes
        assert "agent_1" in topo.entry_node_ids

    def test_build_topology_no_trigger(self, db, workflow):
        from models.node import BaseComponentConfig, WorkflowNode
        from services.topology import build_topology

        cc = BaseComponentConfig(component_type="agent")
        db.add(cc)
        db.flush()

        node = WorkflowNode(
            workflow_id=workflow.id, node_id="agent_1",
            component_type="agent", component_config_id=cc.id,
            is_entry_point=True,
        )
        db.add(node)
        db.commit()

        topo = build_topology(workflow, db)
        assert "agent_1" in topo.nodes


# ── Orchestrator helper functions ────────────────────────────────────────────

class TestOrchestratorHelpers:
    def test_key_functions(self):
        from services.orchestrator import (
            _completed_key, _episode_key, _fanin_key, _inflight_key,
            _lock_key, _loop_iter_done_key, _loop_key, _state_key, _topo_key,
        )

        assert _state_key("e1") == "execution:e1:state"
        assert _fanin_key("e1", "n1") == "execution:e1:fanin:n1"
        assert _lock_key("e1") == "execution:e1:lock"
        assert _topo_key("e1") == "execution:e1:topo"
        assert _completed_key("e1") == "execution:e1:completed"
        assert _episode_key("e1") == "execution:e1:episode_id"
        assert _inflight_key("e1") == "execution:e1:inflight"
        assert _loop_key("e1", "l1") == "execution:e1:loop:l1"
        assert _loop_iter_done_key("e1", "l1", 0) == "execution:e1:loop:l1:iter:0:done"
        assert _loop_iter_done_key("e1", "l1") == "execution:e1:loop:l1:iter_done"

    def test_cleanup_redis(self):
        from services.orchestrator import _cleanup_redis

        mock_r = MagicMock()
        mock_r.keys.return_value = ["execution:e1:state", "execution:e1:topo"]
        with patch("services.orchestrator._redis", return_value=mock_r):
            _cleanup_redis("e1")
        mock_r.delete.assert_called()

    def test_build_initial_state(self):
        from services.orchestrator import _build_initial_state

        execution = MagicMock()
        execution.trigger_payload = {"text": "hello", "chat_id": 123}
        execution.user_profile_id = 42
        execution.execution_id = uuid.uuid4()

        state = _build_initial_state(execution)
        assert state["trigger"]["text"] == "hello"
        assert state["user_context"]["user_profile_id"] == 42

    def test_safe_json(self):
        from services.orchestrator import _safe_json

        # Normal dict
        assert _safe_json({"key": "val"}) == {"key": "val"}
        # None
        assert _safe_json(None) is None
        # Non-serializable object
        result = _safe_json(object())
        assert "repr" in result

    def test_truncate_output(self):
        from services.orchestrator import _truncate_output

        assert _truncate_output(None) is None
        assert _truncate_output("short") == "short"
        long_str = "x" * 5000
        result = _truncate_output(long_str)
        assert len(result) <= 2048

    def test_truncate_output_dict(self):
        from services.orchestrator import _truncate_output

        data = {"key": "x" * 5000}
        result = _truncate_output(data)
        assert isinstance(result, dict)
        assert len(result["key"]) <= 2100  # 2048 + "..."

    def test_extract_output(self):
        from services.orchestrator import _extract_output

        # state with output
        assert _extract_output({"output": "result"}) == {"output": "result"}
        # state with AI message
        msg = SimpleNamespace(type="ai", content="hello")
        assert _extract_output({"messages": [msg]})["message"] == "hello"
        # state with node_outputs
        result = _extract_output({"node_outputs": {"n1": {"val": 1}}})
        assert "node_outputs" in result
        # Empty state
        assert _extract_output({}) is None

    def test_write_log(self, db, user_profile, workflow):
        from models.execution import ExecutionLog, WorkflowExecution
        from services.orchestrator import _write_log

        exec_obj = WorkflowExecution(
            workflow_id=workflow.id, user_profile_id=user_profile.id,
            thread_id=uuid.uuid4().hex, trigger_payload={},
        )
        db.add(exec_obj)
        db.commit()

        _write_log(db, str(exec_obj.execution_id), "node_1", "completed", duration_ms=100, output={"val": 1})
        logs = db.query(ExecutionLog).all()
        assert len(logs) == 1
        assert logs[0].node_id == "node_1"
