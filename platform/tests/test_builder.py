"""Tests for WorkflowBuilder — verifies graph compilation logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
from services.builder import WorkflowBuilder


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


def _add_edge(db, workflow, source, target, edge_label="", edge_type="direct"):
    edge = WorkflowEdge(
        workflow_id=workflow.id,
        source_node_id=source,
        target_node_id=target,
        edge_label=edge_label,
        edge_type=edge_type,
    )
    db.add(edge)
    db.flush()
    return edge


def _dummy_factory(node):
    """Return a no-op graph node function."""
    def noop(state: dict) -> dict:
        return state
    return noop


class TestBuilderSkipsAiModelNodes:
    """ai_model nodes are sub-components and must not be added to the execution graph."""

    def test_disconnected_ai_model_does_not_break_build(self, db, workflow):
        """A disconnected ai_model (no edges, no config) must be silently skipped."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_node(db, workflow, "orphan_model", "ai_model")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        # Graph should contain only agent_1, not orphan_model
        assert "agent_1" in graph.nodes
        assert "orphan_model" not in graph.nodes

    def test_connected_ai_model_excluded_from_graph(self, db, workflow):
        """An ai_model linked via llm edge is still not an execution node."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_node(db, workflow, "model_1", "ai_model")
        _add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        assert "agent_1" in graph.nodes
        assert "model_1" not in graph.nodes

    def test_multiple_ai_models_all_excluded(self, db, workflow):
        """Multiple ai_model nodes (connected and disconnected) are all excluded."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_node(db, workflow, "model_1", "ai_model")
        _add_node(db, workflow, "model_2", "ai_model")
        _add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        assert "agent_1" in graph.nodes
        assert "model_1" not in graph.nodes
        assert "model_2" not in graph.nodes

    def test_non_subcomponent_nodes_still_included(self, db, workflow):
        """Regular nodes (e.g. code) must still appear in the graph."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_node(db, workflow, "code_1", "code")
        _add_edge(db, workflow, "agent_1", "code_1")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        assert "agent_1" in graph.nodes
        assert "code_1" in graph.nodes


class TestBuilderTriggerScoping:
    """When trigger_node_id is provided, only downstream-reachable nodes are compiled."""

    def test_only_reachable_nodes_from_trigger(self, db, workflow):
        """Nodes not connected downstream from the fired trigger are excluded."""
        trigger_a = _add_node(db, workflow, "trigger_a", "trigger_telegram")
        _add_node(db, workflow, "trigger_b", "trigger_webhook")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "categorizer")
        _add_edge(db, workflow, "trigger_a", "agent_a")
        _add_edge(db, workflow, "trigger_b", "agent_b")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db, trigger_node_id=trigger_a.id)

        assert "agent_a" in graph.nodes
        assert "agent_b" not in graph.nodes

    def test_unreachable_ai_model_excluded(self, db, workflow):
        """An ai_model not connected to the triggered branch is excluded (no error)."""
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "agent_1", "agent")
        _add_node(db, workflow, "orphan_model", "ai_model")
        _add_node(db, workflow, "orphan_agent", "categorizer")
        _add_edge(db, workflow, "trigger_1", "agent_1")
        # orphan_model -> orphan_agent via llm edge (not reachable from trigger_1)
        _add_edge(db, workflow, "orphan_model", "orphan_agent", edge_label="llm")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db, trigger_node_id=trigger.id)

        assert "agent_1" in graph.nodes
        assert "orphan_agent" not in graph.nodes
        assert "orphan_model" not in graph.nodes

    def test_chain_of_nodes_reachable(self, db, workflow):
        """Multi-hop chains downstream of trigger are all included."""
        trigger = _add_node(db, workflow, "trigger_1", "trigger_telegram")
        _add_node(db, workflow, "agent_1", "agent")
        _add_node(db, workflow, "code_1", "code")
        _add_node(db, workflow, "code_2", "code")
        _add_edge(db, workflow, "trigger_1", "agent_1")
        _add_edge(db, workflow, "agent_1", "code_1")
        _add_edge(db, workflow, "code_1", "code_2")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db, trigger_node_id=trigger.id)

        assert "agent_1" in graph.nodes
        assert "code_1" in graph.nodes
        assert "code_2" in graph.nodes

    def test_no_trigger_node_id_includes_all(self, db, workflow):
        """Without trigger_node_id, all nodes are included (backwards-compatible)."""
        _add_node(db, workflow, "trigger_a", "trigger_telegram")
        _add_node(db, workflow, "trigger_b", "trigger_webhook")
        _add_node(db, workflow, "agent_a", "agent")
        _add_node(db, workflow, "agent_b", "categorizer")
        _add_edge(db, workflow, "trigger_a", "agent_a")
        _add_edge(db, workflow, "trigger_b", "agent_b")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        assert "agent_a" in graph.nodes
        assert "agent_b" in graph.nodes


class TestBuilderEdgeTypes:
    """Test conditional, direct, and __end__ edges."""

    def test_conditional_edges_with_condition_value(self, db, workflow):
        """Per-edge condition_value routing should compile conditional edges."""
        _add_node(db, workflow, "switch_1", "switch", is_entry_point=True)
        _add_node(db, workflow, "handler_a", "code")
        _add_node(db, workflow, "handler_b", "code")

        # Conditional edges
        e1 = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="switch_1",
            target_node_id="handler_a",
            edge_label="",
            edge_type="conditional",
            condition_value="route_a",
        )
        e2 = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="switch_1",
            target_node_id="handler_b",
            edge_label="",
            edge_type="conditional",
            condition_value="route_b",
        )
        db.add_all([e1, e2])
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)
        assert "switch_1" in graph.nodes
        assert "handler_a" in graph.nodes
        assert "handler_b" in graph.nodes

    def test_legacy_condition_mapping(self, db, workflow):
        """Legacy condition_mapping on a single edge should work."""
        _add_node(db, workflow, "switch_1", "switch", is_entry_point=True)
        _add_node(db, workflow, "handler_a", "code")

        e = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="switch_1",
            target_node_id="handler_a",
            edge_label="",
            edge_type="conditional",
            condition_mapping={"yes": "handler_a"},
        )
        db.add(e)
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)
        assert "switch_1" in graph.nodes

    def test_direct_edge_to_end(self, db, workflow):
        """A direct edge to __end__ should terminate the graph."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        _add_edge(db, workflow, "agent_1", "__end__")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)
        assert "agent_1" in graph.nodes

    def test_entry_point_from_trigger_target(self, db, workflow):
        """Entry point should be the trigger's target when no is_entry_point."""
        _add_node(db, workflow, "trigger_1", "trigger_manual")
        _add_node(db, workflow, "agent_1", "agent")
        _add_edge(db, workflow, "trigger_1", "agent_1")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)
        assert "agent_1" in graph.nodes

    def test_no_edges_defaults_to_end(self, db, workflow):
        """Nodes with no outgoing edges should be connected to END."""
        _add_node(db, workflow, "agent_1", "agent", is_entry_point=True)
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)
        assert "agent_1" in graph.nodes


class TestReachableNodeIds:
    def test_basic_bfs(self):
        from services.builder import _reachable_node_ids

        edges = [
            WorkflowEdge(source_node_id="a", target_node_id="b", edge_type="direct"),
            WorkflowEdge(source_node_id="b", target_node_id="c", edge_type="direct"),
        ]
        result = _reachable_node_ids("a", edges)
        assert result == {"a", "b", "c"}

    def test_conditional_mapping_targets(self):
        from services.builder import _reachable_node_ids

        edges = [
            WorkflowEdge(
                source_node_id="switch",
                target_node_id="default",
                edge_type="conditional",
                condition_mapping={"a": "node_a", "b": "node_b", "end": "__end__"},
            ),
        ]
        result = _reachable_node_ids("switch", edges)
        assert "node_a" in result
        assert "node_b" in result
        assert "__end__" not in result

    def test_empty_edges(self):
        from services.builder import _reachable_node_ids

        result = _reachable_node_ids("start", [])
        assert result == {"start"}


class TestMakeRouteFn:
    def test_returns_route(self):
        from services.builder import _make_route_fn

        fn = _make_route_fn("node_1")
        assert fn({"route": "yes"}) == "yes"
        assert fn({}) == ""
