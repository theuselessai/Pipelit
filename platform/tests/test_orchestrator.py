"""Tests for the per-node orchestrator, topology, and state merge."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
from services.state import deserialize_state, merge_state_update, serialize_state
from services.topology import Topology, build_topology


# ── Helpers ────────────────────────────────────────────────────────────────────


def _add_node(db, workflow, node_id, component_type, **kwargs):
    cc = BaseComponentConfig(component_type=component_type)
    db.add(cc)
    db.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id=node_id,
        component_type=component_type,
        component_config_id=cc.id,
        **kwargs,
    )
    db.add(node)
    db.flush()
    return node


def _add_edge(db, workflow, source, target, edge_label="", edge_type="direct", condition_mapping=None, condition_value=""):
    edge = WorkflowEdge(
        workflow_id=workflow.id,
        source_node_id=source,
        target_node_id=target,
        edge_label=edge_label,
        edge_type=edge_type,
        condition_mapping=condition_mapping,
        condition_value=condition_value,
    )
    db.add(edge)
    db.flush()
    return edge


# ── State merge tests ─────────────────────────────────────────────────────────


class TestMergeStateUpdate:
    def test_messages_append(self):
        current = {"messages": [{"type": "human", "content": "hi"}]}
        update = {"messages": [{"type": "ai", "content": "hello"}]}
        result = merge_state_update(current, update)
        assert len(result["messages"]) == 2

    def test_node_outputs_merge(self):
        current = {"node_outputs": {"a": 1}}
        update = {"node_outputs": {"b": 2}}
        result = merge_state_update(current, update)
        assert result["node_outputs"] == {"a": 1, "b": 2}

    def test_scalar_overwrite(self):
        current = {"route": "old", "error": ""}
        update = {"route": "new"}
        result = merge_state_update(current, update)
        assert result["route"] == "new"
        assert result["error"] == ""

    def test_empty_update(self):
        current = {"messages": [], "node_outputs": {"a": 1}}
        result = merge_state_update(current, {})
        assert result == current

    def test_missing_messages_key(self):
        current = {}
        update = {"messages": [{"content": "hi"}]}
        result = merge_state_update(current, update)
        assert result["messages"] == [{"content": "hi"}]


class TestSerializeDeserialize:
    def test_roundtrip_without_messages(self):
        state = {"route": "test", "node_outputs": {"a": 1}}
        assert deserialize_state(serialize_state(state)) == state

    def test_roundtrip_with_langchain_messages(self):
        from langchain_core.messages import HumanMessage

        state = {"messages": [HumanMessage(content="hello")], "route": ""}
        serialized = serialize_state(state)
        assert isinstance(serialized["messages"], list)
        assert isinstance(serialized["messages"][0], dict)

        deserialized = deserialize_state(serialized)
        assert hasattr(deserialized["messages"][0], "content")
        assert deserialized["messages"][0].content == "hello"


# ── Topology tests ─────────────────────────────────────────────────────────────


class TestBuildTopology:
    def test_linear_topology(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "agent_1", "agent")
        _add_node(db, workflow, "code_1", "code")
        _add_edge(db, workflow, "trigger_1", "agent_1")
        _add_edge(db, workflow, "agent_1", "code_1")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "agent_1" in topo.nodes
        assert "code_1" in topo.nodes
        assert "trigger_1" not in topo.nodes
        assert topo.entry_node_ids == ["agent_1"]
        assert len(topo.edges_by_source["agent_1"]) == 1

    def test_fan_out_topology(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "agent")
        _add_edge(db, workflow, "trigger_1", "agent_a")
        _add_edge(db, workflow, "trigger_1", "agent_b")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "agent_a" in topo.nodes
        assert "agent_b" in topo.nodes
        # Both are entry nodes since both are direct targets of trigger
        assert set(topo.entry_node_ids) == {"agent_a", "agent_b"}

    def test_fan_in_merge_node(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "agent")
        _add_node(db, workflow, "merge_1", "merge")
        _add_edge(db, workflow, "trigger_1", "agent_a")
        _add_edge(db, workflow, "trigger_1", "agent_b")
        _add_edge(db, workflow, "agent_a", "merge_1")
        _add_edge(db, workflow, "agent_b", "merge_1")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert topo.incoming_count["merge_1"] == 2
        # Trigger edges to agent_a/agent_b are excluded (trigger is skipped),
        # so incoming_count for these is 0
        assert topo.incoming_count.get("agent_a", 0) == 0
        assert topo.incoming_count.get("agent_b", 0) == 0

    def test_ai_model_excluded(self, db, workflow):
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_node(db, workflow, "model_1", "ai_model")
        _add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        db.commit()

        topo = build_topology(workflow, db)

        assert "agent_1" in topo.nodes
        assert "model_1" not in topo.nodes

    def test_conditional_edges(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "switch_1", "switch")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "agent")
        _add_edge(db, workflow, "trigger_1", "switch_1")
        _add_edge(
            db, workflow, "switch_1", "agent_a",
            edge_type="conditional",
            condition_value="route_a",
        )
        _add_edge(
            db, workflow, "switch_1", "agent_b",
            edge_type="conditional",
            condition_value="route_b",
        )
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "switch_1" in topo.nodes
        cond_edges = [e for e in topo.edges_by_source.get("switch_1", []) if e.edge_type == "conditional"]
        assert len(cond_edges) == 2
        condition_values = {e.condition_value for e in cond_edges}
        assert condition_values == {"route_a", "route_b"}

    def test_trigger_scoping(self, db, workflow):
        trigger_a = _add_node(db, workflow, "trigger_a", "trigger_telegram")
        _add_node(db, workflow, "trigger_b", "trigger_webhook")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "agent")
        _add_edge(db, workflow, "trigger_a", "agent_a")
        _add_edge(db, workflow, "trigger_b", "agent_b")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger_a.id)

        assert "agent_a" in topo.nodes
        assert "agent_b" not in topo.nodes


# ── Orchestrator unit tests ────────────────────────────────────────────────────


class TestOrchestratorAdvance:
    """Test the _advance logic with mocked Redis."""

    def test_advance_direct_edge(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "a": {"component_type": "agent"},
                "b": {"component_type": "code"},
            },
            "edges_by_source": {
                "a": [{"source_node_id": "a", "target_node_id": "b", "edge_type": "direct"}],
            },
            "incoming_count": {"a": 0, "b": 1},
        }
        state = {"route": ""}

        with patch("services.orchestrator._queue") as mock_q, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_queue = MagicMock()
            mock_q.return_value = mock_queue
            mock_redis = MagicMock()
            mock_r.return_value = mock_redis
            mock_redis.decr.return_value = 0

            _advance("exec-1", "a", state, topo_data, MagicMock())

            mock_queue.enqueue.assert_called_once()
            args = mock_queue.enqueue.call_args
            assert args[0][1] == "exec-1"
            assert args[0][2] == "b"

    def test_advance_conditional_edge(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "switch_1": {"component_type": "switch"},
                "a": {"component_type": "agent"},
                "b": {"component_type": "agent"},
            },
            "edges_by_source": {
                "switch_1": [
                    {
                        "source_node_id": "switch_1",
                        "target_node_id": "a",
                        "edge_type": "conditional",
                        "condition_value": "go_a",
                    },
                    {
                        "source_node_id": "switch_1",
                        "target_node_id": "b",
                        "edge_type": "conditional",
                        "condition_value": "go_b",
                    },
                ],
            },
            "incoming_count": {"switch_1": 0, "a": 0, "b": 0},
        }
        state = {"route": "go_b"}

        with patch("services.orchestrator._queue") as mock_q, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_queue = MagicMock()
            mock_q.return_value = mock_queue
            mock_redis = MagicMock()
            mock_r.return_value = mock_redis
            mock_redis.decr.return_value = 0

            _advance("exec-1", "switch_1", state, topo_data, MagicMock())

            mock_queue.enqueue.assert_called_once()
            args = mock_queue.enqueue.call_args
            assert args[0][2] == "b"

    def test_advance_fanout(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "src": {"component_type": "agent"},
                "a": {"component_type": "agent"},
                "b": {"component_type": "agent"},
            },
            "edges_by_source": {
                "src": [
                    {"source_node_id": "src", "target_node_id": "a", "edge_type": "direct"},
                    {"source_node_id": "src", "target_node_id": "b", "edge_type": "direct"},
                ],
            },
            "incoming_count": {"src": 0, "a": 1, "b": 1},
        }
        state = {"route": ""}

        with patch("services.orchestrator._queue") as mock_q, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_queue = MagicMock()
            mock_q.return_value = mock_queue
            mock_redis = MagicMock()
            mock_r.return_value = mock_redis
            mock_redis.decr.return_value = 0

            _advance("exec-1", "src", state, topo_data, MagicMock())

            assert mock_queue.enqueue.call_count == 2

    def test_advance_fanin_merge(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "a": {"component_type": "agent"},
                "merge_1": {"component_type": "merge"},
            },
            "edges_by_source": {
                "a": [{"source_node_id": "a", "target_node_id": "merge_1", "edge_type": "direct"}],
            },
            "incoming_count": {"a": 0, "merge_1": 2},
        }
        state = {"route": ""}

        with patch("services.orchestrator._queue") as mock_q, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_queue = MagicMock()
            mock_q.return_value = mock_queue

            mock_redis = MagicMock()
            mock_r.return_value = mock_redis
            # First parent done — count=1, not enough
            mock_redis.incr.return_value = 1
            mock_redis.decr.return_value = 0

            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_queue.enqueue.assert_not_called()

            # Second parent done — count=2, merge should be enqueued
            mock_redis.incr.return_value = 2
            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_queue.enqueue.assert_called_once()

    def test_advance_no_successors_tries_finalize(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {"a": {"component_type": "agent"}},
            "edges_by_source": {},
            "incoming_count": {"a": 0},
        }
        state = {"route": ""}

        with patch("services.orchestrator._finalize") as mock_fin, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_redis = MagicMock()
            mock_r.return_value = mock_redis
            mock_redis.decr.return_value = 0

            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_fin.assert_called_once()


# ── Switch component tests ────────────────────────────────────────────────────


class TestSwitchComponent:
    def test_rule_matching(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {
            "rules": [
                {"id": "r_good", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "good", "label": "Good"},
                {"id": "r_bad", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "bad", "label": "Bad"},
            ],
        }

        fn = switch_factory(node)
        result = fn({"node_outputs": {"cat_1": {"category": "good"}}})

        assert result["_route"] == "r_good"
        assert result["route"] == "r_good"

    def test_rule_second_match(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {
            "rules": [
                {"id": "r_good", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "good", "label": "Good"},
                {"id": "r_bad", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "bad", "label": "Bad"},
            ],
        }

        fn = switch_factory(node)
        result = fn({"node_outputs": {"cat_1": {"category": "bad"}}})

        assert result["_route"] == "r_bad"
        assert result["route"] == "r_bad"

    def test_fallback(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {
            "rules": [
                {"id": "r_good", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "good", "label": "Good"},
            ],
            "enable_fallback": True,
        }

        fn = switch_factory(node)
        result = fn({"node_outputs": {"cat_1": {"category": "unknown"}}})

        assert result["_route"] == "__other__"
        assert result["route"] == "__other__"

    def test_no_match_no_fallback(self):
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {
            "rules": [
                {"id": "r_good", "field": "node_outputs.cat_1.category", "operator": "equals", "value": "good", "label": "Good"},
            ],
            "enable_fallback": False,
        }

        fn = switch_factory(node)
        result = fn({"node_outputs": {"cat_1": {"category": "unknown"}}})

        assert result["route"] == ""

    def test_backward_compat(self):
        """Legacy condition_field config still works when no rules are set."""
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {"condition_field": "route"}

        fn = switch_factory(node)
        result = fn({"route": "go_a", "node_outputs": {}})

        assert result["_route"] == "go_a"
        assert result["route"] == "go_a"

    def test_backward_compat_expression(self):
        """Legacy condition_expression still works."""
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {
            "condition_expression": "state.node_outputs.cat_1.category",
        }

        fn = switch_factory(node)
        result = fn({"node_outputs": {"cat_1": {"category": "billing"}}})

        assert result["_route"] == "billing"
        assert result["route"] == "billing"

    def test_backward_compat_default(self):
        """Empty extra_config defaults to condition_field='route'."""
        from components.switch import switch_factory

        node = MagicMock()
        node.node_id = "switch_1"
        node.component_config.extra_config = {}

        fn = switch_factory(node)
        result = fn({"route": "test_val", "node_outputs": {}})

        assert result["_route"] == "test_val"
        assert result["route"] == "test_val"

    def test_operators(self):
        """Test various operators."""
        from components.switch import switch_factory

        def _make(rules):
            node = MagicMock()
            node.node_id = "sw"
            node.component_config.extra_config = {"rules": rules}
            return switch_factory(node)

        # equals
        fn = _make([{"id": "r1", "field": "val", "operator": "equals", "value": "hello", "label": ""}])
        assert fn({"val": "hello"})["_route"] == "r1"
        assert fn({"val": "nope"})["_route"] == ""

        # contains (string)
        fn = _make([{"id": "r1", "field": "val", "operator": "contains", "value": "ell", "label": ""}])
        assert fn({"val": "hello"})["_route"] == "r1"
        assert fn({"val": "world"})["_route"] == ""

        # gt (number)
        fn = _make([{"id": "r1", "field": "val", "operator": "gt", "value": "5", "label": ""}])
        assert fn({"val": 10})["_route"] == "r1"
        assert fn({"val": 3})["_route"] == ""

        # is_true (boolean, unary)
        fn = _make([{"id": "r1", "field": "val", "operator": "is_true", "value": "", "label": ""}])
        assert fn({"val": True})["_route"] == "r1"
        assert fn({"val": False})["_route"] == ""

        # length_eq (array)
        fn = _make([{"id": "r1", "field": "val", "operator": "length_eq", "value": "3", "label": ""}])
        assert fn({"val": [1, 2, 3]})["_route"] == "r1"
        assert fn({"val": [1, 2]})["_route"] == ""

        # exists (unary)
        fn = _make([{"id": "r1", "field": "val", "operator": "exists", "value": "", "label": ""}])
        assert fn({"val": "anything"})["_route"] == "r1"
        assert fn({})["_route"] == ""

        # matches_regex
        fn = _make([{"id": "r1", "field": "val", "operator": "matches_regex", "value": "^\\d+$", "label": ""}])
        assert fn({"val": "12345"})["_route"] == "r1"
        assert fn({"val": "abc"})["_route"] == ""


# ── Human confirmation tests ───────────────────────────────────────────────────


class TestHumanConfirmation:
    def test_no_resume_input_returns_cancelled(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {"prompt": "Are you sure?"}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}})

        assert result["_route"] == "cancelled"
        assert result["confirmed"] is False

    def test_resume_input_yes(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {"prompt": "Are you sure?"}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}, "_resume_input": "yes"})

        assert result["_route"] == "confirmed"
        assert result["confirmed"] is True

    def test_resume_input_no(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}, "_resume_input": "no"})

        assert result["_route"] == "cancelled"
        assert result["confirmed"] is False


# ── Orchestrator output wrapping tests ─────────────────────────────────────────


class TestOrchestratorOutputWrapping:
    """Test the new orchestrator output wrapping logic."""

    def _apply_wrapping(self, state: dict, result: dict | None, node_id: str) -> dict:
        """Simulate the orchestrator wrapping logic from execute_node_job."""
        if result and isinstance(result, dict):
            if "node_outputs" in result:
                state = merge_state_update(state, result)
            else:
                route = result.pop("_route", None)
                new_messages = result.pop("_messages", None)
                state_patch = result.pop("_state_patch", None)

                port_data = {k: v for k, v in result.items() if not k.startswith("_")}
                node_outputs = state.get("node_outputs", {})
                node_outputs[node_id] = port_data
                state["node_outputs"] = node_outputs

                if route is not None:
                    state["route"] = route
                if new_messages:
                    state["messages"] = state.get("messages", []) + new_messages
                if state_patch and isinstance(state_patch, dict):
                    for k, v in state_patch.items():
                        if k not in ("messages", "node_outputs", "node_results"):
                            state[k] = v

        return state

    def test_flat_dict_wrapping(self):
        state = {"node_outputs": {}, "messages": []}
        result = {"output": "hello", "category": "chat"}
        state = self._apply_wrapping(state, result, "agent_1")
        assert state["node_outputs"]["agent_1"] == {"output": "hello", "category": "chat"}

    def test_route_extraction(self):
        state = {"node_outputs": {}, "route": ""}
        result = {"_route": "FOOD", "category": "FOOD", "raw": "..."}
        state = self._apply_wrapping(state, result, "cat_1")
        assert state["route"] == "FOOD"
        assert state["node_outputs"]["cat_1"] == {"category": "FOOD", "raw": "..."}

    def test_messages_extraction(self):
        state = {"node_outputs": {}, "messages": ["existing"]}
        result = {"_messages": ["new_msg"], "output": "hello"}
        state = self._apply_wrapping(state, result, "chat_1")
        assert state["messages"] == ["existing", "new_msg"]
        assert state["node_outputs"]["chat_1"] == {"output": "hello"}

    def test_state_patch_extraction(self):
        state = {"node_outputs": {}, "user_context": {}}
        result = {
            "user_id": "u1",
            "is_new_user": True,
            "_state_patch": {"user_context": {"name": "Alice"}},
        }
        state = self._apply_wrapping(state, result, "id_1")
        assert state["user_context"] == {"name": "Alice"}
        assert state["node_outputs"]["id_1"] == {"user_id": "u1", "is_new_user": True}

    def test_state_patch_cannot_overwrite_protected_keys(self):
        state = {"node_outputs": {"existing": "data"}, "messages": ["msg"], "node_results": {}}
        result = {
            "output": "ok",
            "_state_patch": {
                "messages": ["hacked"],
                "node_outputs": {"hacked": True},
                "node_results": {"hacked": True},
                "custom_field": "allowed",
            },
        }
        state = self._apply_wrapping(state, result, "n1")
        assert state["messages"] == ["msg"]
        assert "hacked" not in state["node_outputs"]
        assert "hacked" not in state["node_results"]
        assert state["custom_field"] == "allowed"

    def test_legacy_format_still_works(self):
        state = {"node_outputs": {}, "messages": []}
        result = {
            "messages": ["msg1"],
            "node_outputs": {"agent_1": "response text"},
        }
        state = self._apply_wrapping(state, result, "agent_1")
        assert state["node_outputs"]["agent_1"] == "response text"
        assert state["messages"] == ["msg1"]

    def test_underscore_keys_not_in_port_data(self):
        state = {"node_outputs": {}}
        result = {"_route": "x", "_messages": [], "_state_patch": {}, "output": "ok"}
        state = self._apply_wrapping(state, result, "n1")
        assert state["node_outputs"]["n1"] == {"output": "ok"}

    def test_empty_result(self):
        """Empty dict is falsy so wrapping is skipped — matches orchestrator behavior."""
        state = {"node_outputs": {}}
        state = self._apply_wrapping(state, {}, "n1")
        assert "n1" not in state["node_outputs"]

    def test_none_result(self):
        state = {"node_outputs": {}}
        state = self._apply_wrapping(state, None, "n1")
        assert "n1" not in state["node_outputs"]
