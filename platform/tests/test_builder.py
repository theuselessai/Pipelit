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
        _add_node(db, workflow, "agent_1", "simple_agent", is_entry_point=True)
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
        _add_node(db, workflow, "agent_1", "simple_agent", is_entry_point=True)
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
        _add_node(db, workflow, "agent_1", "simple_agent", is_entry_point=True)
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
        _add_node(db, workflow, "agent_1", "simple_agent", is_entry_point=True)
        _add_node(db, workflow, "code_1", "code")
        _add_edge(db, workflow, "agent_1", "code_1")
        db.commit()

        builder = WorkflowBuilder()
        with patch("components.get_component_factory", return_value=_dummy_factory):
            graph = builder.build(workflow, db)

        assert "agent_1" in graph.nodes
        assert "code_1" in graph.nodes
