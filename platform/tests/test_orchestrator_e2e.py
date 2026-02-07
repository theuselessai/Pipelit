"""Integration tests — build real workflows in DB and verify component execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models.node import BaseComponentConfig, WorkflowEdge, WorkflowNode
from services.topology import build_topology


# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_node(db, workflow, node_id, component_type, extra_config=None, **kwargs):
    cc = BaseComponentConfig(
        component_type=component_type,
        extra_config=extra_config or {},
        **{k: v for k, v in kwargs.items() if k in (
            "system_prompt", "trigger_config", "is_active", "priority",
            "code_snippet", "code_language",
        )},
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


def _add_edge(db, workflow, src, tgt, edge_type="direct", edge_label="",
              condition_value="", condition_mapping=None):
    edge = WorkflowEdge(
        workflow_id=workflow.id,
        source_node_id=src,
        target_node_id=tgt,
        edge_type=edge_type,
        edge_label=edge_label,
        condition_value=condition_value,
        condition_mapping=condition_mapping,
    )
    db.add(edge)
    db.flush()
    return edge


# ── Workflow 1: Linear + Branching ────────────────────────────────────────────


class TestLinearBranchingWorkflow:
    """Build: trigger_manual -> switch -> [branch_a: code] / [default: wait]"""

    @pytest.fixture
    def branching_workflow(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_manual",
                            trigger_config={}, is_active=True)
        switch = _add_node(db, workflow, "switch_1", "switch", extra_config={
            "rules": [
                {"id": "route_code", "field": "node_outputs.trigger_1.text",
                 "operator": "contains", "value": "code"},
            ],
            "enable_fallback": True,
        })
        code = _add_node(db, workflow, "code_1", "code", extra_config={
            "code": "result = 'executed'",
        })
        wait = _add_node(db, workflow, "wait_1", "wait", extra_config={
            "duration": 1, "unit": "seconds",
        })

        _add_edge(db, workflow, "trigger_1", "switch_1")
        _add_edge(db, workflow, "switch_1", "code_1",
                  edge_type="conditional", condition_value="route_code")
        _add_edge(db, workflow, "switch_1", "wait_1",
                  edge_type="conditional", condition_value="__other__")

        db.commit()
        return {"trigger": trigger, "switch": switch, "code": code, "wait": wait}

    def test_topology_builds(self, db, workflow, branching_workflow):
        trigger = branching_workflow["trigger"]
        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "switch_1" in topo.nodes
        assert "code_1" in topo.nodes
        assert "wait_1" in topo.nodes
        assert topo.entry_node_ids == ["switch_1"]

    def test_switch_routes_to_code(self, branching_workflow):
        from components.switch import switch_factory

        switch_node = branching_workflow["switch"]
        fn = switch_factory(switch_node)

        state = {"node_outputs": {"trigger_1": {"text": "run code please"}}}
        result = fn(state)
        assert result["_route"] == "route_code"

    def test_switch_routes_to_default(self, branching_workflow):
        from components.switch import switch_factory

        switch_node = branching_workflow["switch"]
        fn = switch_factory(switch_node)

        state = {"node_outputs": {"trigger_1": {"text": "hello"}}}
        result = fn(state)
        assert result["_route"] == "__other__"

    def test_code_execution(self, branching_workflow):
        from components.code import code_factory

        code_node = branching_workflow["code"]
        fn = code_factory(code_node)

        result = fn({"node_outputs": {}})
        assert result["output"] == "executed"

    def test_wait_produces_delay(self, branching_workflow):
        from components.control_flow import wait_factory

        wait_node = branching_workflow["wait"]
        fn = wait_factory(wait_node)

        result = fn({})
        assert result["_delay_seconds"] == 1.0

    def test_conditional_edges_in_topology(self, db, workflow, branching_workflow):
        trigger = branching_workflow["trigger"]
        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        switch_edges = topo.edges_by_source.get("switch_1", [])
        assert len(switch_edges) == 2
        cond_values = {e.condition_value for e in switch_edges}
        assert cond_values == {"route_code", "__other__"}


# ── Workflow 2: Loop ──────────────────────────────────────────────────────────


class TestLoopWorkflow:
    """Build: trigger_manual -> loop(items) -> code (body)"""

    @pytest.fixture
    def loop_workflow(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_manual",
                            trigger_config={}, is_active=True)
        loop = _add_node(db, workflow, "loop_1", "loop", extra_config={
            "source_node": "trigger_1", "field": "items",
        })
        body = _add_node(db, workflow, "body_1", "code", extra_config={
            "code": "result = f'processed_{state.get(\"_loop_item\", \"\")}'",
        })

        _add_edge(db, workflow, "trigger_1", "loop_1")
        _add_edge(db, workflow, "loop_1", "body_1", edge_label="loop_body")
        _add_edge(db, workflow, "body_1", "loop_1", edge_label="loop_return")

        db.commit()
        return {"trigger": trigger, "loop": loop, "body": body}

    def test_topology_with_loops(self, db, workflow, loop_workflow):
        trigger = loop_workflow["trigger"]
        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        assert "loop_1" in topo.nodes
        assert "body_1" in topo.nodes
        assert topo.loop_bodies == {"loop_1": ["body_1"]}
        assert topo.loop_return_nodes == {"loop_1": ["body_1"]}
        assert set(topo.loop_body_all_nodes["loop_1"]) == {"body_1"}

    def test_loop_extracts_items(self, loop_workflow):
        from components.control_flow import loop_factory

        loop_node = loop_workflow["loop"]
        fn = loop_factory(loop_node)

        state = {"node_outputs": {"trigger_1": {"items": [1, 2, 3]}}}
        result = fn(state)
        assert result["items"] == [1, 2, 3]
        assert result["_loop"]["items"] == [1, 2, 3]

    def test_loop_empty_array(self, loop_workflow):
        from components.control_flow import loop_factory

        loop_node = loop_workflow["loop"]
        fn = loop_factory(loop_node)

        state = {"node_outputs": {"trigger_1": {"items": []}}}
        result = fn(state)
        assert result["items"] == []

    def test_loop_return_edge_not_counted_in_incoming(self, db, workflow, loop_workflow):
        trigger = loop_workflow["trigger"]
        topo = build_topology(workflow, db, trigger_node_id=trigger.id)

        # loop_return should not count as incoming to loop_1
        # Only the trigger->loop edge counts (but trigger is excluded from exec nodes,
        # so incoming from trigger targets as entry point = 0 incoming from exec nodes)
        assert topo.incoming_count.get("loop_1", 0) == 0


# ── Workflow 3: Filter Pipeline ───────────────────────────────────────────────


class TestFilterPipeline:
    """Build: trigger_manual -> code (produces list) -> filter"""

    @pytest.fixture
    def filter_workflow(self, db, workflow):
        trigger = _add_node(db, workflow, "trigger_1", "trigger_manual",
                            trigger_config={}, is_active=True)
        producer = _add_node(db, workflow, "producer", "code", extra_config={
            "code": "result = [{'val': 10}, {'val': 3}, {'val': 8}, {'val': 1}]",
        })
        filter_node = _add_node(db, workflow, "filter_1", "filter", extra_config={
            "source_node": "producer",
            "rules": [{"field": "val", "operator": "gt", "value": "5"}],
        })

        _add_edge(db, workflow, "trigger_1", "producer")
        _add_edge(db, workflow, "producer", "filter_1")
        db.commit()

        return {"trigger": trigger, "producer": producer, "filter": filter_node}

    def test_producer_then_filter(self, filter_workflow):
        from components.data_ops import filter_factory

        # Simulate producer output (code component stringifies, but the
        # orchestrator wraps raw node output into node_outputs).
        # In a real workflow, the filter reads from node_outputs directly.
        producer_data = [{"val": 10}, {"val": 3}, {"val": 8}, {"val": 1}]

        # Run filter with the data
        filter_node = filter_workflow["filter"]
        filter_fn = filter_factory(filter_node)
        state = {"node_outputs": {"producer": producer_data}}
        filter_result = filter_fn(state)

        assert len(filter_result["filtered"]) == 2
        assert all(item["val"] > 5 for item in filter_result["filtered"])


# ── Workflow 4: Merge Fan-In ──────────────────────────────────────────────────


class TestMergeFanIn:
    """Test merge node collecting from multiple upstream nodes."""

    def test_merge_collects_from_branches(self):
        from components.data_ops import merge_factory

        node = MagicMock()
        node.component_config.extra_config = {
            "mode": "append",
            "source_nodes": ["branch_a", "branch_b"],
        }
        fn = merge_factory(node)

        state = {
            "node_outputs": {
                "branch_a": ["result_1"],
                "branch_b": ["result_2", "result_3"],
            },
        }
        result = fn(state)
        assert result["merged"] == ["result_1", "result_2", "result_3"]


# ── Edge Validation Integration ───────────────────────────────────────────────


class TestEdgeValidationIntegration:
    """Validate edges in real workflow structures."""

    def test_valid_linear_workflow(self, db, workflow):
        _add_node(db, workflow, "trigger_1", "trigger_manual",
                  trigger_config={}, is_active=True)
        _add_node(db, workflow, "switch_1", "switch", extra_config={})
        _add_node(db, workflow, "code_1", "code")

        _add_edge(db, workflow, "trigger_1", "switch_1")
        _add_edge(db, workflow, "switch_1", "code_1",
                  edge_type="conditional", condition_value="branch_a")
        db.commit()

        from validation.edges import EdgeValidator
        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert errors == []

    def test_agent_with_model_and_tool_subcomponent_edges_valid(self, db, workflow):
        _add_node(db, workflow, "model_1", "ai_model")
        _add_node(db, workflow, "tool_1", "run_command")
        _add_node(db, workflow, "agent_1", "agent", system_prompt="test")

        # Sub-component edges (llm, tool) should always pass validation
        _add_edge(db, workflow, "model_1", "agent_1", edge_label="llm")
        _add_edge(db, workflow, "tool_1", "agent_1", edge_label="tool")
        db.commit()

        from validation.edges import EdgeValidator
        errors = EdgeValidator.validate_workflow_edges(workflow.id, db)
        assert errors == []
