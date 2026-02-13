"""Tests for topology — BFS reachability, loop discovery, entry detection."""

from __future__ import annotations

import pytest

from services.topology import build_topology, _reachable_node_ids, SUB_COMPONENT_TYPES


class TestReachableNodeIds:
    """Test the BFS reachability function directly (no DB needed)."""

    def _edge(self, src, tgt, edge_type="direct", edge_label="", condition_mapping=None):
        """Create a mock edge with the attributes BFS needs."""
        from unittest.mock import MagicMock
        e = MagicMock()
        e.source_node_id = src
        e.target_node_id = tgt
        e.edge_type = edge_type
        e.edge_label = edge_label
        e.condition_mapping = condition_mapping
        return e

    def test_linear_chain(self):
        edges = [
            self._edge("A", "B"),
            self._edge("B", "C"),
            self._edge("C", "D"),
        ]
        assert _reachable_node_ids("A", edges) == {"A", "B", "C", "D"}

    def test_unreachable_nodes(self):
        edges = [
            self._edge("A", "B"),
            self._edge("C", "D"),  # separate component
        ]
        assert _reachable_node_ids("A", edges) == {"A", "B"}

    def test_branching(self):
        edges = [
            self._edge("A", "B"),
            self._edge("A", "C"),
            self._edge("B", "D"),
        ]
        assert _reachable_node_ids("A", edges) == {"A", "B", "C", "D"}

    def test_cycle(self):
        edges = [
            self._edge("A", "B"),
            self._edge("B", "A"),
        ]
        result = _reachable_node_ids("A", edges)
        assert result == {"A", "B"}

    def test_conditional_edges_with_mapping(self):
        edges = [
            self._edge("switch", "target_a", edge_type="conditional", condition_mapping={"route_a": "target_a", "route_b": "target_b"}),
        ]
        result = _reachable_node_ids("switch", edges)
        assert "target_a" in result
        assert "target_b" in result

    def test_single_node_no_edges(self):
        result = _reachable_node_ids("A", [])
        assert result == {"A"}


