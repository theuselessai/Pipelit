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


def _add_edge(db, workflow, source, target, edge_label="", edge_type="direct", condition_mapping=None):
    edge = WorkflowEdge(
        workflow_id=workflow.id,
        source_node_id=source,
        target_node_id=target,
        edge_label=edge_label,
        edge_type=edge_type,
        condition_mapping=condition_mapping,
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
        _add_node(db, workflow, "agent_1", "simple_agent")
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
        _add_node(db, workflow, "agent_a", "simple_agent")
        _add_node(db, workflow, "agent_b", "simple_agent")
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
        _add_node(db, workflow, "agent_a", "simple_agent")
        _add_node(db, workflow, "agent_b", "simple_agent")
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
        _add_node(db, workflow, "agent_1", "simple_agent", is_entry_point=True)
        _add_node(db, workflow, "model_1", "ai_model")
        _add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        db.commit()

        topo = build_topology(workflow, db)

        assert "agent_1" in topo.nodes
        assert "model_1" not in topo.nodes

    def test_conditional_edges(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "router_1", "router")
        _add_node(db, workflow, "agent_a", "simple_agent")
        _add_node(db, workflow, "agent_b", "simple_agent")
        _add_edge(db, workflow, "trigger_1", "router_1")
        _add_edge(
            db, workflow, "router_1", "",
            edge_type="conditional",
            condition_mapping={"route_a": "agent_a", "route_b": "agent_b"},
        )
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "router_1" in topo.nodes
        cond_edges = [e for e in topo.edges_by_source.get("router_1", []) if e.edge_type == "conditional"]
        assert len(cond_edges) == 1
        assert cond_edges[0].condition_mapping == {"route_a": "agent_a", "route_b": "agent_b"}

    def test_trigger_scoping(self, db, workflow):
        trigger_a = _add_node(db, workflow, "trigger_a", "trigger_telegram")
        _add_node(db, workflow, "trigger_b", "trigger_webhook")
        _add_node(db, workflow, "agent_a", "simple_agent")
        _add_node(db, workflow, "agent_b", "simple_agent")
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
                "a": {"component_type": "simple_agent"},
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

            _advance("exec-1", "a", state, topo_data, MagicMock())

            mock_queue.enqueue.assert_called_once()
            args = mock_queue.enqueue.call_args
            assert args[0][1] == "exec-1"
            assert args[0][2] == "b"

    def test_advance_conditional_edge(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "router": {"component_type": "router"},
                "a": {"component_type": "simple_agent"},
                "b": {"component_type": "simple_agent"},
            },
            "edges_by_source": {
                "router": [{
                    "source_node_id": "router",
                    "target_node_id": "",
                    "edge_type": "conditional",
                    "condition_mapping": {"go_a": "a", "go_b": "b"},
                }],
            },
            "incoming_count": {"router": 0, "a": 0, "b": 0},
        }
        state = {"route": "go_b"}

        with patch("services.orchestrator._queue") as mock_q, \
             patch("services.orchestrator._redis") as mock_r, \
             patch("services.orchestrator._publish_event"):
            mock_queue = MagicMock()
            mock_q.return_value = mock_queue

            _advance("exec-1", "router", state, topo_data, MagicMock())

            mock_queue.enqueue.assert_called_once()
            args = mock_queue.enqueue.call_args
            assert args[0][2] == "b"

    def test_advance_fanout(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "src": {"component_type": "simple_agent"},
                "a": {"component_type": "simple_agent"},
                "b": {"component_type": "simple_agent"},
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

            _advance("exec-1", "src", state, topo_data, MagicMock())

            assert mock_queue.enqueue.call_count == 2

    def test_advance_fanin_merge(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {
                "a": {"component_type": "simple_agent"},
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

            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_queue.enqueue.assert_not_called()

            # Second parent done — count=2, merge should be enqueued
            mock_redis.incr.return_value = 2
            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_queue.enqueue.assert_called_once()

    def test_advance_no_successors_tries_finalize(self):
        from services.orchestrator import _advance

        topo_data = {
            "nodes": {"a": {"component_type": "simple_agent"}},
            "edges_by_source": {},
            "incoming_count": {"a": 0},
        }
        state = {"route": ""}

        with patch("services.orchestrator._maybe_finalize") as mock_fin, \
             patch("services.orchestrator._publish_event"):
            _advance("exec-1", "a", state, topo_data, MagicMock())
            mock_fin.assert_called_once()


# ── Human confirmation tests ───────────────────────────────────────────────────


class TestHumanConfirmation:
    def test_no_resume_input_returns_cancelled(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {"prompt": "Are you sure?"}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}})

        assert result["route"] == "cancelled"
        assert result["node_outputs"]["confirm_1"]["confirmed"] is False

    def test_resume_input_yes(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {"prompt": "Are you sure?"}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}, "_resume_input": "yes"})

        assert result["route"] == "confirmed"
        assert result["node_outputs"]["confirm_1"]["confirmed"] is True

    def test_resume_input_no(self):
        from components.human_confirmation import human_confirmation_factory

        node = MagicMock()
        node.node_id = "confirm_1"
        node.component_config.extra_config = {}

        fn = human_confirmation_factory(node)
        result = fn({"node_outputs": {}, "_resume_input": "no"})

        assert result["route"] == "cancelled"
        assert result["node_outputs"]["confirm_1"]["confirmed"] is False