class TestBuildTopology:
    """Test build_topology() with real DB objects."""

    def _add_node(self, db, workflow, node_id, component_type, extra_config=None):
        from models.node import BaseComponentConfig, WorkflowNode

        cc = BaseComponentConfig(
            component_type=component_type,
            extra_config=extra_config or {},
        )
        db.add(cc)
        db.flush()
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_id,
            component_type=component_type,
            component_config_id=cc.id,
        )
        db.add(node)
        db.flush()
        return node

    def _add_edge(self, db, workflow, src, tgt, edge_type="direct", edge_label="", condition_value=""):
        from models.node import WorkflowEdge

        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=src,
            target_node_id=tgt,
            edge_type=edge_type,
            edge_label=edge_label,
            condition_value=condition_value,
        )
        db.add(edge)
        db.flush()
        return edge

    def test_basic_topology(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        code_node = self._add_node(db, workflow, "code_1", "code")
        self._add_edge(db, workflow, "trigger_1", "code_1")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "code_1" in topo.nodes
        # Triggers are excluded from executable nodes
        assert "trigger_1" not in topo.nodes
        assert topo.entry_node_ids == ["code_1"]

    def test_sub_components_excluded(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        agent = self._add_node(db, workflow, "agent_1", "agent")
        model = self._add_node(db, workflow, "model_1", "ai_model")
        tool = self._add_node(db, workflow, "tool_1", "run_command")

        self._add_edge(db, workflow, "trigger_1", "agent_1")
        self._add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        self._add_edge(db, workflow, "tool_1", "agent_1", edge_label="tool")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "agent_1" in topo.nodes
        assert "model_1" not in topo.nodes
        assert "tool_1" not in topo.nodes

    def test_trigger_scoped_reachability(self, db, workflow):
        trigger_a = self._add_node(db, workflow, "trigger_a", "trigger_manual")
        code_a = self._add_node(db, workflow, "code_a", "code")
        self._add_edge(db, workflow, "trigger_a", "code_a")

        # Separate branch not connected to trigger_a
        trigger_b = self._add_node(db, workflow, "trigger_b", "trigger_schedule")
        code_b = self._add_node(db, workflow, "code_b", "code")
        self._add_edge(db, workflow, "trigger_b", "code_b")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger_a.id)

        assert "code_a" in topo.nodes
        assert "code_b" not in topo.nodes

    def test_loop_bodies_discovered(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        loop = self._add_node(db, workflow, "loop_1", "loop")
        body = self._add_node(db, workflow, "body_1", "code")

        self._add_edge(db, workflow, "trigger_1", "loop_1")
        self._add_edge(db, workflow, "loop_1", "body_1", edge_label="loop_body")
        self._add_edge(db, workflow, "body_1", "loop_1", edge_label="loop_return")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "loop_1" in topo.loop_bodies
        assert topo.loop_bodies["loop_1"] == ["body_1"]
        assert "loop_1" in topo.loop_return_nodes
        assert topo.loop_return_nodes["loop_1"] == ["body_1"]

    def test_loop_body_all_nodes_bfs(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        loop = self._add_node(db, workflow, "loop_1", "loop")
        body_a = self._add_node(db, workflow, "body_a", "code")
        body_b = self._add_node(db, workflow, "body_b", "code")

        self._add_edge(db, workflow, "trigger_1", "loop_1")
        self._add_edge(db, workflow, "loop_1", "body_a", edge_label="loop_body")
        self._add_edge(db, workflow, "body_a", "body_b")  # chain inside body
        self._add_edge(db, workflow, "body_b", "loop_1", edge_label="loop_return")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert set(topo.loop_body_all_nodes["loop_1"]) == {"body_a", "body_b"}

    def test_incoming_count(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        code_a = self._add_node(db, workflow, "code_a", "code")
        code_b = self._add_node(db, workflow, "code_b", "code")
        merge = self._add_node(db, workflow, "merge_1", "merge")

        self._add_edge(db, workflow, "trigger_1", "code_a")
        self._add_edge(db, workflow, "trigger_1", "code_b")
        self._add_edge(db, workflow, "code_a", "merge_1")
        self._add_edge(db, workflow, "code_b", "merge_1")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert topo.incoming_count["merge_1"] == 2

    def test_loop_return_not_counted_in_incoming(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        loop = self._add_node(db, workflow, "loop_1", "loop")
        body = self._add_node(db, workflow, "body_1", "code")

        self._add_edge(db, workflow, "trigger_1", "loop_1")
        self._add_edge(db, workflow, "loop_1", "body_1", edge_label="loop_body")
        self._add_edge(db, workflow, "body_1", "loop_1", edge_label="loop_return")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        # loop_return edges should NOT count toward incoming_count
        assert topo.incoming_count.get("loop_1", 0) == 0

    def test_entry_nodes_from_trigger_targets(self, db, workflow):
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        node_a = self._add_node(db, workflow, "node_a", "code")
        node_b = self._add_node(db, workflow, "node_b", "code")

        # Fan-out from trigger
        self._add_edge(db, workflow, "trigger_1", "node_a")
        self._add_edge(db, workflow, "trigger_1", "node_b")
        db.commit()

        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert set(topo.entry_node_ids) == {"node_a", "node_b"}

    def test_no_executable_nodes_raises(self, db, workflow):
        # Only a trigger, no downstream nodes
        trigger = self._add_node(db, workflow, "trigger_1", "trigger_manual")
        db.commit()

        with pytest.raises(ValueError, match="no executable nodes"):
            build_topology(workflow, db, trigger_node_id=trigger.id)


class TestSubComponentTypes:
    def test_known_sub_components(self):
        expected = {"ai_model", "run_command", "http_request", "web_search",
                    "calculator", "datetime", "output_parser", "memory_read",
                    "memory_write", "code_execute", "create_agent_user",
                    "platform_api", "whoami", "epic_tools", "task_tools",
                    "spawn_and_await", "workflow_create", "workflow_discover",
                    "scheduler_tools", "system_health"}
        assert SUB_COMPONENT_TYPES == expected
